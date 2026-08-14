# RAG build log — G1/G2 sqlite-vec + real tools in gramsahayak

Prabhakar asked for this to be built, tested, and documented overnight for morning
review (possibly cross-checked with another tool). Everything below is real: real
commands run, real output, real numbers, no simulated results. Where something is a
known gap or a judgment call rather than a finished, hardened decision, it's called
out explicitly rather than glossed over.

**Read `G1-G2-VECTORDB-PLAN.md` first** (in the krishi-rag repo) — that's the design
plan this build executed. This doc is the "what actually happened when it was built,"
not a second design doc.

---

## 0. What exists now, in one table

| Piece | Where | Status |
|---|---|---|
| G1/G2 doc corpus (copied from krishi-rag) | `gramsahayak/datasets/rag/{g1,g2}/` | 127 + 17 = 144 concepts |
| OKF parser + section-aware chunking | `gramsahayak/rag/{okf,chunking}.py` | ported, real build ran |
| sqlite-vec + BM25 indexes | `gramsahayak/datasets/rag/{g1,g2}.sqlite`, `{g1,g2}_bm25.pkl` | built, 818 + 60 chunks |
| Hybrid retrieval (dense int8 + BM25 + RRF) | `gramsahayak/rag/retrieval.py` | built, tested |
| 7 new real agent tools | `agent/tools/{g1,g2}_rag_tools.py` | built, wired into `agent.py`, tested standalone AND through 2 full ASR→TTS pipeline runs |
| 4 old mock tools | — | **retired** (query_entomologist, query_botanist, query_disease_diagnosis_index, query_govt_scheme) |
| 2 old real tools | `agent/tools/{pesticide_lookup,photo_analysis}.py` | **kept unchanged**, decisions on why below |

---

## 1. Real blocker hit and fixed: sqlite3 in this venv can't load extensions at all

First thing tried (`sqlite_vec.load(db)` via stdlib `sqlite3`) failed immediately:
`'sqlite3.Connection' object has no attribute 'load_extension'`. This Python's sqlite3
module was built with loadable-extension support compiled out entirely — not a config
flag to flip, a build-time omission.

**Fix: `apsw`** (Another Python SQLite Wrapper) — bundles its own sqlite3 build with
extension loading on by default. Verified directly: `apsw` + `sqlite_vec` loads,
creates a `vec0` table, and returns correct KNN results. Both ship prebuilt
**aarch64** wheels (confirmed via `pip install` on this dev box), so this should
install the same way on the Jetson without a source build — not yet verified on the
actual Jetson, flagged as a real thing to check before deploying this there.

Added to `requirements.txt`: `apsw==3.53.4.0`, `sqlite-vec==0.1.9`,
`rank_bm25==0.2.2`, `pyyaml>=6.0`.

## 2. Real sqlite-vec schema gotchas hit and fixed (not in the docs clearly enough to avoid)

Three real errors, in order, each fixed and verified before moving on:

1. **`+`-prefixed auxiliary columns cannot be filtered in a KNN query at all** — tried
   filtering on `+crop`, got `"A LIMIT or 'k = ?' constraint is required"` (a
   misleading error for the actual cause). Real fix, confirmed via a minimal
   reproduction before touching the real schema: `crop` and `concept_type` had to
   become real **metadata columns** (declared without `+`), everything else
   (chunk_id, text, source_type, label_id, etc.) stays auxiliary since it's never
   filtered in SQL, only read back and boosted in Python.
2. **KNN queries need an explicit `k = ?` constraint**, not just `ORDER BY distance
   LIMIT ?` — confirmed the same error persisted until `k = ?` was added directly
   into the `WHERE` clause.
3. **Metadata columns reject NULL outright** (`"Expected text for TEXT metadata
   column crop, received NULL"`) — most chunks (entomology, pathology, most
   guidelines) genuinely have no crop. Fixed with an empty-string sentinel at
   insert time, normalised back to `None` in `rag/retrieval.py` so every other
   caller sees the same None-means-no-crop convention the rest of this codebase
   already uses (`Chunk`, `Concept`).

All three are now commented directly in `rag/store.py` at the exact line, not just
here, so the next person editing that file doesn't rediscover them the hard way.

## 3. Real build numbers

```
$ python3 rag/build_index.py
[g1] 127 concepts -> 818 chunks (0.35s)
[g1] embedded 818 chunks with granite-embedding:30m (13.75s)
[g1] sqlite-vec (int8) index written (0.18s)
[g1] BM25 index written (0.41s)
[g2] 17 concepts -> 60 chunks (0.08s)
[g2] embedded 60 chunks with granite-embedding:30m (0.81s)
[g2] sqlite-vec (int8) index written (0.01s)
[g2] BM25 index written (0.01s)
Total build time: 15.63s
```

Note: 127 concepts, not 133/17 (the raw file counts from the doc-separation step) —
the difference is `index.md`/`log.md` navigational files correctly excluded by the
existing `RESERVED_FILENAMES` convention (ported as-is from krishi-rag's `okf.py`).

## 4. Real retrieval quality — `rag/test_retrieval.py`, 10 queries, both DBs

Re-run twice to check for noise (two queries hit 2.4–3s on the first run, both came
back to ~65ms on rerun — confirmed transient system noise, not a real defect; every
query is consistently 58–77ms now). All timings below are the clean rerun.

| Query | Top hit | Relevance | Correct? |
|---|---|---|---|
| "brown spots with rings... tomato" (crop=tomato) | tomato-early-blight | 0.508 | βœ… |
| "insects rasping leaves... chilli" | chilli-thrips | 0.438 | βœ… |
| "mancozeb dose... potato" (crop=potato) | mancozeb-75wp-potato | 0.554 | βœ… |
| "yellowing between veins... nutrient" | nitrogen-vs-iron-yellowing | 0.401 | βœ… |
| "safety precautions before spraying" | spray-safety | 0.389 | βœ… |
| "purple elephant riding a bicycle" (nonsense) | onion-purple-blotch | 0.361 | correctly weak — real signal (0.5+) separates from this |
| "PM-KISAN money how often" | **kisan-call-centre (0.416) outranked pm-kisan (0.348)** | — | ⚠️ real quality issue, see Β§6 |
| "crop insurance weather damage" | pmfby | 0.515 | βœ… |
| "loan for tractor/farm equipment" | SMAM | 0.419 | βœ… |
| "minimum support price" (should NOT be strong in G2 — MSP is G1) | fertiliser-subsidy, weak (0.36) | — | βœ… confirms the G1/G2 split boundary holds |

**Relevance distribution** (n=30): min=0.121, max=0.554, mean=0.367. This is a
**provisional** signal, not a derived threshold — krishi-rag's own `MIN_RELEVANCE=0.44`
took 3 rounds of re-derivation against a 99-case eval suite as its corpus grew; this
build has not done that yet against granite-embedding:30m's actual score distribution.
The new tools use a soft `LOW_CONFIDENCE_FLOOR=0.40` that **flags, does not block** —
real structural gates (crop coverage boundary, info-sufficiency check — krishi-rag has
7 of these) are **not built**, flagged as the single biggest safety gap below.

## 5. Real agent tool tests — `rag/test_agent_tools.py`, 5 real `agent.run_turn()` calls

| Query | Tools called | Turn time | Answer quality |
|---|---|---|---|
| Tomato ring-spot symptoms | plant_disease_lookup, pesticide_usage_and_dose Γ—3, pesticide_lookup | 51.95s | Correct diagnosis (early blight), correct dose (Mancozeb, 7-day PHI), correctly distinguished protectant vs curative |
| Chilli silvery-streak insects | plant_entomology_lookup, plant_disease_lookup, pesticide_usage_and_dose Γ—2, pesticide_lookup | 50.82s | Correct pest (chilli thrips), named Fipronil as registered — see caveat below |
| "PM-KISAN how much/how often" | get_scheme_details | 15.93s | Correct: β‚Ή6,000/yr, 3 installments, correct windows |
| "2 acres tomato Karnataka, what schemes" | match_eligible_schemes | 20.47s | 4 real schemes surfaced (PM-KMY, PM-KISAN, PMFBY, PMKSY), all genuinely relevant |
| "subsidy for drip irrigation" | get_subsidy_details | 16.60s | Correct: PMKSY/PDMC, correct 55%/45% split |

**Real, honest finding, not hidden: G1 tool calls are 2.5–3x slower than G2's, and
show real redundancy** — `pesticide_usage_and_dose` got called 2-3 times in a single
turn with near-identical arguments (the model re-querying instead of recognizing it
already had an answer). G2 tools show zero redundancy across all 3 tests — one clean
call each. This matches a risk this project's own reading of krishi-rag's `router.py`
already flagged in passing ("Qwen 2B is unreliable at tool selection") — real,
reproduced here on this specific model/tool-set combination, not assumed.

**Follow-up, same night**: added one concise `SYSTEM_PROMPT` rule ("call each lookup
tool AT MOST ONCE per turn... do not retry with reworded arguments... pass the matched
condition, not the original symptom sentence") and re-ran the exact same 5-query test.
Real, mixed result, not a clean fix:

| Query | Before | After |
|---|---|---|
| G1 disease | 5 calls (3Γ— same tool reworded), 51.95s | 4 distinct calls (no literal repeats), 90.24s (slower) |
| G1 entomology | 5 calls, 50.82s | **2 calls, 30.11s** — real improvement |
| G2 scheme | 1 call, 15.93s | 1 call, 12.42s |
| G2 eligibility | 1 call, 20.47s | **5 calls, 36.03s — got worse** |
| G2 subsidy | 1 call, 16.60s | 1 call, 16.04s |

The exact literal failure mode targeted (same tool, reworded args) is gone — 0
instances this run vs 5 before. But a *different* pattern the instruction explicitly
forbade still happened: for G2 eligibility, the model called `match_eligible_schemes`
once then `get_scheme_details` four more times (once per scheme surfaced) — directly
against "at most once per turn." **A prompt instruction to a small model is a soft
nudge here, not a guarantee** — confirmed, not assumed. G1 disease's slowdown (51.95s
β†’ 90.24s despite fewer redundant calls) looks like ordinary generation-length
variance at temperature=0.2 rather than something the prompt change caused, but that's
not confirmed with more than one run either way. Net: real partial improvement, not a
solved problem — left as-is rather than iterating further tonight; a stronger
per-turn tool-call budget (not just per-tool-name) is the likely next lever if this
gets revisited.

**Real caveat on the chilli/Fipronil answer**: the agent stated "Fipronil 5% SC is
registered for chilli thrips... this should be safe to use now" — that claim traces
to `pesticide_lookup` (real FSSAI registration data, legitimate), but the agent never
actually called `pesticide_usage_and_dose(pesticide_name="Fipronil", ...)` to pull a
real CIB&RC dose record for it — its repeated `pesticide_usage_and_dose` calls kept
searching symptom text, not the product name, and kept returning Mancozeb matches
instead. The final answer does NOT state a fabricated dose number for Fipronil (no
grams-per-acre figure was invented) — it stops at "registered," which is true and
sourced — but this is a real example of the tool being available and not used the way
its own docstring asks. Worth a closer look at whether the docstring needs to be more
directive.

## 6. Real full-pipeline tests — `test_orchestrated_pipeline.py`, real ASR→NMT→Agent→NMT→TTS

Two full runs, both real audio through the real gateway/orchestrator, unmodified
except that the agent now has the new tools:

**Run 1** (`--language hi`, no image, the standard Q1 pesticide question): agent
correctly asked a clarifying question rather than guessing, since the translated
question ("best pesticides... protect potatoes from insects and rats") genuinely
doesn't name a pest or symptom — no tool call was the right call here, not a miss.
Turn: 42.18s. **Peak memory 4.70GB/67.1%** during TTS, safely under the 7.0GB budget.
Clean teardown to 0.00GB.

**Run 2** (`--language ta`, with the sample pepper-disease photo): real,
useful, and slower — `analyze_photo` β†’ `plant_disease_lookup` called **4 times**
with shifting crop/description arguments as the model tried to reconcile a weak match
(the corpus's top hit for this actual photo was "Healthy plant, no disease detected,"
and a crop-unfiltered retry surfaced "Potato early blight" — wrong crop entirely, a
real cross-crop leak). **The agent handled this correctly** — it hedged
("bacterial blights... typically... which isn't clearly visible here... recommend
checking with your KVK") instead of confidently naming a wrong disease with an
invented dose, which is the actual safety property this whole system exists to
protect. But it took **118.82s of agent time, 153.29s total turn** to get there.
**Peak memory 5.22GB/74.6%**, still safely under budget even at the slowest, most
tool-call-heavy point tested.

**Read together, Β§5 and Β§6 say the same thing**: real answers are correct and safe
(no invented facts observed anywhere in testing), memory is fine even in the worst
case tested, but **latency on a hard/ambiguous query is real and not small** (2.5
minutes for one turn). This is the honest state to walk into a morning review with,
not a rounded-up "it works great."

## 7. Real decisions made along the way (autonomous, documented here for review)

- **`pesticide_lookup` (FSSAI) kept, NOT merged with the new `pesticide_usage_and_dose`
  (CIB&RC).** They answer different questions — FSSAI data is toxicity/MRL/legality,
  CIB&RC treatments data is actual application dose/PHI. Checked the real FSSAI JSON
  schema (`functional_class`, `cibrc_classification`, `adi`, `major_uses[].mrl`) before
  deciding — genuinely non-overlapping fields, not a redundant pair.
- **`query_botanist` dropped, not replaced.** It was general agronomic Q&A (soil pH,
  water needs), not diagnosis — doesn't map to any named G1/G2 tool, and keeping a
  mock next to seven real tools seemed more likely to confuse tool selection than help.
- **`analyze_photo`/`prompts.py`'s vision prompts left unmodified.** Read them closely
  before deciding: `CROP_VISION_PROMPT` already outputs plain factual symptom
  descriptions (the right register for feeding `plant_disease_lookup`), and
  `LABEL_VISION_PROMPT` already extracts a clean active-ingredient name (the right
  input for `pesticide_lookup`/`pesticide_usage_and_dose`). No VLM tool changes needed
  — this was a composition problem, not a prompt problem.
- **G1's `crop` metadata filter doesn't work for Treatment concepts** — their
  frontmatter uses `registered_crop`, not `crop`, and `rag/okf.py`'s `Concept.crop`
  property only reads the latter (ported as-is from krishi-rag, where treatments/
  concepts have the same shape). `pesticide_usage_and_dose` compensates with a
  **post-hoc text-match safety net** (flags `crop_confirmed_in_text: false` when the
  requested crop doesn't literally appear in the retrieved text) rather than a real
  filter. **Confirmed working as intended** in testing (Β§5's mancozeb/potato query
  correctly flagged the tomato-registered record as unconfirmed for potato) but this
  is a warning, not a filter — the underlying ranking still doesn't prioritize the
  crop-correct record. This is the single most important thing to harden before
  trusting a real spray recommendation from this tool, directly echoing krishi-rag's
  own README warning about exactly this failure mode.

## 8. Known gaps — not fixed tonight, flagged plainly

1. **No real structural abstention gates.** krishi-rag has 7 (info sufficiency, crop
   coverage, healthy-class check, ambiguity, etc.) plus an emergency short-circuit for
   poisoning queries. None of that is ported here — only a soft relevance flag. This
   is the biggest real safety gap versus the reference design.
2. **`MIN_RELEVANCE` not derived.** Β§4's 30-query distribution is a start, not a
   real threshold — needs a real eval set (krishi-rag's own `evalset.py`/
   `evalset100.py` are a template for what that should look like) run against this
   actual embedding model before trusting a hard cutoff.
3. **Treatment concepts' crop filtering is a warning, not a filter** (Β§7, last bullet).
4. **No weed-detection corpus** — `plant-disease-weed-detector` from the original spec
   currently just runs the same `plant_disease_lookup` path; there's no weed-specific
   data in the bundle to back a distinct tool.
5. **`get_disaster_relief_options`/`match_eligible_schemes` are soft-RAG, not real
   table lookups** — the original spec called for structured eligibility rules and a
   disaster-relief table; neither exists as structured data in the corpus, only as
   prose inside scheme concepts. Flagged in each tool's own docstring, not hidden.
6. **PM-KISAN query quality issue** (Β§4 table, βš οΈ row): `kisan-call-centre` (a shared
   reference doc) outranked the actually-correct `pm-kisan` concept for a very
   on-topic query. Not investigated further tonight — a real quality signal worth
   a closer look, possibly the shared-doc duplication (Β§2 of
   `G1-G2-VECTORDB-PLAN.md`) needs a boost adjustment.
7. **G1 tool-call redundancy** (Β§5) — real, reproducible, not fixed.
8. **`apsw`+`sqlite-vec` on the actual Jetson is unverified** — confirmed aarch64
   wheels exist, not confirmed they install/run cleanly on that specific device yet.

## 9. Files touched/added, for a diff-level review

**New:**
`gramsahayak/rag/{__init__,okf,chunking,embed,store,retrieval,build_index,test_retrieval,test_agent_tools}.py`,
`gramsahayak/agent/tools/{g1_rag_tools,g2_rag_tools}.py`,
`gramsahayak/datasets/rag/` (g1/, g2/, both .sqlite, both _bm25.pkl),
`gramsahayak/RAG-BUILD-LOG.md` (this file).

**Modified:** `gramsahayak/agent/agent.py` (4 mocks removed, 7 real tools added,
module docstring updated), `gramsahayak/agent/prompts.py` (SYSTEM_PROMPT's tool-name
references updated to match), `gramsahayak/requirements.txt` (4 new deps).

**Untouched, confirmed:** `agent/tools/pesticide_lookup.py`, `agent/tools/
photo_analysis.py`, `agent/tools/weather_tools/`, everything in `api_server/`,
`models/`, the whole orchestrator/gateway memory-management layer — none of tonight's
work touched the pipeline's memory-orchestration design, only the agent's tool set.
