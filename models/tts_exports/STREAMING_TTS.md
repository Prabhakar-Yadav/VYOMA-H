# `streaming.py` — chunked, pipelined streaming TTS

Adds chunked/streaming generation on top of `inference.py`'s `TTSInferencer`. Doesn't replace
anything — `synthesize()`/`synthesize_long()` are untouched and still the right choice for
simple one-shot use; this module is for when time-to-first-audio matters (a live agent
answering out loud) and/or the input is long enough to risk `synthesize()`'s truncation cliff.

See also: [`vyoma_v5.ipynb`](../../vyoma_v5.ipynb) for a live side-by-side comparison against
the old path, and [`../STREAMING_TEST_RESULTS.md`](../STREAMING_TEST_RESULTS.md) for the full
log of every test run behind the numbers in this doc (batch-size sweep, all 4 per-language
runs, raw debug output).

## The problem this solves

`TTSInferencer.synthesize()` makes one `model.generate()` call for the *entire* input text and
returns nothing until it's done. Measured in `vyoma_v4.ipynb`'s own stage timing log, that's
**28–161 seconds of silence** before a real agent answer starts playing. Long enough answers
also risk `DEFAULT_MAX_NEW_TOKENS`'s truncation cliff (a real ~620-char answer was observed to
run a single `generate()` call all the way to the 3000-token/~35s cap).

## A dead end worth documenting: sub-chunk streaming does not work here

An early version of this module used `parler_tts.ParlerTTSStreamer` — a real, library-
supported mechanism for this model family — to decode chunk 0's audio in small windows
*during* generation (every ~10 generation steps) and play each window the instant it was
decoded, chasing a sub-second time-to-first-audio number. It measured well in isolation and
**sounded broken** when actually played through speakers: stuttering, "o-o-o" broken-syllable
audio, confirmed by listening, not just inferred.

The cause: generation on this hardware runs measurably slower than real-time (2.2x–4.9x for
solo calls across languages, measured on the GB10 dev workstation — see
[`STREAMING_TEST_RESULTS.md`](../STREAMING_TEST_RESULTS.md)). Playing each decoded window
immediately means the audio output device consumes it in real time, but the *next* window
doesn't arrive for another 2–5x its own duration — the output starves between every single
window, not occasionally. Sub-chunk incremental streaming only sounds clean when generation
keeps pace with playback. This is exactly how cloud TTS APIs (Deepgram, OpenAI) get away with
playing audio as it streams in — their inference keeps up with real-time; a quantized local
model running several times slower than real-time at low batch sizes does not, and trying to
play its intermediate decode state live just exposes that gap as audible glitching.

If a chunk has to fully finish generating before it can play back cleanly anyway, decoding it
in windows along the way buys nothing over one plain blocking call — same wall-clock until the
chunk is ready, with unusable audio in between. **The fix: generate every chunk as one complete
blocking call, and only ever hand a player a fully-generated chunk.**

## How it works (current design)

1. **`clean_text(text)`** — strips markdown the agent/NMT output tends to contain (`**bold**`,
   headers, bullets, links, etc.) down to plain speakable prose. Stress-tested against a real
   Malayalam answer containing a run of 30+ repeated `*` characters (an NMT mangling artifact,
   not synthetic) — strips cleanly, no leftover garbage. Paragraph breaks are kept as a signal
   for step 2.
2. **`chunk_text(text, sentence_lang=None, max_chunk_chars=180)`** — cleans, then splits into
   chunks cut only at sentence/paragraph boundaries, never mid-sentence. Reuses the project's
   own Indic-aware sentence splitter (`models/nmt/inference/engine.py`'s `split_sentences()` —
   handles Devanagari danda etc. via `indic_nlp_library`/Moses/NLTK), with a regex fallback if
   unavailable for a given language. A single "sentence" longer than `max_chunk_chars` (e.g. a
   dash-separated list with no internal terminal punctuation) is kept whole rather than
   mutilated — chunks can run over budget in that case, by design.
3. **`StreamingTTS(tts_inferencer)`** — orchestrates generation across chunks on a background
   producer thread, yielding each chunk's **complete** audio to the caller in order as soon as
   it's ready:
   - **`synthesize_stream_chunks(..., solo_first_chunk=True)`** (default): chunk 0 generates
     alone via one plain `TTSInferencer.synthesize()` call, for the fastest possible single
     ready chunk. Pass `solo_first_chunk=False` to batch it in with the rest instead —
     `play_stream()` does this, since its smart-prebuffer strategy (below) doesn't play
     anything until a buffer threshold is met regardless, so chunk 0's faster *solo* readiness
     buys nothing while its worse *solo* throughput only slows down reaching that threshold.
     Measured effect on a real 4-chunk answer: solo chunk 0 reached the buffer threshold at
     t=78.88s; batching it in reached the same point at t=45.06s — 43% faster.
   - **Remaining chunks** generate `batch_size` at a time (default 6) in single batched
     `generate()` calls, because autoregressive decode at batch=1 is memory-bandwidth-bound,
     not compute-bound —
     batching pushes real throughput up dramatically (see Performance below). This is also why
     thread-level concurrent `generate()` calls were *not* used instead: on one GPU with one
     copy of the model's weights, two independent `generate()` calls don't get the
     weights-read-once-shared-across-sequences benefit batching gets — they'd just queue up
     behind each other on the same device (or contend, with unverified thread-safety), with no
     real throughput win.
   - Only **one `generate()` call is ever in flight at a time** — matches this project's stated
     sequential-stage, memory-conscious design for the 8GB Jetson Orin Nano target.
   - If batched generation raises for any reason, falls back to plain sequential
     `TTSInferencer.synthesize()` per chunk — the existing, proven code path.
4. **`play_stream(...)`** — a **smart-prebuffer** consumer on top of `synthesize_stream_chunks()`
   (see its own docstring in `streaming.py` for the full derivation): measures RTF live from
   completed chunks, estimates total answer duration from total character count (known upfront,
   since chunking happens before any generation), and computes the minimum buffer — `total_
   duration * (r-1)/r` for measured rate `r` — that should let playback run through without
   starving, instead of either playing chunk 0 instantly (confirmed by listening: stalls after
   almost every chunk once RTF > 1) or waiting for the whole answer (the original 28-161s
   problem). **Verified zero detected stalls across all 4 languages tested** — see Performance.

## API

```python
from models.tts_exports import QuantizedParlerTTS, TTSInferencer, StreamingTTS

engine = QuantizedParlerTTS(checkpoint_dir="models/checkpoints/indic-parler-tts-awq-int4")
engine.load()
tts = TTSInferencer(engine)
streaming_tts = StreamingTTS(tts)

for audio, sample_rate, chunk_text, chunk_index, total_chunks in \
        streaming_tts.synthesize_stream_chunks(long_answer, language="Hindi"):
    ...  # feed a queue/socket/player -- each item is one COMPLETE chunk's audio

# or, to actually hear it, with the smart prebuffer doing the pacing:
streaming_tts.play_stream(long_answer, language="Hindi", backend="sounddevice")
```

`synthesize_stream_chunks(text, description=None, speaker=None, language=None, gender=None, sentence_lang=None, max_new_tokens=DEFAULT_MAX_NEW_TOKENS, max_chunk_chars=180, batch_size=6, solo_first_chunk=True)`
— same voice-selection params as `TTSInferencer.synthesize()` (`description`/`speaker`/
`language`/`gender`, see `inference.py`'s module docstring for how those resolve). `sentence_lang`
(iso-2-letter or flores code) drives sentence splitting; auto-derived from `language=` for
English/Hindi/Malayalam/Tamil/Gujarati, pass it explicitly for anything else. Yields
`(audio: np.ndarray[float32], sample_rate, chunk_text, chunk_index, total_chunks)` in order,
one complete chunk at a time.

`play_stream(text, ..., batch_size=6, backend="sounddevice", device=None, gap_seconds=0.5, buffer_margin=1.15, blocking=True, debug=False)`
— plays the stream with the smart-prebuffer strategy above. `debug=True` prints the live
RTF/threshold estimate and, once playback starts, whether each subsequent chunk arrived in
time or caused a detected stall — this is how every result in this doc was verified, not
inferred. See backends below for `backend=`/`device=`.

## Performance — measured, not assumed (GB10 dev workstation, real checkpoint)

- **Time-to-first-audio (to `play_stream()`'s buffering decision, i.e. when playback actually
  starts) measured 33.8s–46.3s** across 4 real per-language answers (4–10 chunks each,
  `batch_size=6`) — down from the old path's 28–161s wait for the *entire* answer, though not
  sub-second (see the dead-end section for why that specific earlier claim didn't hold up).
- **Batch size is nearly free here, far past the point that seems intuitive.** A sweep of
  `_generate_batch()` at batch_size 1–16 (16 same-length English sentences) found wall-clock
  time per call nearly flat while audio produced per call grew ~17x:

  | batch_size | wall_time | peak VRAM (Δ over baseline) | audio produced | RTF |
  |---|---|---|---|---|
  | 1  | 11.3s | +0.34GB | 5.1s  | 2.23x |
  | 2  | 10.3s | +0.39GB | 10.0s | 1.03x |
  | 3  | 11.3s | +0.46GB | 15.7s | 0.72x |
  | 6  | 12.3s | +0.63GB | 32.2s | 0.38x |
  | 9  | 13.3s | +0.79GB | 47.7s | 0.28x |
  | 12 | 14.1s | +0.94GB | 62.3s | 0.23x |
  | 16 | 15.2s | +1.15GB | 84.2s | 0.18x |

  This directly confirms the memory-bandwidth-bound theory: reading the weights once and
  applying them to more sequences per call is nearly free, at least up to batch=16 (not tested
  further; peak VRAM stayed under 2.1GB the whole way, so there was no forcing function to
  stop at 16). `batch_size=6` is `play_stream()`'s default — not the sweep's ceiling, but a
  practical choice, since real answers chunked at `max_chunk_chars=180` typically produce
  single-digit chunk counts (4–10 in the four real per-language answers tested), past which a
  larger batch has less to batch with anyway. **Not yet re-measured on the actual Jetson Orin
  Nano target** — this sweep is GB10 only, and VRAM/compute headroom will differ.
- **`max_chunk_chars` and `batch_size` interact — a chunk size that produces too few chunks
  defeats batching regardless of `batch_size`.** An earlier default (`max_chunk_chars=400`)
  produced only 2 chunks for a real ~600-char answer (chunk 0 + one leftover, nothing left to
  batch), and total time came out **0.64x — 56% *slower*** than the old single-call path.
  Lowering it to 180 reliably produces enough chunks (4–10 across the real per-language tests)
  for batching to matter.
- **Batching itself had a real bug, now fixed**: HF's batch `generate()` runs every item in a
  batch until the *longest* one finishes, so shorter items came back padded — confirmed via a
  per-item RMS envelope against solo-generated ground truth that the padding decodes as genuine
  silence, not garbage, but it was not small (1.6x–2.25x length inflation observed), which
  would have played back as real dead air after every batched chunk shorter than its
  batch-mates. Fixed with `_trim_trailing_silence()`.
- **`solo_first_chunk=False` measurably shortens `play_stream()`'s wait**: on the same real
  4-chunk Hindi answer, batching chunk 0 in with the rest reached the buffer threshold at
  t=45.06s vs. t=78.88s with chunk 0 solo first — 43% faster, because the solo call ran at the
  slower unbatched RTF instead of getting the batch throughput benefit.
- **Smart-prebuffer strategy: zero detected stalls across all 4 languages tested**
  (`batch_size=6`, `buffer_margin=1.15`, `debug=True` used to directly verify, not infer):

  | Language | Chunks | Chars | Playback starts at | Total wall-clock | Stalls |
  |---|---|---|---|---|---|
  | English   | 8  | 1338 | 33.76s | 128.43s | 0 |
  | Hindi     | 4  | 883  | 46.30s | 125.14s | 0 |
  | Malayalam | 5  | 875  | 43.83s | 105.73s | 0 |
  | Tamil     | 10 | 1305 | 35.70s | 129.07s | 0 |

  Full raw debug output for every run in [`../STREAMING_TEST_RESULTS.md`](../STREAMING_TEST_RESULTS.md).
- **None of the above has been re-benchmarked on the actual Jetson Orin Nano target** — GB10 is
  a dev workstation, not the deployment device. Re-run the same kind of sweep there before
  trusting these specific numbers on-device (the *mechanism* — batching, smart prebuffer — is
  architecture, not GB10-specific, but the tuned defaults are).

**Bottom line**: come to this module for the latency win (audio starts in tens of seconds
instead of tens-to-hundreds, and a long answer can no longer hit the truncation cliff a single
3000-token call risks) and for verified-gapless playback once it starts, not for sub-second
first audio — that specific claim didn't survive contact with actual playback.

## Tuning knobs

| Param | Default | Effect |
|---|---|---|
| `max_chunk_chars` | 180 | Smaller → shorter, faster-to-ready chunks and more of them for batching to work with; larger → fewer, longer chunks, worse on both. Keep well under ~620 chars regardless (truncation-risk data point). |
| `batch_size` | 6 (both `synthesize_stream_chunks` and `play_stream`) | Chunks generated together per call. Nearly free up to at least 16 on GB10 (see sweep above) — `1` disables batching entirely (safest starting point on constrained/unmeasured memory, e.g. actual Orin hardware). |
| `solo_first_chunk` (`synthesize_stream_chunks` only) | `True` (`False` for `play_stream`) | `True`: chunk 0 generates alone for fastest single-chunk readiness. `False`: chunk 0 batches in with the rest — better when nothing plays until a buffer accumulates anyway. |
| `buffer_margin` (`play_stream` only) | 1.15 | Safety margin (15%) added to the computed minimum prebuffer, since the RTF/duration estimates it's based on are averages with real per-chunk variance. |
| `gap_seconds` (`play_stream` only) | 0.5 | Pause inserted between chunks during playback. |

## Pocketinfer / Orin integration

`play_stream(..., backend="pocketinfer", device=..., blocking=False)` already exists for this —
built in from the start, not a retrofit. What it does and what's still needed:

**Already built:**
- Lazily imports `pocketinfer.audio.AudioPlayer` (only when `backend="pocketinfer"` is actually
  requested) — `streaming.py` stays importable in this project's own venv either way. Confirmed
  `pocketinfer` is **not installed** in this repo's `venv` today, so this path is code-reviewed
  but not execution-tested from here.
- Opens **one** `AudioPlayer(sample_rate, device=...)` for the whole stream (not reopened per
  chunk) and converts each yielded float32 chunk to int16 PCM (`_float32_to_int16_bytes()`) —
  the same `ffplay`-piped-to-ALSA sink `pocketinfer/models/piper.py`'s `Piper` class already
  uses, so audio delivery is identical to what that device stack already does today.
- `blocking=False` mirrors `Piper.start_playback()`/`stop_playback()`'s exact shape — runs
  playback on a background thread, returns a handle with `.stop()`/`.join()`, `.stop()` checked
  between chunks so playback can be interrupted mid-answer (needed since `pocketinfer`'s device
  UI loop is interactive and can't block on a multi-chunk TTS answer).
- Since every chunk handed to a sink is always a complete, fully-generated waveform, the
  `AudioPlayer`'s own buffering is naturally sufficient — no sub-chunk pacing concern to carry
  over to the on-device player.

**To actually wire it in on the Orin, later:**

1. **Make both projects importable together.** `dev/agents/models/tts_exports/` and
   `suno-sutra-sw/python/pocketinfer/` are currently two separate top-level projects with no
   import edge between them. On the Orin, either vendor/copy `models/tts_exports/` (plus
   whatever of `models/nmt/` it needs for `chunk_text()`'s sentence splitter) into the
   `pocketinfer` runtime, or install both into one shared venv. Check `parler_tts`/
   `torchao`/`transformers` version compatibility against whatever `pocketinfer` already pins
   in `suno-sutra-sw/python/setup.py` — not checked yet.
2. **Swap the call site.** In `pocketinfer/applications/hear_the_world.py` (and
   `hear_the_world_en.py`), replace:
   ```python
   self.piper = Piper(voice_name=..., audio_device=...)
   ...
   self.piper.start_playback(text)
   ...
   self.piper.stop_playback()
   ```
   with something like:
   ```python
   self.tts_engine = QuantizedParlerTTS(checkpoint_dir=...)  # load once at app startup
   self.tts_engine.load()
   self.streaming_tts = StreamingTTS(TTSInferencer(self.tts_engine))
   ...
   self._playback_handle = self.streaming_tts.play_stream(
       text, language=..., backend="pocketinfer", device=self.audio_device, blocking=False,
   )
   ...
   self._playback_handle.stop()
   self._playback_handle.join()
   ```
   `voice_name`/language selection needs a mapping from whatever `pocketinfer`'s app metadata
   uses today (Piper voice names) to this module's `language=`/`speaker=`/`description=`
   (`best_speakers.json`/`feminine_speakers.json` in this same directory) — not a 1:1 rename,
   needs a small lookup table like the per-language test scripts' `LANGUAGE`/`SENTENCE_LANG`
   pair, or `vyoma_v5.ipynb`'s `LANGUAGES` dict.
3. **Re-benchmark on the actual device before trusting the defaults.** Everything under
   Performance above was measured on a GB10 dev workstation, not Jetson Orin Nano hardware —
   including the RTF (real-time factor) numbers that motivate batching at all. Start with
   `batch_size=1`, measure time-to-first-audio and total time the same way the
   `test_streaming_*.py` scripts do (`debug=True` on `play_stream()`), and only raise
   `batch_size` if that measurement supports it. If Orin's RTF turns out close to or under 1x
   (faster hardware, or a smaller/faster checkpoint), most of the batching/chunk-size tuning in
   this doc may matter less — worth re-deriving from scratch there rather than assumed to
   transfer.
4. **Memory budget.** The quantized checkpoint alone measured ~0.86GB VRAM on GB10, growing to
   ~2GB at batch_size=16; the Orin Nano's 8GB is unified CPU+GPU memory shared with ASR/NMT/
   Agent if those run concurrently — worth a fresh full-pipeline memory snapshot (same
   `memory_utils.MemoryTracker` pattern this project already uses) once this is running
   on-device, not assumed to carry over from GB10.
5. **Decide whether this replaces Piper or lives alongside it.** Piper is a smaller, always-
   available fallback (different engine, different quality/language tradeoffs); this module is
   the higher-quality/more-language option. Not evaluated here which one `pocketinfer` should
   default to — that's a product decision for whoever does this integration.
