# Architecture — How This Pipeline Actually Works

Companion to `README.md` (which covers *setup*). This doc covers *how it works*: the
memory orchestrator's rules, why there are two TTS engines and how they differ, and the real
measured timing/latency numbers this design is based on — everything a new contributor needs
before changing anything here. Every number below is a real measurement from an actual run
of this code (see the "Where these numbers came from" note at the end of each section) — none
of it is estimated.

---

## 1. The pipeline shape

```
farmer's voice (native language)
        │
        ▼
   ASR (indic-conformer-600m)  ──►  text, native language
        │  (skipped entirely for English input)
        ▼
   NMT (IndicTrans2)  ──►  text, English
        │
        ▼
   Agent (qwen3.5:2b via Ollama, tool-calling loop)  ──►  answer, English
        │
        ▼
   NMT (IndicTrans2)  ──►  answer, native language
        │  (skipped entirely for English output)
        ▼
   TTS (mms_tts or parler)  ──►  audio
        │
        ▼
   farmer hears the answer
```

Every stage is a separate process (`api_server/workers/{asr,nmt,tts}_worker.py`) except the
Agent, which is a request to a locally-running Ollama server — none of this pipeline's own
code hosts the LLM itself. `api_server/gateway.py` is the one process that's always running;
it spawns/kills the ASR/NMT/TTS worker subprocesses on demand (see §2) and proxies
`/<component>/...` HTTP calls to whichever one is currently up.

**Why separate processes at all, not one Python process holding everything**: the whole
point is a hard 8GB memory ceiling (Jetson Orin Nano target, `config.MODEL_BUDGET_BYTES` =
7.0GB after OS/UI overhead). A model loaded in-process can leak GPU/host memory that
`torch.cuda.empty_cache()`/`gc.collect()` genuinely cannot reclaim (CUDA driver context,
cuDNN/cuBLAS workspace — see any `model_loader.py`'s `unload()` docstring for the specifics).
Killing the whole subprocess is the only *guaranteed* full reclaim — see
`api_server/API_DESIGN.md` for the full reasoning.

---

## 2. The Memory Orchestrator (`api_server/orchestrator.py`)

`MemoryOrchestrator` is the thing deciding, at every pipeline boundary, what should be
loaded and what should be evicted — never the workers themselves, and never a fixed
schedule. It reads live `/status` from every component before every decision (never trusts
a cached number), and its full rule set is:

### The rules

| Rule | What it does | Why |
|---|---|---|
| **1 — Complementary exclusion** | ASR and TTS are never allowed loaded at the same time. Loading one force-evicts the other first. | They're never needed simultaneously in this pipeline's flow, and evicting proactively avoids ever having to *react* to an overshoot. |
| **2 — Evict NMT before TTS peak** | Once NMT's output is cached (translation done, text captured), NMT is unloaded before the TTS stage starts. | NMT's ~1.6GB is real, avoidable weight sitting idle exactly when TTS needs headroom most. |
| **3 — TTS batch size is not a memory-safety lever** *(historical, Parler-only)* | Parler's `batch_size` is tuned for latency/throughput only. | Real measurement found batch size barely moved Parler's peak memory (chunk *content* length dominates, not batch grouping) — see §3. |
| **4 — Agent is sticky within a turn** | The Agent is never evicted mid-generation. | Obviously — you can't evict a model mid-answer. |
| **5 — Golden-window TTS preload** | The instant the Agent's turn starts, TTS is fired to load *asynchronously*, in the background, overlapping the Agent's own ~15-45s generation time. | By the time TTS is actually needed, it's very often already fully loaded — confirmed real in every logged run so far ("TTS already fully loaded, zero wait"). |
| **6 — Boundary-ordered checks** | Every load goes through: complementary check → eviction for budget → load. Never skipped, never reordered. | Consistency — no path where a load happens before the budget was actually checked. |
| **7 — Embedder is on-demand only** | The embedder (`nomic-embed-text`) only loads for a tool call that actually needs vector search. Never baseline-resident. | Not exercised by today's mock tools, but ready for when real retrieval tools replace them — no reason to pay ~0.32GB for a capability not in use this turn. |
| **8 — Evict Agent before TTS's peak** | **Engine-dependent, see below.** | The single most important rule in this design — see its own subsection. |
| **9 — Golden-window Agent preload** | The Agent's load is fired asynchronously the moment ASR starts (or immediately, for English input with no ASR stage) — overlapping its ~5-7.5s load time with ASR/NMT's own work. | Same idea as Rule 5, one stage earlier. |
| **10 — Workers are spawned lazily, never a standing pool** | ASR/NMT/TTS worker *processes* only exist between their own `/load` and `/unload` — "unloaded" means the process is gone, zero cost, not just idle. | A standing pool was tried first and found to cost ~2.06GB combined, just from being alive (Python + FastAPI/uvicorn + heavy imports) — even with every model itself "unloaded." That silently pushed a supposedly-safe combination over budget in a real run. Trade-off: every *first* load after an eviction now pays real process-spawn + import time (confirmed: TTS's cold load grew from ~3.2s to ~7.45s wall-clock once this was fixed — see §3's component table). |

### Rule 8, in detail — the one rule that changed shape with the TTS engine

This is the rule most worth understanding before touching anything, because it's the one
place the two TTS engines genuinely behave differently, not just faster/slower.

**For `parler`** (unconditional, no exceptions): Agent is evicted *every single time*,
right before TTS synthesis starts, regardless of any projected-budget calculation. This was
originally conditional too — a projected-budget check was tried first, computed whether
eviction was actually necessary before doing it. It was abandoned after two live
full-pipeline runs on the same real Hindi answer measured a peak pool of **7.79GB (batch=6)**
and **7.54GB (batch=3)** — both over the 7.0GB budget — because Parler's real peak is
content-dependent (driven by *how much* text a given answer chunks into, not by batch size)
in a way that isn't reliably predictable ahead of time. Unconditional eviction frees a fixed,
known 2.65GB no matter what the answer contains — the one eviction in this whole design that
doesn't depend on getting a prediction right.

**For `mms_tts`** (conditional): Agent is evicted *only if* the actual projected total (with
Agent still resident) would exceed the 7.0GB budget. If there's room, Agent stays loaded
straight through TTS synthesis and into the next turn — no reload, no ~5-7.5s tax paid for no
reason. This is safe specifically *because* MMS-TTS's real peak is an order of magnitude
smaller and far less content-dependent than Parler's (no autoregressive KV-cache growth to
blow past an estimate — see §3 for the real numbers). Confirmed via a live pipeline run:
projected 6.35GB with Agent resident (under budget) → Agent kept loaded → real observed peak
5.53GB, still comfortably under budget.

```python
# orchestrator.py's _prepare_budget_for_tts_peak(), the actual logic:
if tts_engine != "mms_tts":
    evict_agent_unconditionally()               # Parler: always
else:
    if projected_total_with_agent_resident > BUDGET:
        evict_agent()                             # mms_tts: only if actually needed
    # else: leave it loaded
```

**Practical implication for anyone extending this**: if you add a third TTS engine, decide
explicitly which side of this branch it belongs on based on real measurement, not
assumption — an autoregressive/unbounded-peak engine belongs with Parler's unconditional
behavior; a bounded, small-peak engine can use the conditional path. Guessing wrong in the
"conditional" direction for an engine that's actually unpredictable is exactly the failure
mode Rule 8 exists to prevent.

### The state variables it tracks

Nothing is assumed — every decision reads real numbers:

- **Per-component**: `state` (loaded/unloaded/loading), `rss_bytes`, `vram_bytes` — read live
  from each worker's own `/status`, or from Ollama's `/api/ps` for Agent/Embedder.
- **Pool-level**: `total_bytes` = sum of every component's `rss_bytes + vram_bytes`,
  `available_bytes` = `7.0GB - total_bytes`, `utilization_pct`.
- **Turn-scoped flags**: `nmt_output_cached` (is NMT's output safe to evict — Rule 2),
  `tool_needs_embedder` (is the Embedder actively needed this turn — Rule 7).

*Where these numbers came from*: `suno-sutra-sw/python/pocketinfer/memory_orchestrator/
load_balancer_plan.md` (the original design doc, with a full update-log of every real
measurement that changed a rule) and `orchestrator.py`'s own docstrings — both worth reading
directly for more depth than this summary carries.

---

## 3. Two TTS engines, and why they're genuinely different

`api_server/config.TTS_ENGINE` picks between them — `"mms_tts"` (default) or `"parler"`.
This isn't a simple swap: they're architecturally different model families, which is the
entire reason their memory/timing numbers (and Rule 8's behavior above) differ as much as
they do.

### The architectural difference

| | **mms_tts** (default) | **parler** |
|---|---|---|
| Model | Meta MMS-TTS, VITS architecture | Indic Parler-TTS, AWQ+int4 quantized |
| Generation | **Non-autoregressive** — one forward pass produces the complete waveform | **Autoregressive** — a codec-token decoder, generates token-by-token like an LLM |
| Consequence | No KV-cache growth with output length, no generation-length cap, no chunking/batching needed at all | Needs a `max_new_tokens` cap (~35s of audio per call); long text must be split into chunks (`chunk_text()`) and chunks generated in `batch_size`-sized batches for throughput (`streaming.py`) |
| Checkpoints | **One checkpoint per language** (`facebook/mms-tts-<iso>`) — 15 languages bundled (see `setup/download_models.py`) | **One shared model**, any language via a voice-description prompt |
| License | **CC-BY-NC 4.0 — non-commercial only.** Confirmed directly against every repo's model card, not assumed from a headline framing. Re-check before any commercial deployment. | (not re-verified as part of this evaluation — check separately before relying on it) |

### The hybrid fallback (why Parler is still needed even when `TTS_ENGINE="mms_tts"`)

MMS-TTS does not have a checkpoint for every one of India's 22 constitutionally-recognized
languages — confirmed directly against Meta's own published language-coverage table (not the
"1107 languages supported" headline, which counts *every* language MMS covers across all
speech tasks, not specifically well-trained TTS). Of the 22, **14 have real MMS-TTS
checkpoints; 8 do not**: Bodo, Kashmiri, Konkani, Manipuri, Nepali, Sanskrit, Santali, Sindhi
(`config.MMS_TTS_UNSUPPORTED_INDIAN_LANGUAGES`).

`api_server/workers/tts_worker.py`'s `_HybridMmsParlerEngine` handles this transparently:
a request for any of those 8 languages is routed to a **lazily-loaded** Parler-TTS instance
instead — Parler only actually loads (paying its own ~2.65-2.9GB) the first time one of those
languages is genuinely requested, not on every startup. This is also why
`setup/download_models.py` downloads the Parler checkpoint unconditionally, regardless of
which engine is configured as the default.

### Real measured performance — the numbers Rule 8 and the default engine choice are based on

**Component load/unload** (dev machine, NVIDIA GB10 — not yet re-measured on a real Jetson;
re-run `api_server/test_timing.py` on your actual target device before trusting these for
latency budgeting).

**Read the RSS/VRAM columns here as *idle, just-loaded* footprint, not peak-during-work** —
easy to misread as the ceiling, and it isn't one. This table comes from a plain `/load` call
with no inference run afterward. TTS in particular climbs a lot further once it's actually
*synthesizing* something — Parler's real observed peak during synthesis is **4.46-5.2GB**
(not the 0.863GB idle VRAM figure below), and this is exactly why Rule 8 exists at all (§2)
— see the full-pipeline table further down for TTS's real *working* footprint, not just its
idle one:

| Component | Load, wall-clock (s) | Unload (s) | Peak RSS (idle, just loaded) | Peak VRAM (idle, just loaded) |
|---|---|---|---|---|
| ASR | 6.641 | 0.953 | 3.204GB | 0.0GB |
| NMT | 3.296 | 0.58 | 1.612GB | 0.0GB |
| TTS (parler) | 7.45 | 0.534 | 1.269GB | 0.863GB — climbs to **4.46-5.2GB during real synthesis**, see below |
| Agent (qwen3.5:2b, Ollama) | 5.436 | 0.72 | — | 2.647GB |
| Embedder (nomic-embed-text) | 2.456 | 0.262 | — | 0.323GB |

**Full pipeline, both engines** — same real ASR→NMT→Agent→NMT→TTS run, all 4 core
languages, `--no-play` (compute time, not audio-playback duration):

| Language | Parler total turn (s) | mms_tts total turn (s) | Speedup |
|---|---|---|---|
| English | 145.28 | 30.93 | 4.70x |
| Hindi | 107.75 | 69.04 | 1.56x |
| Malayalam | 141.08 | 49.62 | 2.84x |
| Tamil | 125.48 | 65.17 | 1.93x |
| **Total (4 languages)** | **519.59** | **214.76** | **2.42x** |

Per-step breakdown for the same runs (ASR/NMT/Agent timings are within normal run-to-run
noise between the two — identical code paths either way; **the entire gap is the TTS
stage**):

| Engine | Lang | ASR infer | NMT-in infer | Agent turn | NMT-out infer | **TTS infer** | Total turn |
|---|---|---|---|---|---|---|---|
| parler | hi | 4.86 | 0.81 | 6.39 | 4.94 | **60.14** | 107.75 |
| parler | ml | 4.77 | 0.49 | 16.18 | 5.76 | **94.59** | 141.08 |
| parler | ta | 4.07 | 0.50 | 13.67 | 8.34 | **78.49** | 125.48 |
| mms_tts | hi | 4.94 | 0.82 | 25.61 | 7.28 | **2.28** | 69.04 |
| mms_tts | ml | 4.45 | 0.65 | 15.55 | 6.22 | **2.33** | 49.62 |
| mms_tts | ta | 4.13 | 0.66 | 25.44 | 7.55 | **2.80** | 65.17 |

**What "TTS infer" actually measures here**: the full `/tts/infer` HTTP call, start to
finish — this run used `--no-play`, so there is zero audio-playback time mixed into any
column above, every number is pure server-side compute. For Parler this means *every batch
of chunks finishes generating* before the call returns even one byte to the caller — Parler
never streams partial results back through this endpoint, it just generates internally in
`batch_size`-sized batches for its own throughput, then hands back one complete response.
That's the whole reason Parler's number here (60-94s) is so much larger than mms_tts's
(2.3-2.8s): it's genuinely still-generating compute time, not first-chunk latency — see
below for the actual first-audio-latency numbers, and read the note under that table
carefully, because it answers an easy-to-assume-wrong question: *does this endpoint's caller
ever get to benefit from the faster first-chunk number?*

**TTS specifically — time-to-first-audio vs. total generation time.** This table measures
something different from the "TTS infer" column above: not the HTTP round-trip, but how
quickly *internal* audio chunks become available, by calling each engine's own streaming
generator (`StreamingTTS.synthesize_stream_chunks()` for parler) **directly, in-process,
bypassing the gateway entirely** — because `/tts/infer` has no concept of partial results to
measure in the first place (see the note right after this table for why that matters). Same
real long multi-paragraph agent answers as above (691-1307 chars), *not* short filler text
(short text never exceeds Parler's 180-char chunk threshold, so its batching never actually
engages — see `TTS_ENGINE_TIMING_RESULTS.md` for the methodology note on why this matters):

| Engine | Language | Time to first audio (s) | Total TTS time (s) | Audio duration (s) |
|---|---|---|---|---|
| parler | English | 28.37 | 104.02 | 78.41 |
| parler | Hindi | 26.93 | 61.78 | 57.26 |
| parler | Malayalam | 23.61 | 58.02 | 61.55 |
| parler | Tamil | 43.03 | 98.53 | 83.59 |
| mms_tts | English | 1.43 | 1.43 | 75.31 |
| mms_tts | Hindi | 0.74 | 0.74 | 54.85 |
| mms_tts | Malayalam | 0.93 | 0.93 | 57.47 |
| mms_tts | Tamil | 1.09 | 1.09 | 87.41 |

Neither column here includes playback time — both are pure generation/compute wall-clock,
same as the per-step table above.

**Why Parler has two different numbers and mms_tts doesn't, mechanically**: Parler generates
`chunk_text()`'s output `batch_size` chunks at a time (3, by default — `config.py`'s
`default_batch_size`). "Time to first audio" is how long the *first* batch takes to finish;
"Total TTS time" is how long *every* batch takes, back to back. While one batch is being
generated, none of the others are — there's no actual parallel generation happening, batching
here means "grouped into one `generate()` call for throughput," not "concurrent." mms_tts has
no batches at all: VITS's single forward pass produces the complete answer as one indivisible
unit, so time-to-first-audio *always* equals total time — a real architectural fact, not a
measurement gap.

**The number that actually matters depends on which code path you're using — two real
paths exist, on purpose, not one replacing the other:**

- **`/tts/infer`** (the original, still-default path — what `test_orchestrated_pipeline.py`
  calls unless you pass `--stream-tts`) collects **every** chunk/batch into one response
  before returning *anything*: `worker_base.py`'s `/infer` route does a plain
  `return infer_fn(...)` (no `yield`, no `StreamingResponse`), and `_infer_parler` appends
  each batch to a list inside a blocking loop, building the response only after it ends. A
  caller here waits the full "Total TTS time" (58-104s for Parler in the table above) before
  hearing anything. Kept exactly as it was, unconditionally — the simpler, more proven
  fallback if the streaming path below ever causes a real-world problem (context loss across
  batches, network reliability on an actual device, etc.) that hasn't shown up in this
  project's own dev-machine testing.
- **`/tts/infer_stream`** (new, opt-in via `--stream-tts`) actually delivers the faster
  time-to-first-audio number to a real caller, through the real gateway, over real HTTP.
  `tts_worker.py`'s `_stream_parler`/`_stream_mms_tts` yield one chunk/batch at a time via a
  `StreamingResponse`; `gateway.py` had to gain a **real** streaming passthrough for this
  route specifically (`httpx.AsyncClient.stream()` + `aiter_bytes()`) — the generic proxy's
  buffered `resp.content` pattern used for every other route would have silently swallowed
  the streaming benefit at the gateway hop even with the worker streaming correctly. On the
  client side, `models/tts_exports/streaming.py`'s `play_http_stream()` consumes that stream
  and feeds it into the *same* smart-prebuffer algorithm `StreamingTTS.play_stream()` already
  used locally (refactored into one shared `_smart_prebuffer_playback()` core so both paths
  run identical logic). **Getting this genuinely stall-free took finding and fixing two real
  bugs, not just wiring the plumbing together** — see `TTS_HTTP_STREAMING_RESULTS.md` for
  the full root-cause writeup (a buffering-math timing bug, and a real one: the playback
  thread blocking on `sink.play()` also stopped reading the network, starving the socket via
  TCP backpressure until playback caught up). Real verified numbers, real gateway, real
  audio actually played: Parler time-to-first-audio **52.12s** (vs. 58-104s total-wait via
  `/tts/infer`), zero stalls; mms_tts **10.82s** (already close to best-case — one chunk,
  nothing to buffer for).
- **mms_tts benefits least from streaming, structurally**: with no "first chunk" concept at
  all (VITS's single forward pass, one chunk, always), `/tts/infer`'s own round-trip
  (2.3-2.8s in the per-step table) is already close to the streaming path's own
  time-to-first-audio (10.82s in the real streaming test — mostly real generation+transfer
  time, not buffering). Streaming's real win here is specifically for Parler.

*Where these numbers came from*: `TTS_ENGINE_TIMING_RESULTS.md` (this folder) for the
TTFA/total table and engine load times (in-process, no gateway); `TTS_HTTP_STREAMING_RESULTS.md`
(this folder) for the real `/tts/infer_stream` numbers, the two real bugs found getting it
stall-free, and the full root-cause writeup; `MMS_TTS_EVALUATION.md` (this folder) for the
full license/architecture/quality evaluation that led to `mms_tts` becoming the default,
including a real human-listenable audio quality check per language; `api_server/
TIMING_RESULTS.md` for the component load/unload table. The full-pipeline and per-step
tables came from two real `test_orchestrated_pipeline.py --all --no-play` runs (one per
engine) on this dev machine — re-run that same command yourself any time to reproduce or
update these numbers, including on your actual target device.

---

## 4. Package tour — where to look to change something

| I want to... | Look at |
|---|---|
| Change which TTS engine is default | `api_server/config.py`, `TTS_ENGINE = "mms_tts"` |
| Add a new MMS-TTS language | `models/mms_tts/model_loader.py`'s `LANGUAGE_TO_REPO`, then `setup/download_models.py`'s `MMS_TTS_LANGUAGES`, then `api_server/config.py`'s `MMS_TTS_LANGUAGE_NAME_TO_CODE` if the pipeline will send it a full display name |
| Change the memory budget (e.g. a device with more/less than 8GB) | `api_server/config.py`, `MODEL_BUDGET_BYTES` |
| Change the Agent's text-generation model | `api_server/config.py`'s `OLLAMA_MODELS[0]` (global default), or pass `GramSahayakAgent(model="...")` per-instance. **Always pass `num_ctx` explicitly on every Ollama load call** — omitting it falls back to the model's own huge default context and can blow the entire budget on its own (confirmed real: `qwen3.5:2b` at its own default context allocates 6.8GB idle vs. 2.647GB at this pipeline's configured `num_ctx` — a 2.6x difference for identical weights, zero tokens generated). See the vision-model note right below this table before changing this — the two are coupled by default, on purpose. |
| Add a real tool (replacing a mock) | `agent/agent.py` — five MOCK domain tools (entomologist/botanist/weather/disease/govt-scheme) are stand-ins for real vector-search lookups; `agent/tools/` has the two already-real tools (`pesticide_lookup.py`, `photo_analysis.py`) as a pattern to follow. A real retrieval tool is also what would finally exercise Rule 7's on-demand Embedder loading. |
| Understand/change an orchestrator rule | `api_server/orchestrator.py` — `_prepare_budget_for_tts_peak()` (Rules 2/7/8), `_make_room_for()` (Rule 6's generic budget check), `_find_eviction_candidate()` (Rule 6's eviction scoring) |
| Add a new pipeline stage | `api_server/worker_base.py`'s `make_worker_app()` is the generic worker state machine every component (ASR/NMT/TTS) is built on — a new stage just needs `engine_factory`/`infer_fn`, same shape as `api_server/workers/tts_worker.py` |
| Re-measure timing on real hardware | `api_server/test_timing.py` (component load/unload), `test_orchestrated_pipeline.py --all --no-play` (full pipeline + per-step), `TTS_ENGINE_TIMING_RESULTS.md`'s generating script isn't included here — see `MMS_TTS_EVALUATION.md`'s methodology to rebuild it if needed |
| Understand the HTTP surface (`/asr/load`, `/tts/infer`, etc.) | `api_server/API_DESIGN.md` |
| Use real incremental TTS playback instead of blocking `/tts/infer` | `--stream-tts` flag on `test_orchestrated_pipeline.py`, or call `/tts/infer_stream` directly / `models/tts_exports/streaming.py`'s `play_http_stream()` from your own code. See `TTS_HTTP_STREAMING_RESULTS.md` for real measured numbers and the two real bugs it took to make this stall-free. Opt-in, not the default -- `/tts/infer` is unchanged and still there as the simpler fallback. |

### The Agent's text model and vision model default to being the same model — on purpose

`GramSahayakAgent.__init__(self, model=None, vision_model=None, ...)`
(`agent/agent.py`): `model` defaults to `config.OLLAMA_MODELS[0]` (`qwen3.5:2b`) if not
passed, and — this is the part worth knowing before splitting them —
**`vision_model` defaults to whatever `model` ends up being**, not to a separate model of its
own. So changing the text model (either via `config.OLLAMA_MODELS[0]` globally, or
`GramSahayakAgent(model="...")` per-instance) automatically keeps the vision model in sync
too, unless you explicitly pass `vision_model=` to override it.

This is a memory decision, not a simplicity shortcut. `agent/tools/photo_analysis.py`'s own
default vision model (`"gemma4:e2b"`) is a real, separate 7.2GB Ollama model — if the agent
ever actually used that default instead of sharing its own model, that would be a **second**
Ollama-resident model the memory orchestrator's budget math has never accounted for anywhere
(`config.OLLAMA_MODELS` only lists the agent + embedder), and 7.2GB alone is already over the
entire 7.0GB budget on its own. `qwen3.5:2b` was confirmed directly (`ollama show
qwen3.5:2b`) to genuinely support vision, tools, and thinking in one model — so sharing it for
both text and vision avoids that risk entirely, no model swap and no second resident model
needed for a photo-analysis tool call.

**If you do want a different vision model deliberately** (e.g. a text model that doesn't
support vision), pass `vision_model=` explicitly and add its real measured footprint to the
orchestrator's budget accounting yourself — right now nothing in `config.py` or
`orchestrator.py` knows a second Ollama model might load during a tool call, so a real
memory-budget gap opens up silently the moment `vision_model` differs from `model`.

Every number in this document needs re-measuring on the actual Jetson Orin Nano before being
trusted for a real deployment decision — everything above came from a dev machine with a much
larger unified-memory pool and no 8GB ceiling. The *rule structure and engine comparison*
are validated against real, live pipeline runs, not simulated — but every millisecond and
gigabyte figure is device-specific and due for a real re-measurement pass on-device.
