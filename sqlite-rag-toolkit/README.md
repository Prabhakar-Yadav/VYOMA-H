# sqlite-rag-toolkit

Standalone toolkit for growing the G1 (plant/crop) and G2 (govt schemes) knowledge
corpora that back GramSahayak's RAG tools -- add new documents, build/update the
sqlite-vec + BM25 index, then copy the two resulting files onto whatever device
actually serves them (Jetson or otherwise). This folder is self-contained on
purpose: it doesn't depend on anything else in the main `gramsahayak/` app, so a
doc-writing contributor doesn't need the whole ASR/TTS/agent pipeline set up just to
add a new pesticide record.

Everything in `rag/` here is a real copy of the same code the live pipeline runs
(`gramsahayak/rag/`) -- not a simplified/toy version, but deliberately scoped to
INGESTION only (parsing/chunking/embedding/storing documents), not the query-side
hybrid search the live agent tools call to retrieve them -- see Β§3's note on why
`rag/retrieval.py` isn't bundled here. `datasets/rag/` is the real, current
production corpus (127 G1 concepts, 17 G2 concepts) -- confirmed byte-identical
(sha256) to what's actually live on the Jetson deployment at the time this branch
was cut, not a stale or divergent copy. Included as both a working starting point
and the best reference for how to write a new document correctly (read a few real
files before writing your first one).

## 1. Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

You also need a local Ollama server running with the embedding model pulled --
building/appending to the index calls it for every new/changed chunk:

```bash
ollama pull granite-embedding:30m
```

(`rag/embed.py` forces this model to run CPU-only, not GPU -- see that file's own
docstring for why. Doesn't matter for a normal dev laptop, matters a lot on a
Jetson-class device, which is exactly why that decision lives in code, not just here.)

## 2. Quick check it all works

```bash
cd sqlite-rag-toolkit
python3 rag/ingest.py stats g1
```

Should print the real concept_type/source_type breakdown of `datasets/rag/g1.sqlite`
(818 chunks across 10 concept_types). If this works, your environment is set up right.

## 3. How search actually uses this metadata (read before writing anything)

This toolkit is deliberately scoped to ingestion only -- it doesn't bundle
`rag/retrieval.py` (the query-side hybrid search the live agent tools actually call),
since `rag/ingest.py`/`rag/build_index.py` never import it. The mechanics below still
matter a lot when deciding what metadata to put in a new doc, even though the code
that acts on it lives in the main `gramsahayak/` repo, not here -- Β§4 shows exactly
which tool uses which of these.

Two real, different mechanisms, not interchangeable -- see
`../gramsahayak/rag/retrieval.py`'s own docstring for the full detail:

- **`crop` / `concept_type`** -- real SQL `WHERE` filters, applied *before* the vector
  search runs. Get `concept_type` wrong and your doc is either invisible to a tool
  that filters on it (e.g. `get_treatment_details` only ever sees `type: Treatment`)
  or reachable somewhere you didn't intend.
- **`source_type`** -- never a filter, only a post-query ranking *boost* (a small
  multiplier applied to hits from a matching source when a tool asks for it, e.g.
  `plant_disease_lookup` boosts `source_type: diseases`). Getting this "wrong" just
  means your doc ranks a bit lower in a boosted search, it never disappears.

`LOW_CONFIDENCE_FLOOR` (0.40, in each tool file) is a **provisional, un-derived**
soft-flag threshold, not a real quality bar -- see
`../gramsahayak/rag/retrieval.py`'s own docstring and
`../gramsahayak/RAG-BUILD-LOG.md` Β§4/Β§8 for why. Don't read a low relevance score on
a real test query as "this doc doesn't work" without checking against that context
first.

## 4. Current RAG tools, and exactly what each one draws from

The live agent (`gramsahayak/agent/agent.py`) has 8 tools backed by this corpus (plus
`pesticide_lookup`, which is a real FSSAI dataset lookup, not RAG at all -- listed
here only for contrast). This table is the real, current wiring, pulled directly
from `agent/tools/{g1,g2}_rag_tools.py` and a real cross-tab query of
`datasets/rag/g1.sqlite`/`g2.sqlite` (2026-08-13, not estimated) -- when you add a
new document, this is what decides which tool(s) can actually surface it.

### G1 tools (`datasets/rag/g1.sqlite`, 818 chunks / 127 concepts)

| Tool | concept_type filter (hard) | source_type boost (soft) | Real chunk counts reachable |
|---|---|---|---|
| `plant_disease_lookup` | none -- searches everything | `diseases` (Γ—1.15) | ALL 818 chunks reachable; 283 boosted (Disease 194 + Pest 85 + Reference/diseases 4) |
| `plant_entomology_lookup` | none -- searches everything | `entomology` (Γ—1.2) | ALL 818 chunks reachable; 134 boosted (Insect) |
| `get_treatment_details` (was `pesticide_usage_and_dose`) | `Treatment` only | none -- equal weight (fixed 2026-08-12, see Β§6) | ONLY 171 chunks (pesticide_label 129 + treatments 42); everything else is invisible to this tool no matter how relevant |
| `get_guidelines_and_safety` (new, 2026-08-12) | `Practice Guidance` + `Safety Guidance` only | none | ONLY 60 chunks (govt_guideline 53 + safety 7); everything else is invisible to this tool |

**Real, current gap**: `Pathogen` (132 chunks, pathology), `Deficiency` (21 chunks),
`Coverage Boundary` (7 chunks), and `Reference` (14 chunks) have no tool that
filters *or* boosts toward them -- they're only reachable through
`plant_disease_lookup`/`plant_entomology_lookup`'s unfiltered search, competing on
raw relevance alone against everything else in the corpus. `Pathogen`/`Deficiency`
being unboosted is deliberate (a leaf-yellowing symptom can be a disease OR a
deficiency and both should compete fairly -- see `plant_disease_lookup`'s own
docstring). `Coverage Boundary`/`Reference` being unboosted is just because nothing
has needed them boosted yet, not a considered decision -- if you're adding a lot of
this kind of content, a new tool (like `get_guidelines_and_safety` was) is worth
considering rather than assuming raw relevance will surface it reliably.

### G2 tools (`datasets/rag/g2.sqlite`, 60 chunks / 17 concepts: 15 schemes + 2 shared reference docs)

| Tool | concept_type filter | source_type boost | What differs from the others |
|---|---|---|---|
| `get_scheme_details` | none | none | Query = `scheme_name: query` if a scheme was named, else raw query |
| `match_eligible_schemes` | none | none | Query built from a farmer profile (state/land size/crop/category), not their literal words |
| `get_disaster_relief_options` | none | none | Query text prefixed with disaster-relief vocabulary |
| `get_subsidy_details` | none | none | Query text prefixed with "subsidy:" |

All four search the *exact same* 60-chunk corpus with zero filtering -- nothing is
structurally excluded on the G2 side, they're four different ways of phrasing a
query into the same content. `match_eligible_schemes`/`get_disaster_relief_options`
are explicitly soft-RAG wrappers, not real table lookups (no structured
eligibility-rules or disaster-relief table exists in the corpus) -- see each tool's
own docstring in `agent/tools/g2_rag_tools.py` in the main repo.

### What this means for you, writing a new doc

- Adding a new **Disease/Pest/Insect** doc: reachable and properly boosted through
  the tool that already exists for it. Just get `type`/`source_type` right.
- Adding a new **Treatment** (product + dose): reachable through
  `get_treatment_details`, and (since the equal-weight fix) doesn't need to fight an
  artificial boost against other Treatment content -- just needs to be genuinely
  relevant to the query.
- Adding new **Practice Guidance / Safety Guidance**: reachable through
  `get_guidelines_and_safety` specifically -- this is the newest, least-populated
  slice (60 chunks total), a good place to contribute if you want your addition to
  matter more per-document.
- Adding a new **Pathogen/Deficiency/Coverage Boundary/Reference** doc: it'll be
  indexed and technically searchable, but nothing steers a query toward it --  if
  you're adding a meaningful volume of this kind of content, flag it, since a new
  dedicated tool (or a boost adjustment) might be the right move, the same way
  `get_guidelines_and_safety` was added when this exact gap was found for
  guidelines/safety content.
- G2: any new scheme/subsidy/relief doc is reachable through all four tools
  immediately, no filter/boost decisions to make.

## 5. Adding a new document

### 5.1 Pick the right corpus and directory

- **G1** (`datasets/rag/g1/`) -- anything about a specific plant/crop problem: disease
  symptoms, pest/insect biology, nutrient deficiencies, pathogen mechanisms, treatment
  products and doses, general application/safety guidance.
- **G2** (`datasets/rag/g2/`) -- government schemes, subsidies, disaster relief, and
  shared reference docs (e.g. "how to contact your local KVK").

Within G1, the directory a file lives in sets its default `source_type` (used for
search-ranking *boosts*, see Β§3/Β§4) -- match an existing directory unless you're
genuinely adding a new kind of content:

| Directory | source_type | Real content today |
|---|---|---|
| `diseases/` | diseases | Disease + Pest concepts (symptom-first descriptions) |
| `entomology/` | entomology | Insect concepts (life cycle, biology, natural enemies) |
| `pathology/` | pathology | Pathogen concepts (mechanism-level: how a genus of pathogen behaves across crops) |
| `deficiencies/` | deficiencies | Nutrient deficiency concepts |
| `treatments/` | treatments *or* pesticide_label (set explicitly, see Β§5.2) | Registered products + dose/PHI data |
| `guidelines/` | govt_guideline | General practice guidance (not disease/product-specific) |
| `safety/` | safety | Cross-cutting pesticide-safety content |
| `crops/` | crops / scope | Corpus scope/coverage meta-docs, not usually farmer-facing content |

### 5.2 Write the file -- real frontmatter schema

Every file is Markdown with YAML frontmatter (`---`-delimited), OKF-style. `type` is
the only field the parser strictly requires (`rag/okf.py` raises if it's missing);
everything else below is either used directly by the pipeline or just
provenance/searchability metadata. Read `rag/okf.py`'s `Concept` class if you want
the exact mapping from a frontmatter field to what gets stored per chunk.

**Required:**
```yaml
type: Disease   # or: Pest, Insect, Pathogen, Deficiency, Treatment,
                # Practice Guidance, Safety Guidance, Coverage Boundary, Reference
                # (G1); Scheme, Practice Guidance (G2). This is the real, hard SQL
                # filter some tools use (e.g. get_treatment_details only ever sees
                # type=Treatment) -- get this wrong and your doc becomes invisible
                # to the tool that should be finding it, or visible to the wrong one.
                # See Β§4 for exactly which tool sees which type.
```

**Strongly recommended (every real doc in the corpus has these):**
```yaml
title: Human-readable concept name
description: One-sentence summary -- gets prepended to every chunk's embedding text
tags: [list, of, searchable, keywords]
```

**Common, situational (see real examples below):**
```yaml
crop: potato                    # real SQL filter (soft: empty-crop docs still match
                                 # any crop query) -- set this if the content is
                                 # genuinely crop-specific
source_type: pesticide_label    # explicit override of the directory-based default --
                                 # see the Β§5.1 table; only set this if you actually
                                 # want a different boost behavior than the directory
                                 # default
label_id: CIBRC-SOME-KEY        # Treatment concepts only -- the real registration key
verified: { by: human:yourname, at: 2026-08-13T00:00:00Z }   # trust_tier: "verified"
                                 # entries starting "human:" -> trust_tier=human-reviewed,
                                 # anything else verified -> machine-confirmed,
                                 # nothing -> unverified (see rag/okf.py's trust_tier property)
```

**Body**: plain Markdown, chunked on `#`/`##` heading boundaries (`rag/chunking.py`).
A few heading names are handled specially -- use them exactly (case-insensitive):

- `# Visual Symptoms` -- marked `is_visual=True` (surfaces higher for a photo-derived query)
- `# Dose`, `# Farmer-facing instruction`, `# Safety`, `# Constraints` -- kept as one
  atomic chunk even if long (never mid-table/mid-instruction split)
- `# Distinguishing from similar conditions` (or headings starting "distinguishing
  from"/"telling it apart"/"not to be confused") -- **excluded from the index
  entirely**. Write contrastive-only content here if you want it in the doc for a
  human reader but never want it retrieved as if it described *this* concept.

**Real example** (`datasets/rag/g1/treatments/cymoxanil-mancozeb-potato.md` --
read the actual file for the full real thing, this is trimmed):

```yaml
---
type: Treatment
title: Cymoxanil 8% + Mancozeb 64% WP for potato late blight
description: Curative plus protectant combination fungicide registered on potato for late blight.
tags: [potato, late-blight, fungicide, curative]
source_type: pesticide_label
label_id: CIBRC-CYMO-MANC-POTATO
registered_crop: potato
dose_per_hectare: 1.5 kg
dose_per_acre: 600 g
phi_days: 10
---

# Dose
| Field | Value |
|---|---|
| Per hectare | **1.5 kg** |
...

# Farmer-facing instruction
> Mix 2 to 3 g in one litre of water...

# Safety
- Cover mouth, nose and hands...

# Constraints
- Registered for **potato** only. Use on any other crop is off-label.

# Applies to
- [Potato late blight](/diseases/potato-late-blight.md)
```

Also read `datasets/rag/g1/safety/spray-safety.md` (a Safety Guidance example) and
`datasets/rag/g2/guidelines/pm-kisan.md` (a G2 Scheme example) before writing your
first doc in either of those categories -- real examples teach the register/tone
faster than this doc can describe it.

### 5.3 Build/update the index

```bash
# First time ever, or a full clean rebuild of everything:
python3 rag/build_index.py

# Normal case -- you added new .md file(s), keep everything already indexed as-is:
python3 rag/ingest.py append g1      # or: append g2

# You EDITED an existing .md file (append won't pick this up -- it only looks
# for concept_ids it hasn't seen before):
python3 rag/ingest.py reingest g1 --concepts /treatments/cymoxanil-mancozeb-potato

# Sanity-check what's actually in the index now:
python3 rag/ingest.py stats g1
```

`append` only embeds the chunks from concepts it hasn't indexed before -- it doesn't
re-embed (or cost Ollama calls for) anything already there, so it stays fast as the
corpus grows. It rebuilds the BM25 sparse index every run regardless (cheap -- pure
tokenization, no embedding calls, real full-corpus BM25 rebuild takes well under a
second even at hundreds of chunks) since BM25 doesn't have a real partial-update
primitive the way the dense vector table does.

## 6. Deploying an updated corpus

The runtime tools (`gramsahayak/agent/tools/{g1,g2}_rag_tools.py`) only ever read two
files per corpus: `datasets/rag/{g1,g2}.sqlite` and `datasets/rag/{g1,g2}_bm25.pkl`.
Once you've built/updated them here, deployment is just copying those two files over
whatever's currently at that path -- on the main dev machine, and then (if serving
happens on a separate device) onto that device too. **Real recommended order:
pull the CURRENTLY-DEPLOYED files first (from wherever is actually serving, e.g.
Jetson), so you're appending onto the true live corpus rather than a possibly-stale
local copy, then push the updated result back:**

```bash
# 1. Pull the current live DB first (don't assume your local copy is still current):
scp user@device:/path/to/gramsahayak/datasets/rag/g1.sqlite \
    user@device:/path/to/gramsahayak/datasets/rag/g1_bm25.pkl \
    datasets/rag/

# 2. Add your new/edited .md file(s), then:
python3 rag/ingest.py append g1

# 3. Push the updated result back:
cp datasets/rag/g1.sqlite datasets/rag/g1_bm25.pkl \
   /path/to/gramsahayak/datasets/rag/          # same dev machine, if that's what serves

scp datasets/rag/g1.sqlite datasets/rag/g1_bm25.pkl \
    user@device:/path/to/gramsahayak/datasets/rag/   # separate serving device, e.g. Jetson
```

No code changes, no restart of anything beyond however the serving pipeline already
picks up a changed file (`agent/tools/g1_rag_tools.py`'s `HybridRetriever` opens the
DB connection once per process -- a running pipeline process needs a restart to pick
up a freshly-copied `.sqlite`/`.pkl` pair, same as any other file swap under a live
process).

## 7. Known real gotchas (already hit once, documented so you don't rediscover them)

From the original build -- see `../gramsahayak/RAG-BUILD-LOG.md` Β§2 for the full
story, summarized here:

1. sqlite-vec needs `apsw`, not stdlib `sqlite3` -- most Python builds have
   extension-loading compiled out entirely. `rag/store.py`'s `connect()` already
   handles this; you don't need to do anything, just don't swap it for raw `sqlite3`.
2. A sqlite-vec KNN query needs `crop`/`concept_type` as real metadata columns (no
   `+` prefix) to be filterable at all -- already correct in `rag/store.py`'s schema,
   just don't add a new filterable field as a `+`-prefixed auxiliary column and
   expect it to work in a `MATCH ... k = ?` query (a plain, non-KNN `DELETE`/`SELECT`
   on an auxiliary column, like `rag/ingest.py`'s reingest path uses, is fine).
3. Metadata columns reject `NULL` outright -- a doc with no `crop` gets stored as an
   empty string, not `None`, at the DB layer; `../gramsahayak/rag/retrieval.py`
   normalizes it back to `None` for every caller. You don't need to think about this
   when writing a `.md` file (just omit `crop` if it doesn't apply), only if you're
   touching `rag/store.py` itself.
4. `get_treatment_details`'s boost bug (2026-08-12, already fixed here): it used to
   favor the smaller, more generic `treatments` source_type slice over the larger,
   more relevant crop-specific `pesticide_label` slice -- backwards from what the
   tool is actually for. If you're tuning boosts for a new tool, sanity-check the
   direction against a real query before shipping it, the same mistake is easy to
   repeat.
