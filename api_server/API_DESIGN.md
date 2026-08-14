# Model Serving API — Design Plan

> Building this in `dev/agents/` for now, same as the rest of the pipeline prototyping —
> not the `suno-sutra-sw` deployment tree yet. Port to deployment once this is solid.

## Why this has to come before the orchestrator

The orchestrator's whole job is deciding *when* to load/unload each model to stay under
7 GB. That decision is worthless if calling "unload" doesn't actually give the memory back.
So before writing any orchestration logic, the API underneath it has to guarantee three
things per model: it can be loaded, it can be unloaded (with a **truthful** memory result),
and its live memory usage can be read at any moment. This doc is that API.

## Critical finding: in-process "unload" does not fully free RSS

The real measurements from `dev/local_model_test/*_memory_log.txt` (same numbers used in
`suno-sutra-sw/python/pocketinfer/memory_orchestrator/load_balancer_plan.md`):

| Module | Steady load | After `.unload()` + `gc.collect()` + `torch.cuda.empty_cache()` | Stuck |
|---|---|---|---|
| ASR  | 3037.8 MB | 1823.7 MB (baseline was 11.8 MB) | **~1812 MB never comes back** |
| NMT  | 1514.3 MB | 1173.2 MB (baseline was 11.7 MB) | **~1161 MB never comes back** |
| TTS (CPU RSS) | 1193.9 MB | 2322.2 MB *(RSS actually higher after use than at load!)* | **glibc heap never trimmed** |
| TTS (CUDA/VRAM) | 0.863 GB allocated | 0.034 GB reserved after unload | **fully reclaimed ✓** |

The pattern: **CUDA-side memory (TTS's VRAM) is released cleanly** — `torch.cuda.empty_cache()`
genuinely hands pages back. **CPU-side RSS (ASR, NMT, and TTS's own Python/torch heap) does
not** — this is standard glibc malloc behavior (freed heap arenas are kept mapped in the
process rather than `madvise`'d back to the kernel when live objects are still interleaved
with the freed ones). `test_tts_memory.py`'s own log calls this out directly: *"RSS not
dropping after unload is expected glibc/CPython heap retention."*

On a normal machine this is a non-issue — the OS has other RAM. **On Jetson Orin's unified
8 GB pool it is not a non-issue**: RSS that glibc won't give back is RAM that TTS or NMT
can't use next, permanently, for the rest of that process's life. If ASR, NMT, and TTS all
share one Python process, every load→unload cycle ratchets the floor up — the orchestrator's
internal ledger would say "freed 1.8 GB" while the OS says otherwise, and the budget math
silently goes wrong in a way no amount of clever state-variable logic can fix, because the
bug isn't in the logic, it's in the assumption that in-process unload == memory back.

**Conclusion: each model runs as its own OS process**, so "fully unloaded" can mean what it
needs to mean — kill the process, the kernel reclaims 100% of its RSS and VRAM unconditionally,
no glibc trust required. In-process `.unload()` still has a place (fast, cheap, good enough
when you're about to reload the *same* model seconds later) but it is not the operation that
guarantees the byte count the orchestrator's budget math depends on.

## Architecture: one gateway, one worker process per model

```
                    ┌─────────────────────────────┐
   pipeline apps,   │   Gateway (FastAPI, :11400)  │
   orchestrator,  ─→│   /asr/*  /nmt/*  /tts/*     │
   hardware/UI      │   /agent/*  /system/*        │
                    └───────────┬─────────────────┘
                                │ spawns + proxies to (httpx, localhost)
              ┌─────────────────┼──────────────────┐
              ▼                 ▼                  ▼
     ASR worker :11411   NMT worker :11412   TTS worker :11413      Ollama :11434
     (own process)       (own process)       (own process)          (already its own
     IndicConformerASR   NMTEngine           QuantizedParlerTTS      process — reuse
     (../models/asr/      (../models/nmt/     + StreamingTTS          its native
      model_loader.py)     model_loader.py)   (../models/tts_exports/ keep_alive/API,
                                               model_loader.py)        no new worker)
```

Workers import the engine classes directly from `dev/agents/models/*/model_loader.py` —
no copying yet, per the decision to keep everything in the dev/test tree until this is
proven out. Porting to `suno-sutra-sw` is a later, separate step.

Why a gateway instead of pipeline code calling 4 different ports directly: apps and the
orchestrator should have one address and one JSON shape to deal with; the gateway is also
the one place that knows how to spawn/kill/restart a worker, so "kill ASR's process" isn't a
capability scattered across every caller.

Why Agent/Ollama gets no new worker: Ollama **is** already a separate long-running server
process with its own load/unload primitive (`keep_alive`) and its own `/api/ps` status
endpoint — `suno-sutra-sw/python/pocketinfer/models/ollama.py` already talks to it this way.
Wrapping it in another subprocess would just add a hop. The gateway's `/agent/*` routes proxy
straight to Ollama's REST API.

## Worker process: generic contract (same shape for asr/nmt/tts)

Each worker is a tiny standalone FastAPI app wrapping exactly one engine object. State
machine per worker — four states, matching the three the user asked for plus the transition:

```
UNLOADED ──POST /load──→ LOADING ──(load() returns)──→ LOADED ──POST /unload──→ UNLOADED
                                                            │
                                                            └──POST /unload?full=true──→
                                                               (gateway kills + respawns
                                                                the OS process) ──→ UNLOADED
                                                                (guaranteed clean)
```

| Endpoint | Method | Behavior |
|---|---|---|
| `/health` | GET | Liveness only — process is up, doesn't mean model is loaded |
| `/status` | GET | `{state, loaded_at, rss_bytes, vram_bytes, load_time_sec, last_used_at}` |
| `/load` | POST | Synchronous — blocks until `state=="loaded"` or raises. Body: `{}` |
| `/load` | POST `?mode=async` | Returns `202` immediately with `state="loading"`; poll `/status` |
| `/unload` | POST | Soft unload: `engine.unload()` + `gc.collect()` + `torch.cuda.empty_cache()`. Fast (~1-2s). RSS may not fully drop (see above) — response reports the honest before/after byte counts, not an assumed zero |
| `/unload` | POST `?full=true` | Tells the **gateway** to kill this worker's process and respawn a fresh one. Guaranteed-clean but pays full interpreter+import startup cost (~2-4s depending on model) |
| `/infer` | POST | The actual ASR/NMT/TTS call. If `state != "loaded"`: `409` by default (caller must load first — this keeps "who decides to load" solely the orchestrator's job, not a side effect of an inference call racing it). An explicit `?auto_load=true` query flag exists for standalone testing/dev use, off by default in the pipeline |

Async load matters for exactly the case you described: kick off `POST /tts/load?mode=async`
the moment NMT→target starts translating, so TTS is already `state="loaded"` by the time
translation finishes and `/tts/infer` is called with zero load latency in the critical path.

## Gateway endpoints

| Endpoint | Purpose |
|---|---|
| `/asr/...`, `/nmt/...`, `/tts/...` | Proxy 1:1 to the matching worker's `/load`, `/unload`, `/status`, `/infer` |
| `/agent/status` | Proxies to Ollama `/api/ps`, reshaped to the same `{state, vram_bytes, ...}` shape as the other three, so the orchestrator polls one uniform shape for all four components |
| `/agent/load`, `/agent/unload` | Wraps Ollama's `keep_alive` mechanism (`keep_alive=-1`/large value to load+pin, `keep_alive=0` to unload immediately) |
| `GET /system/memory` | The one call the orchestrator's decision loop needs most: `{budget_max_bytes, total_rss_bytes, total_vram_bytes, available_bytes, utilization_pct, components: {asr: {...}, nmt: {...}, tts: {...}, agent: {...}}}` — sums each worker's own self-reported `rss_bytes`/`vram_bytes` from their `/status`, plus Ollama's `/api/ps` |
| `GET /system/status` | Same idea but the full per-component state machine snapshot, not just bytes — this is what the orchestrator's state variables are read from directly, no separate bookkeeping needed on the orchestrator side |
| `POST /system/workers/{name}/restart` | Explicit low-level "kill and respawn," same primitive `/unload?full=true` uses internally — exposed directly for ops/debugging |

`/system/memory` and `/system/status` are read from the workers' own live self-reports
(each worker's `/status` calls `psutil.Process().memory_info().rss` and
`torch.cuda.memory_allocated()` on itself, same functions as `dev/agents/memory_utils.py`)
rather than the gateway estimating from static config numbers — the config's `load_cost_*`
values are only used as *predictions* for pre-flight budget checks before a load happens,
never as a substitute for a real reading once something is actually loaded.

## Directory layout

```
dev/agents/api_server/
  API_DESIGN.md          (this file)
  config.py               port numbers, budget_max_bytes, per-module load_cost predictions,
                           ollama model list — same shape as load_balancer_plan.md's JSON block
  worker_base.py           Generic worker FastAPI app factory (state machine, load/unload/
                            status/infer routes) — asr/nmt/tts workers each just plug in
                            their engine class + a couple of config knobs
  workers/
    asr_worker.py           imports IndicConformerASR from ../../models/asr/model_loader
    nmt_worker.py            imports NMTEngine from ../../models/nmt/model_loader
    tts_worker.py            imports QuantizedParlerTTS/TTSInferencer from
                              ../../models/tts_exports
  gateway.py                FastAPI app: routes + worker process supervisor
  run_all.py                dev convenience script: launches gateway + all 3 workers,
                             Ctrl-C tears everything down cleanly
  test_api.py                Exercises the checklist below against the real checkpoints
                             already present in dev/agents/models/checkpoints/
```

This dev machine has no GPU exposed to it (checked: `nvidia-smi` reports no device) and
121 GB of RAM, so it won't reproduce the Jetson's tight-8GB failure modes — but it's exactly
right for validating the *plumbing*: state transitions, spawn/kill supervision, async load
timing relative to a simulated "translation window," and confirming `?full=true` unload
genuinely returns to baseline RSS. TTS's CUDA path will no-op/CPU-fallback here; that's fine
for this stage, real GPU numbers get recalibrated on-device per the checklist below.

## What "test the API" means before building the orchestrator

1. Start the gateway, confirm all three workers spawn in `UNLOADED` state, `/system/memory`
   reports near-zero.
2. Load each model one at a time via `/<name>/load`, confirm `/status` and `/system/memory`
   match the measured steady-state numbers in the table above (within noise).
3. Unload each one, confirm the soft-unload numbers match the "stuck RSS" table above exactly
   — i.e. confirm the API reports the *true* number, not a hopeful one.
4. `?full=true` unload each one, confirm `/system/memory` actually returns to near-baseline —
   this is the test that validates the whole subprocess-isolation decision.
5. Async-load timing: measure real load_time_sec for each model via the API (not the notebook)
   — these numbers calibrate the orchestrator's preload-window math (on the real Jetson later,
   they'll need re-measuring since ONNX/ctranslate2/torch behave differently there).
6. Concurrent load test: load NMT + start TTS async-load simultaneously, confirm no crash/race
   in the gateway's process supervisor.

Only after step 6 passes does it make sense to write the orchestrator's decision loop on top —
it will be a client of exactly this API (`GET /system/status` → decide → `POST .../load` or
`.../unload`), nothing more.
