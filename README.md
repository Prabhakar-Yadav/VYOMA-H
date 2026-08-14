# GramSahayak — Voice-first Agricultural Assistant

Self-contained deployable pipeline: real-time ASR → NMT → tool-calling Agent → NMT → TTS,
with a memory orchestrator that keeps everything inside an 8GB unified-memory budget (Jetson
Orin Nano target). Extracted from this repo's `dev/agents/` working area into a package
meant to be shared/cloned/copied on its own — nothing here reaches outside this folder.

**New to this codebase? Read `ARCHITECTURE.md` next** — it explains the memory
orchestrator's rules, how the two TTS engines differ and why both exist, and every real
timing/latency number this design's decisions are based on. This README only covers *setup*.

## What's in here

```
gramsahayak/
├── ARCHITECTURE.md      Orchestrator rules, TTS engine comparison, real timing numbers --
│                         READ THIS before changing anything
├── api_server/        FastAPI gateway + memory orchestrator + ASR/NMT/TTS worker processes
├── agent/              GramSahayakAgent (tool-calling loop over Ollama) + its tools
├── models/              Engine wrapper code (asr/, nmt/, mms_tts/, tts_exports/) --
│                         models/checkpoints/ starts EMPTY, populated by setup/ below
├── setup/                download_models.py -- run this first on a fresh machine
├── sample_audio/          Real test fixtures (pipeline_inputs/) for validation
├── datasets/               Real data the agent's tools need (pesticide lookup data, a
│                            sample crop photo for the vision tool)
├── test_orchestrated_pipeline.py   End-to-end validation script (--stream-tts for real
│                                    incremental TTS playback -- see below)
├── test_streaming_tts_http.py       Isolated real /tts/infer_stream test, both engines
├── MMS_TTS_EVALUATION.md            Full MMS-TTS vs Parler-TTS evaluation (license,
│                                     architecture, per-language audio quality, real numbers)
├── TTS_ENGINE_TIMING_RESULTS.md      Raw in-process TTS timing data behind ARCHITECTURE.md
├── TTS_HTTP_STREAMING_RESULTS.md      Real /tts/infer_stream numbers + two real bugs found
│                                       getting it stall-free
└── requirements.txt
```

## Setup (fresh machine, e.g. a new Jetson)

**1. Python environment.** This was built and tested against Python 3.10.

```bash
python3.10 -m venv venv
source venv/bin/activate
```

**2. torch + torchao first, separately — before requirements.txt.** Every engine here needs
torch, and there is no one correct version across platforms. A Jetson needs NVIDIA's own
JetPack/L4T-matched torch wheel, not a generic `pip install torch` — follow NVIDIA's Jetson
PyTorch install instructions for your JetPack version, then install a matching `torchao`
build (functional minimums: `torch>=2.10`, `torchao>=0.17.0` — see
[pytorch/ao#installation](https://github.com/pytorch/ao#installation) for platform-specific
build instructions; torchao is only needed for the Parler-TTS fallback engine's int4
quantization, but install it regardless so that fallback path works).

**3. Everything else:**

```bash
pip install -r requirements.txt
```

**4. Hugging Face token** (needed for the gated ASR checkpoint only — everything else is a
public repo):

```bash
export HF_TOKEN=hf_...   # get one at https://huggingface.co/settings/tokens
```

Then visit https://huggingface.co/ai4bharat/indic-conformer-600m-multilingual once while
logged in and accept its access terms (a click-through, not a paid/restricted license) — the
download will fail with a clear 401 error if you skip this step.

**5. Download the checkpoints:**

```bash
python setup/download_models.py
```

This downloads MMS-TTS (15 languages), Parler-TTS (fallback engine), and ASR into
`models/checkpoints/`. It prints clear instructions for the one checkpoint it can't
auto-fetch (NMT — see below) and is safe to re-run (skips anything already present).

**6. NMT checkpoint — manual step.** No verified clean download source exists for the exact
IndicTrans2 ct2-int8 checkpoint this pipeline uses (see
`models/nmt/model_loader.py`'s module docstring for the full story — it was originally
vendored from a locally-extracted toolkit bundle, not a standard Hugging Face repo). Copy it
in from a teammate or your team's internal source so you end up with:

```
models/checkpoints/indic-trans2-nmt/
  en-indic/ct2_int8_model/     {config.json, model.bin, source_vocabulary.txt, target_vocabulary.txt, vocab/}
  indic-en/ct2_int8_model/     (same file set)
  indic-indic/ct2_int8_model/  (same file set)
```

Skip this if you only need English — NMT is only invoked for non-English input/output.

**7. Ollama, for the Agent.** This pipeline's agent runs against a local Ollama server, not
a bundled model:

```bash
ollama pull qwen3.5:0.8b        # the agent model, config.OLLAMA_MODELS[0]
ollama pull nomic-embed-text    # the embedder, config.OLLAMA_MODELS[1] (only loaded
                                 # on-demand for tool calls needing vector search)
```

## Validate the install

```bash
python test_orchestrated_pipeline.py --language hi --no-play
python test_orchestrated_pipeline.py --all             # every language, one session
python test_orchestrated_pipeline.py --language en --with-image   # vision tool path
python test_orchestrated_pipeline.py --language hi --stream-tts   # real incremental TTS
                                                                    # playback -- see below
```

This runs the real pipeline end to end (spawns its own gateway + workers), printing every
memory-orchestrator decision live (`[ORCH]` lines) and writing real audio to
`sample_audio/pipeline_outputs/`. If this completes cleanly for `hi`, `ml`, and `ta` (the
three languages with real ASR input audio bundled here), the install is good.

**`--stream-tts`** uses the newer `/tts/infer_stream` path (real incremental playback —
audio starts before the whole answer has finished generating) instead of the default,
simpler `/tts/infer` (blocking — waits for everything). Both are real, both stay available —
`/tts/infer` is unchanged and is the fallback if streaming ever misbehaves in practice. See
`TTS_HTTP_STREAMING_RESULTS.md` for real measured numbers and two real bugs it took to get
this genuinely stall-free (not just "it usually works").

## Running the actual service

```bash
python api_server/run_all.py
```

Starts the gateway on `:11400`. ASR/NMT/TTS workers are spawned lazily on first `/load` —
see `api_server/API_DESIGN.md` for the full HTTP surface, and
`api_server/config.py` for every tunable (which TTS engine, Ollama context size, memory
budget, etc.).

## TTS engine — mms_tts (default) vs parler

`api_server/config.py`'s `TTS_ENGINE` picks between two architecturally different engines —
Meta's MMS-TTS (default) and the original Parler-TTS, kept as a selectable alternative and
as the automatic fallback for 8 India languages MMS-TTS has no checkpoint for. **See
`ARCHITECTURE.md` §3** for the full explanation (why they're different, not just faster/
slower), the license note (MMS-TTS is CC-BY-NC 4.0 — non-commercial only), and every real
measured timing number this default was chosen on. `MMS_TTS_EVALUATION.md` and
`TTS_ENGINE_TIMING_RESULTS.md` in this same folder are the underlying source data.

## Memory budget

Tuned for an 8GB unified-memory device (Jetson Orin Nano), `config.MODEL_BUDGET_BYTES` =
7.0GB (1GB reserved for OS/UI). Every load/unload/eviction decision is made by
`api_server/orchestrator.py`'s `MemoryOrchestrator` — see its module docstring for the full
rule set (complementary ASR/TTS exclusion, proactive eviction before TTS's peak, golden-window
preloading, etc.). All of this was designed and measured on a non-Jetson dev machine (much
larger unified memory, no 8GB ceiling) — re-run `api_server/test_timing.py` and
`test_orchestrated_pipeline.py` on your actual target device before trusting the timing
numbers baked into `config.py`'s comments; the *rule structure* is validated against real
pipeline runs, but every millisecond number needs re-measuring per device.
