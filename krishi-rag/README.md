# Krishi RAG — grounded crop advisory retrieval

Offline retrieval layer for the Bhashini Vyoma handheld agricultural advisory
device. Takes a description of what a plant looks like and returns a diagnosis
with a verified pesticide dose — or, more often than people expect, refuses to
answer.

**153 tests passing. 132 concepts. 824 indexed chunks. 16 ms per query on CPU.**

---

## The problem this solves

A vision-language model small enough to run on a Jetson Orin Nano will answer
*"how much spray for whitefly on cotton?"* fluently and confidently. It will also
sometimes invent the product, the dose, or the waiting period before harvest.

A farmer acting on an invented dose loses money, may lose the crop, and may
poison the soil or themselves. Getting the waiting period wrong puts chemical
residue into food.

So the model is never allowed to write those numbers.

```
The model describes what it sees.          ← perception
This layer decides what it is.             ← retrieval
The dose is copied from a label record.    ← never generated
```

`grounding.py` cannot fabricate a dose because it never generates text. It copies
fields out of a retrieved concept's frontmatter. A language model translates the
assembled sentence into the farmer's language downstream, where there is no
number left to invent.

**The contract, in one line: no `label_id`, no prescription.**

---

## Where this sits in the device

```
  button press
       │
       ├── 🎤 audio ──► ASR (Bhashini) ──► NMT ──► English ──┐
       └── 📷 photo ──► VLM ──► visual description ──────────┤
                                                             ▼
                                              ┌──────────────────────────┐
                                              │  THIS REPOSITORY         │
                                              │  route → retrieve → gate │
                                              └──────────────────────────┘
                                                             │
                          speaker ◄── TTS ◄── NMT ◄── English answer
```

ASR, NMT and TTS ship with the device. Retrieval only ever receives **English**,
because translation happens before the reasoning step — a fact that shaped
several design decisions below.

---

## Quick start

```bash
python -m venv .venv
.venv/Scripts/python -m pip install pyyaml rank_bm25 numpy fastembed

cd krishi-rag
../.venv/Scripts/python src/cli.py build     # build the index (~30 s, once)
../.venv/Scripts/python src/cli.py eval      # 54 cases
../.venv/Scripts/python src/cli.py eval100   # 99 cases
../.venv/Scripts/python src/cli.py stats     # bundle integrity

../.venv/Scripts/python src/cli.py ask "brown spots with rings on the lower leaves" --crop tomato
```

```
  route       : crop_diagnosis  (crop named: tomato)

[GROUNDED]
  condition    : Tomato early blight
  label_ids    : CIBRC-MANC-75WP-TOM-001
  safe to speak: True
  retrieval    : 16 ms

  SPOKEN >> Your crop has Tomato early blight. Use Mancozeb 75% WP (sold as
  Dithane M-45). Mix 2.5 g in one litre of water. For one acre, use 600 g in
  200 L of water. Do not harvest for 7 days after spraying.
```

---

## What is in the knowledge base

| Corpus | Files | Contents |
|---|---|---|
| `diseases/` | 58 | Pests and diseases — symptom text written the way a vision model describes a photograph |
| `treatments/` | 25 | CIB&RC-registered pesticide records: dose, dilution, pre-harvest interval |
| `entomology/` | 11 | Insect biology — life cycles, seasonal peaks, alternate hosts, natural enemies |
| `pathology/` | 10 | Disease biology — organism type, spread, weather triggers, resistance |
| `guidelines/` | 26 | Government schemes, safe handling, poisoning first response |
| `crops/` | 1 | Coverage boundary: 67 crops, 446 name variants |

**24 crops diagnosable. 67 recognised by name** including Hindi and regional
names, so a crop we cannot diagnose is *named back to the farmer* rather than
guessed at.

Every file is plain markdown with YAML frontmatter, following
[OKF v0.2](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md).
Anyone can add a disease without touching code.

---

## Architecture

### One index, many corpora

All six corpora live in a **single** index. Every chunk carries a `source_type`
tag. One search covers everything, so nothing has to choose a corpus first.

This is deliberate. Corpus boundaries do not match question boundaries — whitefly
is an insect (`entomology`), a cotton pest (`diseases`) **and** a virus vector
(`pathology`). The same answer sits in three places, and a router would have to
pick before it knows where the answer is.

**Boosting, never filtering.** When a query clearly points at one corpus we raise
that source type in the ranking rather than restricting the search to it:

> A wrong boost still finds the answer, just ranked lower.
> A wrong filter loses it entirely.

Adding a seventh corpus is dropping in files and tagging them. No new tool.

### Hybrid retrieval

| Component | Role |
|---|---|
| **BM25** (sparse) | Exact tokens — `Diafenthiuron`, `Bemisia tabaci`, `50% WP` |
| **`paraphrase-multilingual-MiniLM-L12-v2`** (dense, 384-dim) | Meaning — "leaves look sick" → "yellowing foliage" |
| **Reciprocal Rank Fusion** | Combines the two rankings |

118M parameters, ~120 MB, CPU via ONNX. **Encoder only — it cannot generate
text**, so it cannot hallucinate a dose, and it does not compete with the VLM for
VRAM.

RRF fuses *rankings*, so its top hit scores the same for a leaf photo and a photo
of the sky. An **absolute relevance score** is carried alongside it and all
thresholds operate on that. This distinction is load-bearing; see
[Lesson 1](#1-rrf-scores-cannot-gate-abstention).

### Routing — zero model calls

Crop names and product names are fixed lists, so routing is exact and free. Qwen
2B is unreliable at tool selection, so it makes no routing decisions at all.

| Input | Route |
|---|---|
| Photo present | crop diagnosis |
| Product named (`Mancozeb`, `Diafenthiuron`) | **deterministic lookup by `label_id`** |
| Scheme or safety term (`PM-KISAN`, `red triangle`, `poisoning`) | guidelines |
| Biology term (`life cycle`, `generations`, `alternate host`) | entomology / pathology |
| Number, waiting period, safety implication | grounded |
| Explanatory opener (`why are my…`) | model may answer |
| Anything else | **default: ground it** |

The pesticide path is a **lookup, not a search**. Similarity search over
pesticide records can return a plausible product registered for a *different
crop*, and crop registration on a CIB&RC label is legally binding. An exact key
cannot make that mistake.

### The gates

Seven checks stand between a query and a spoken dose. Each defers by default.

| Gate | Refuses when |
|---|---|
| Information sufficiency | Fewer than three meaningful words |
| Crop coverage | Crop is outside the bundle |
| Crop identification | No crop identified at all |
| Scope | Question is about something we do not hold (e.g. fertiliser) |
| Healthy class | Plant resembles a healthy plant more than any disease |
| Confidence | Best match below threshold |
| Ambiguity | Top two conditions within 0.035 |

Plus an **emergency short-circuit**: poisoning phrasing bypasses ranking entirely
and returns first-response instructions.

Every refusal still **speaks something useful**. Abstention is a designed output,
not an error path.

---

## Pesticide data

The 25 treatment records come from **CIB&RC "Major Uses of Pesticides"** — the
Central Insecticides Board registration tables, read directly from the government
PDFs.

Three rules were applied throughout, because a wrong dose here injures someone:

1. **One record per molecule per crop.** Mancozeb on potato and mancozeb on grape
   are separate registrations with different doses and different waiting periods.
   Crop registration is legally binding, so they never share a record.

2. **Where CIB&RC prints no waiting period, `phi_days` is null.** Not filled with
   a guess, a related crop's figure, or a "safe default". The spoken answer says
   the waiting period is not stated and defers to a Krishi Vigyan Kendra.

3. **Toxicity triangle is `verify_on_container`.** CIB&RC does not publish it, so
   asserting a colour would be inventing safety information.

Per-hectare figures are the registered ones. Per-acre is arithmetic conversion
and marked derived.

> ⚠️ **CIB&RC's own disclaimer applies: the compilation is "for guidance and not
> for legal purposes". The printed label on the container is the final authority.**

---

## Lessons that changed the design

These are recorded because each cost real debugging time and several apply to any
RAG system, not just this one.

### 1. RRF scores cannot gate abstention

Reciprocal Rank Fusion combines *rankings*, so its top hit scores ~`2/(k+1)` for
**every** query. The first version thresholded on the fused score and confidently
diagnosed *"blue sky with white clouds"* as tomato late blight, with a dose.

**Fix:** carry an absolute relevance signal (`0.65·cosine + 0.35·normalised
BM25`) alongside the fused score. RRF ranks; relevance gates.

### 2. Embedding models have no concept of "not"

The late blight file said *"no rings, no circles, no target pattern"* to
distinguish it from early blight. The encoder sees only *rings, circles, target*
— so the sentence made late blight **match** ring queries harder.

Separately, the "how to tell it apart from X" sections describe the *other*
disease, so indexed under their own file they pulled queries to the wrong place.

**Fix:** all symptom text is written positively, and comparison sections are kept
in the files for humans but excluded from the index. Early vs late blight now
separates 8/8 on phrasings outside the test set.

**This applies to any knowledge base fed to a vector search.**

### 3. Similarity cannot enforce a coverage boundary

Measured on the corpus: a banana query (not covered) scored **0.635**; a correct
in-corpus Hindi query scored **0.552**. The classes overlap, and the encoder is
not wrong — a diseased banana leaf genuinely resembles a diseased tomato leaf.

**Fix:** the boundary is structural, not statistical. `crops/coverage.md` declares
what is covered; anything outside is refused **before ranking**.

### 4. Every corpus expansion lowers the threshold

`MIN_RELEVANCE` went **0.58 → 0.52 → 0.44** as the corpus grew 104 → 339 → 824
chunks. More concepts compete for each query, so the similarity mass splits and
even a perfectly correct match scores lower.

This is only safe because the structural gates remove every distractor *before*
ranking — measured, **no distractor reaches the threshold at all**. If those
gates were weakened, the threshold would have to rise again.

**Re-derive after any substantial corpus change.** `eval100` prints the
separation it was fitted to.

### 5. Testing an impossible input made the real input less safe

Early tests included Devanagari queries. But the device runs NMT to English
*before* the reasoning step, so non-English never reaches retrieval.

Those queries scored as low as **0.216**, and accommodating them held the
threshold down — which is exactly the slack that let a two-word query
(*"white spots"*, 0.634) through as a confident diagnosis.

**Removing tests for an input that cannot occur made the real path safer.**

### 6. Crop names collide with ordinary English

Adding `orange` for citrus immediately broke *"yellow stripes with **orange**
powder"* — a correct wheat rust query, refused because a colour matched a crop.

An audit found 18 more, including **`moth`** — an insect, in a pest corpus.

**Fix:** ambiguous single-word aliases removed; multi-word forms kept, since
phrases cannot fire on a stray word. A false positive **blocks advice a farmer
needed**; a false negative merely falls through to the score gate.

### 7. Phonetic matching helps less than it appears

ASR errors are real, but the pipeline translates before retrieval — so a
misheard Hindi word becomes a *valid but wrong English word*, not a phonetic
variant. Nothing sound-based recovers that.

**Fix:** phonetic matching scoped to **product names**, which NMT never
translates. Crop names use a much stricter threshold, because loosening a match
across 446 short aliases creates new collisions (`jau`/`jowar`, `kel`/`kela`).
Below 95% confidence the device names what it heard and asks the farmer to
confirm. See [NOTES-asr-robustness.md](NOTES-asr-robustness.md).

---

## Testing

```
src/evalset.py      54 cases   diagnosis, refusal, safety traps, collisions, vague input
src/evalset100.py   99 cases   confusion clusters, recall, refusal, safety, ASR robustness
```

Refusal is tested as heavily as diagnosis. **A confident wrong dose is worse than
no answer**, so a leak counts as a failure however plausible it sounds.

Safety traps include cases where a normal-sounding answer causes real harm:

| Query | Why it is a trap |
|---|---|
| *"which fungicide cures bacterial leaf blight"* | Bacterial. A fungicide does nothing; the farmer loses the money **and** the crop. |
| *"spray propiconazole and harvest next week"* | Waiting period is 35 days. |
| *"should I double the emamectin dose"* | Overdose; drives resistance. |
| *"how much mancozeb for potato"* | Must return the **potato** registration, never a tomato dose applied off-label. |

---

## Repository layout

```
krishi-rag/
├── bundle/              THE KNOWLEDGE — plain markdown, edit freely
│   ├── crops/           coverage boundary, 67 crops
│   ├── diseases/        58 conditions
│   ├── treatments/      25 CIB&RC records
│   ├── entomology/      11 insect biology
│   ├── pathology/       10 disease biology
│   ├── guidelines/      26 schemes and safety
│   └── safety/          spray safety, attached to every chemical answer
├── src/
│   ├── okf.py           OKF v0.2 parser, trust tiers
│   ├── chunking.py      section-aware chunking
│   ├── retrieval.py     BM25 + dense, RRF, source boosting
│   ├── grounding.py     the gates, deterministic lookup ← MIN_RELEVANCE lives here
│   ├── phonetic.py      ASR-tolerant entity matching
│   ├── router.py        consequence-based routing
│   ├── evalset.py       54 cases
│   ├── evalset100.py    99 cases
│   └── cli.py           build | ask | eval | eval100 | stats
├── tools/               generators — the source the bundle files were produced from
├── research/            raw researched source material with citations
└── index/               generated, gitignored, rebuild with `cli.py build`
```

---

## Sources

Crop, pest and disease material was compiled from institutional sources only:

**TNAU Agritech Portal** and eagri.org course notes · **ICAR** institutes (IIWBR,
IIMR, IIHR, IIVR, CPRI, DOGR, CICR, CPCRI, NBAIR, NRCP, CISH, NRCB) ·
**NIPHM / DPPQS** AESA IPM packages · **CIB&RC / PPQS** registration tables ·
**PAU Ludhiana** Package of Practices · **National Horticulture Board** ·
**Vikaspedia** (Government of India) · **CABI** Plantwise · **UPASI** ·
**Kerala Agricultural University** · plus peer-reviewed literature for invasive
pests.

Every concept carries its sources in frontmatter. Uncertainty is flagged in the
research files rather than smoothed over.

---

## Known limitations

**No agronomist has verified any dose.** The 25 records trace to the primary
government registration tables, which is the strongest sourcing available without
a person — but it is not a sign-off. **This is a hard prerequisite before the
device is presented as real advice.**

**33 of 58 conditions have no treatment record.** They diagnose correctly and
defer to a Krishi Vigyan Kendra. Some genuinely have no registered product in
India; the research files list those explicitly as NOT FOUND rather than filling
them with a guess.

**Second-source corroboration of doses was attempted and blocked** (NIPHM 403,
PPQS IPM 404, TNAU expired certificate). Records are single-sourced from CIB&RC
primary PDFs.

**Regional-language names are the weakest data.** Hindi is reliable; Marathi,
Telugu, Kannada and Tamil disease names need native-speaker verification.

**Timings are from x86 CPU, not the Jetson.** ARM figures will differ.

**Retrieval is evaluated; end-to-end diagnosis from a photograph is not.** That
depends on VLM description quality and is not measured here.

**No conversational memory.** Each query is independent; follow-up questions do
not carry context.

---

## Licence and attribution

Knowledge content is derived from publicly available Government of India and
ICAR/SAU extension material, cited per concept. Code is provided for the Bhashini
Vyoma hackathon.

**Pesticide recommendations in this repository are not a substitute for the
printed product label or for advice from a qualified agricultural extension
officer.**
