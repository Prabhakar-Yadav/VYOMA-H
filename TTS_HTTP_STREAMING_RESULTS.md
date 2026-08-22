# Real HTTP Streaming TTS — What Was Built, Two Real Bugs Found, Final Verified Numbers

Generated 2026-08-05. Both TTS engines already had a non-streaming `/tts/infer` endpoint
(blocking — waits for the complete answer, returns one response) and, for Parler, a
proven local incremental-playback mechanism (`StreamingTTS.play_stream()`) that was never
reachable through the actual deployed HTTP pipeline (`test_orchestrated_pipeline.py` only
ever called `/tts/infer`). This work adds a second, real HTTP-streaming path
(`/tts/infer_stream`) that gets that same time-to-first-audio benefit through the gateway,
to a real remote caller, over real HTTP — **without removing or changing `/tts/infer`**,
which stays exactly as it was, on purpose, as the simpler fallback path if streaming turns
out to be a problem in practice (context loss across batches, network reliability on a
real device, etc.).

## What was built

- **`api_server/worker_base.py`**: `make_worker_app()` takes an optional `stream_infer_fn`
  and, only if a worker provides one, registers `/infer_stream` — a `StreamingResponse`
  yielding newline-delimited JSON, one line per chunk/batch as `stream_infer_fn` produces
  it. ASR/NMT never pass one (nothing to stream for a single short answer), so they don't
  get the extra route at all.
- **`api_server/workers/tts_worker.py`**: `_stream_parler` (generator version of
  `_infer_parler`, yielding per-batch instead of collecting into one list) and
  `_stream_mms_tts` (always yields exactly one item for a supported language — VITS has no
  partial output to stream — but delegates to `_stream_parler` for the 8 India languages
  MMS-TTS has no checkpoint for, since *that* fallback genuinely does have multiple chunks).
- **`api_server/gateway.py`**: real streaming passthrough for `/infer_stream` specifically
  (`httpx.AsyncClient.stream()` + `resp.aiter_bytes()` + `StreamingResponse`), separate from
  the generic proxy's buffered `resp.content` pattern used for every other route.
- **`models/tts_exports/streaming.py`**: `play_http_stream()` — the client. Consumes
  `/infer_stream`'s NDJSON and feeds it into the *exact same* smart-prebuffer
  buffering/playback algorithm `play_stream()` already used locally, refactored out into a
  shared `_smart_prebuffer_playback()` core so both paths run identical logic, not two
  parallel implementations that could drift.

## Two real bugs found during testing, not assumed away

Neither of these was visible from reading the code beforehand — both only showed up once
this was actually run end-to-end, through the real gateway, with real audio playing.

### Bug 1 — RTF estimate saw "0 elapsed time" for chunk 1, skipped buffering entirely

`play_http_stream()` has to peek the first streamed chunk before playback's buffering math
can even start (it needs `total_chars`, embedded in that first chunk's JSON). The original
version set `gen_t0` (the buffering algorithm's generation-rate clock) *after* that peek —
so the peek's own very real ~45s of network+generation time was invisible to the RTF
estimate. The algorithm concluded generation was instant (`elapsed_gen=0.00s`,
`running_rtf=0.00x`) and started playing immediately with zero buffer — then every
following chunk stalled for real, audible dead air (`STALL: waited 6.03s`, `3.17s`, `2.00s`
in the first real run). **Fix**: `gen_t0` is now captured *before* the HTTP request goes
out and threaded explicitly through `_launch_playback()` → `_smart_prebuffer_playback()`
(new optional `gen_t0=` parameter, defaults to "now" so `play_stream()`'s local path is
completely unaffected).

### Bug 2 (the real one) — the playback thread blocking on audio also stopped reading the network

Fixing bug 1 alone didn't fix the stalls — it just made them smaller, then in later test
runs a **new, larger, and fully reproducible** stall appeared: chunk 4 of 4 consistently
took ~77s longer than its own measured generation rate predicted, within 2% across two
independent process runs (144.37s and 147.00s) — far too consistent to be GPU/system noise.

Root-caused with real diagnostic timestamps on both sides (server-side: when each chunk was
actually produced/yielded; client-side: when each line was actually received), not guessed:
the server had already generated and sent chunk 4 by t≈78.7s (its own clock). The client
didn't receive that line until t≈96.7s — **not because the data wasn't there, but because
nothing was reading it.** `_smart_prebuffer_playback`'s consumer loop does two things on one
thread: pull the next chunk, and (once the buffer threshold is met) call `sink.play()`,
which **blocks for real, wall-clock seconds** while it paces itself against real-time audio
output (~37s for the first flushed batch). While that thread was blocked inside `sink.play()`,
it wasn't calling `next()` on the HTTP response iterator either — so the socket sat unread,
TCP-level backpressure kicked in, and the already-generated, already-sent chunk 4 just sat
buffered somewhere in the network stack until playback caught up and the loop finally asked
for more data again.

`play_stream()` (the local path) never hits this because `synthesize_stream_chunks()`
already runs its real generation on an independent background thread (a `producer()` +
`queue.Queue()` pattern), completely decoupled from whatever the consumer does with
playback timing. **Fix**: gave `play_http_stream()` that same decoupling — a background
`_reader` thread continuously drains and decodes the HTTP response into a `queue.Queue()`,
independent of the playback thread. Confirmed directly: identical `buffer_margin`, stalls
present without the reader thread, zero stalls with it.

A smaller, real contributing factor was also addressed: `buffer_margin` defaults to **1.35
for `play_http_stream()`, not 1.15** (`play_stream()`'s proven-safe local value) — real
per-chunk HTTP overhead (base64 encode/decode, JSON (de)serialization, the network hop
itself) is genuine added latency local generation never pays. This alone never fixed the
stalls (they occurred at both 1.15 and 1.35 before the reader thread existed), but it's
kept as real headroom on top of the reader-thread fix. 1.15-with-the-reader-thread wasn't
separately re-tested — 1.35 is confirmed to work, not confirmed to be the minimum needed.

## Final verified numbers — real gateway, real network, real playback, zero stalls

Both runs: real Hindi answer (860 chars, 4 real chunks after `chunk_text()`), through the
actual `run_all.py` gateway, `/tts/infer_stream`, `play_http_stream()`, `backend="sounddevice"`.

### Parler (`TTS_ENGINE="parler"`)

| | Value |
|---|---|
| Time to first audio actually playing | **52.12s** (buffering phase: chunk 1 at 47.14s "still buffering", chunk 2 at 52.12s "STARTING PLAYBACK NOW") |
| Stalls after playback started | **0** (chunks 3 and 4 both "ready in time, no stall") |
| Total wall-clock (network + generation + real-time playback) | 129.26s |
| Audio duration | 75.66s |

### mms_tts (`TTS_ENGINE="mms_tts"`)

| | Value |
|---|---|
| Time to first audio actually playing | **10.82s** (single chunk — no batching, nothing to buffer for, `needed=0.00s`) |
| Stalls | **0** (structurally impossible — one chunk, nothing to stall waiting for) |
| Total wall-clock | 75.57s |
| Audio duration | 64.72s |

Not directly comparable to `TTS_ENGINE_TIMING_RESULTS.md`'s earlier TTFA/total numbers —
those measured pure generation time with no playback ever happening (an isolated benchmark
of `synthesize_stream_chunks()`/`synthesize()` in a loop); the numbers here include real
audio actually playing through a real output device, which is what a user would actually
experience. The **52.12s Parler figure above is the number that matters**: real
time-to-first-audio, through the real deployed HTTP path, with the buffering/network stack
that real traffic would actually go through — not an in-process shortcut.

## What this doesn't change

`/tts/infer` is completely untouched — same function, same behavior, still the simpler,
proven, always-available path. `/tts/infer_stream` is additive. Neither
`test_orchestrated_pipeline.py`'s default behavior nor any other existing caller changed as
part of this work by itself — wiring the pipeline's own playback over to the new streaming
path (so a real turn actually benefits from this) is a separate, deliberate follow-up step,
not a side effect of adding the endpoint.

## Cross-chunk voice drift, measured and fixed (2026-08-23)

Streaming's ~12s chunks mean more independent VITS forward passes per answer than the
blocking path's 30s chunks — and each pass is an **independent unseeded draw**. VITS has
no speaker embedding to anchor "the voice" (these checkpoints are mono-speaker,
`speaker_embedding_size: 0`), no seed, and fresh latent/duration noise every call. A real
streamed Hindi answer (`orchestrated_hi_ux-1.wav`, 4 chunks) made this audible and then
measurable: median F0 per chunk via autocorrelation was **155 / 122 / 141 / 195 Hz** —
chunk 3 is +32% off the first three's running median and genuinely sounds like a different
person started talking. This is the same underlying property the 2026-08-09 chunk-size
revert documented as "no prosody continuity across the cut", heard at full strength.

Two levers, both config-tunable (`config.py` → `WORKERS["tts"]["engines"]["mms_tts"]`),
both implemented in `tts_worker.py` + `models/mms_tts/inference.py`:

1. **Lower sampling noise** — `noise_scale` 0.667→0.333, `noise_scale_s` 1.0→0.667,
   applied to the loaded VitsModel around its forward pass. Deploy-day lesson (2026-08-23):
   they can NOT be passed as `VitsModel.forward()` kwargs — this transformers build rejects
   them outright and both TTS paths died at once (the stream path surfaces it as a final
   NDJSON `{"error": ...}` line that reads client-side as `KeyError('audio_base64')`; the
   blocking path as a bare HTTP 500). They are model attributes — `model.noise_scale`,
   `model.noise_scale_duration` (= config's `noise_scale_s`), `model.speaking_rate` — set
   before forward() and restored in a `finally:` by `inference.py::synthesize()`.
   Clusters draws around the model's mean voice;
   costs some prosody liveliness. Initial values by reasoning, not by ear.
2. **F0 voice-matched redraw** — `_synthesize_voice_matched()`: each chunk's median F0
   (cheap numpy autocorrelation, `_chunk_f0_median`, central 8s window, bounded cost)
   must land within `voice_match_tolerance` (±15%) of the running median of prior chunks,
   else it redraws up to `voice_match_max_retries` (2), keeping the closest draw. Chunk 0
   is always accepted as-is — it IS the reference. At RTF ~0.1 a fully-retried chunk still
   finishes far inside its own playback time, so retries cannot stall the stream.

Telemetry: stream chunks now carry `f0_median` + `voice_tries` (surfaced in the app's
`[tts-stream]` end-of-turn block); blocking `/infer` responses carry `chunk_f0_medians` +
`voice_match_tries`. `seed` (null by default) makes all chunks share one random sequence
when set; `voice_match_tolerance=0` disables matching entirely.
