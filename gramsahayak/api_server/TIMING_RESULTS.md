# Component Load/Unload Timing Results

Generated: 2026-08-05T05:28:26+00:00
Repeats per component: 3

Measured on this dev machine (NVIDIA GB10, ~130GB unified CPU/GPU memory, no Jetson-style 8GB ceiling) -- real numbers from the real checkpoints and the real Ollama server, but **not** Jetson Orin numbers. Re-run this same script on-device before trusting these for the orchestrator's preload-window math (`load_balancer_plan.md`'s "golden window" rules).

## ⚠️ Context window controls VRAM more than model size does

`qwen3.5:2b` at its own Ollama default context (`num_ctx=262144`) allocates **6.8GB** of VRAM at idle, zero tokens generated -- purely pre-allocated KV cache. At this pipeline's configured context (`num_ctx=16384`, `config.OLLAMA_NUM_CTX`), the same model loads at **2.647GB** -- a **2.6x** difference for identical weights.

This means every Ollama load call in the orchestrator/API **must** pass `options: {"num_ctx": ...}` explicitly -- never rely on Ollama's per-model default. Omitting it on a real device is enough on its own to blow the entire 8GB budget before ASR, NMT, or TTS even get a chance to load.

## ASR / NMT / TTS (gateway-managed worker processes -- lazy spawn)

Workers are no longer a standing pool (see `gateway.py`'s module docstring) -- "unloaded" now means zero processes running, zero cost, but every cold `/load` pays real process-spawn + heavy-import time on top of the model's own load() call. `spawn overhead` below is exactly that gap (`wall-clock − server-reported`), broken out explicitly rather than left hidden inside the wall-clock number.

| Component | Load, server-reported (s) | Load, wall-clock (s) | Spawn overhead (s) | Unload -- process-kill, no respawn (s) | Peak RSS | Peak VRAM |
|---|---|---|---|---|---|---|
| ASR | 5.088 (min 4.831, max 5.396) | 6.641 | 1.553 | 0.953 (min 0.816, max 1.169) | 3.204GB | 0.0GB |
| NMT | 0.749 (min 0.69, max 0.838) | 3.296 | 2.547 | 0.58 (min 0.514, max 0.622) | 1.612GB | 0.0GB |
| TTS | 3.319 (min 3.318, max 3.319) | 7.45 | 4.131 | 0.534 (min 0.511, max 0.546) | 1.269GB | 0.863GB |

Raw samples per component:

- **ASR** load(server)=[4.831, 5.396, 5.035]s, load(wall-clock)=[6.012, 7.2, 6.712]s, unload=[0.816, 0.873, 1.169]s
- **NMT** load(server)=[0.717, 0.69, 0.838]s, load(wall-clock)=[3.318, 3.443, 3.126]s, unload=[0.514, 0.622, 0.606]s
- **TTS** load(server)=[3.319, 3.319, 3.318]s, load(wall-clock)=[7.431, 7.449, 7.469]s, unload=[0.546, 0.545, 0.511]s

## Ollama-served models (agent + embedder)

All generate-capable models loaded with `num_ctx=16384` (see the warning above) -- this is *not* Ollama's per-model default, it's this pipeline's configured value, set via `config.OLLAMA_NUM_CTX` and overridable per-call through the gateway's `/agent/load`.

| Model | Role | num_ctx | Size (VRAM) | Load (s) | Unload -- until gone from `/api/ps` (s) |
|---|---|---|---|---|---|
| qwen3.5:2b | agent (`/api/generate`) | 16384 | 2.647GB | 5.436 (min 5.125, max 5.809) | 0.72 (min 0.578, max 1.003) |
| nomic-embed-text | embedder (`/api/embed`) | (embed default) | 0.323GB | 2.456 (min 2.431, max 2.491) | 0.262 (min 0.229, max 0.326) |
| qwen3.5:0.8b | smaller-model comparison (`/api/generate`) | 16384 | 1.331GB | 5.388 (min 5.032, max 5.653) | 0.485 (min 0.469, max 0.513) |

Raw samples per model:

- **qwen3.5:2b** load=[5.809, 5.374, 5.125]s, unload=[1.003, 0.578, 0.579]s
- **nomic-embed-text** load=[2.491, 2.431, 2.445]s, unload=[0.231, 0.326, 0.229]s
- **qwen3.5:0.8b** load=[5.032, 5.653, 5.479]s, unload=[0.469, 0.513, 0.472]s

## Notes

- Ollama's unload HTTP call (`keep_alive: 0`) returns almost immediately, but the model stays visible in `/api/ps` as `Stopping...` for a further stretch before it actually disappears -- confirmed directly. The unload numbers above are timed until the model is genuinely gone from `/api/ps`, not until the HTTP call returned, since the HTTP-return number alone would understate real unload time.
- `nomic-embed-text` doesn't support `/api/generate` at all (confirmed: `"nomic-embed-text" does not support generate`) -- it's loaded/unloaded via `/api/embed` with an empty `input`, same `keep_alive` semantics.
- Workers are lazily spawned, not a standing pool (see `gateway.py`) -- every unload is now a full process kill, no respawn, and the next `/load` pays real process-spawn + heavy-import time on top of the model's own load() call (see the `spawn overhead` column above). This replaced an earlier always-on-pool design after a live orchestrator run caught its ~2.06GB combined idle-process baseline (ASR+NMT+TTS, never zero even fully "unloaded") pushing a supposedly-safe combination over the 7GB Jetson budget for real -- see `load_balancer_plan.md`'s update log.
- `qwen3:0.8b` (from the original notes) is not a real Ollama tag -- confirmed via `ollama pull` (`Error: pull model manifest: file does not exist`). The real tag is `qwen3.5:0.8b`, kept here only as the smaller comparison point now that the agent model has moved to `qwen3.5:2b`. Likewise there is no `qwen3.5:2.5b` tag.
- Verified directly (process list, not just `/api/ps`'s self-report) that Ollama runs each *loaded* model as its own `llama-server` subprocess (command line includes `-c <num_ctx>`, confirming the configured context size actually took effect), and that subprocess is fully gone -- not just flagged idle -- once the model is unloaded. Unloading a model this way is a genuine process-kill, the same guarantee as `?full=true` on the ASR/NMT/TTS workers, not a soft in-process release.
