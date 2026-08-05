# MMS-TTS Evaluation — Replacing Indic Parler-TTS for GramSahayak

> **Historical evaluation report**, copied in from this repo's `dev/agents/` working area
> where the actual evaluation work (including the sanity-check notebook this doc references)
> happened — it isn't part of the `gramsahayak/` deployable package itself. Paths below like
> `dev/agents/mms_tts_test.ipynb` point to that original working area, not to anything inside
> this folder. The conclusion (mms_tts as the default engine) and the underlying numbers are
> exactly what `ARCHITECTURE.md` §3 summarizes — read that first; come here for the full
> derivation, the license verification, and the per-language audio quality notes.

Generated: 2026-08-05. Evaluates Meta's MMS-TTS (`facebook/mms-tts-*`) as a possible
replacement for the current AWQ+TorchAO int4 Indic Parler-TTS engine
(`dev/agents/models/tts_exports/`) for the Jetson Orin Nano deployment (8GB unified memory,
~7GB usable budget — `suno-sutra-sw/python/pocketinfer/memory_orchestrator/
load_balancer_plan.md`). Every number below is a real, directly-measured value from this
dev machine (NVIDIA GB10) — no estimates, same rigor as `dev/agents/api_server/
TIMING_RESULTS.md` and `dev/local_model_test/tts_memory_log.txt`.

Code produced alongside this report: `dev/agents/models/mms_tts/` (engine wrapper),
`dev/agents/mms_tts_test.ipynb` (audio generation + sanity-check notebook, already
executed — outputs included), `dev/local_model_test/test_mms_tts_memory.py` (timing/memory
harness, already run — raw log in `dev/local_model_test/mms_tts_memory_log.txt` and
`mms_tts_memory_results.json`).

---

## 1. License — CONFIRMED CC-BY-NC 4.0, a real commercial blocker

Checked directly against the Hugging Face Hub API (`HfApi.model_info`), not the model
card's marketing framing, against every repo actually touched by this evaluation:

| Repo | `license` tag | Model card text |
|---|---|---|
| `facebook/mms-tts` (umbrella repo) | `cc-by-nc-4.0` | "License: cc-by-nc-4.0" |
| `facebook/mms-tts-eng` | `cc-by-nc-4.0` | "The model is licensed as CC-BY-NC 4.0" |
| `facebook/mms-tts-hin` | `cc-by-nc-4.0` | same |
| `facebook/mms-tts-mal` | `cc-by-nc-4.0` | same |
| `facebook/mms-tts-tam` | `cc-by-nc-4.0` | same |

**Non-Commercial only, no sublicensing under different terms.** This is a hard legal
blocker for any commercial GramSahayak deployment (sold, monetized, bundled into a paid
product/device, or otherwise for commercial advantage) — confirmed with the project owner
before proceeding past this point: **GramSahayak's current phase is non-commercial/research,
so this evaluation was authorized to continue**, but this license must be re-checked (and
almost certainly blocks MMS-TTS outright, or requires a direct commercial license from Meta)
the moment shipping becomes commercial. Do not treat anything below as a green light to ship
MMS-TTS in a monetized product.

For contrast, confirm current Parler-TTS's own licensing separately before treating this as
"the same tradeoff either way" — that was not in scope for this evaluation and should not be
assumed.

---

## 2. Real per-language coverage — not the "1107 languages" headline

`facebook/mms-tts`'s model card states it "supports 1107 languages" — that is every
language Meta's MMS project covers across all speech tasks, not a claim that all 1107 have
well-trained, non-degenerate TTS checkpoints. The number the user recalled ("19 Indian
languages") does not appear anywhere on the actual model card or repo file listing checked
here — it doesn't match either the 1107 headline or any per-language subset documented by
Meta, and should not be relied on. Confirmed for real, for exactly this project's 4 target
languages, by checking each per-language repo's actual file listing (not just the headline
count):

| Language | 2-letter (this project) | ISO 639-3 | HF repo | Repo exists? | Real weights present? |
|---|---|---|---|---|---|
| English | en | eng | `facebook/mms-tts-eng` | Yes | Yes — `model.safetensors` (139MB) + `pytorch_model.bin` |
| Hindi | hi | hin | `facebook/mms-tts-hin` | Yes | Yes — same |
| Malayalam | ml | mal | `facebook/mms-tts-mal` | Yes | Yes — same |
| Tamil | ta | tam | `facebook/mms-tts-tam` | Yes | Yes — same |

All 4 of this project's target languages have real, downloadable, loadable checkpoints —
no gaps, no missing language. (Coverage for languages beyond these 4, should the project
expand later, was **not** checked here and should not be assumed from this table.)

---

## 3. Architecture — CONFIRMED VITS, non-autoregressive, single forward pass

Loaded `facebook/mms-tts-hin` directly and inspected its actual `config.json` and inference
behavior (not assumed from the model name):

- `config.json`: `"model_type": "vits"`, `"architectures": ["VitsModel"]`
- Loaded via `transformers.VitsModel.from_pretrained(...)` (`transformers==4.46.1`,
  `transformers.models.vits.modeling_vits`)
- Calling `model(**inputs)` directly (no `.generate()` loop) returns a
  `VitsModelOutput` whose `.waveform` tensor is the complete synthesized audio in one
  forward pass — confirmed by inspecting the tensor shape and timing one real call.
- No KV-cache, no `max_new_tokens` cap, no autoregressive decoding loop of any kind —
  architecturally cannot exhibit the runaway/near-silent decoding failure mode documented
  in the Parler engine's own `model_loader.py` docstring (that failure is specific to
  autoregressive codec-token decoding).
- Each checkpoint: ~36M parameters, ~139MB on disk (`model.safetensors`) — small enough
  that all 4 languages fit resident simultaneously (see §7).
- Mono-speaker: every checkpoint's `config.json` has `num_speakers: 1`,
  `speaker_embedding_size: 0` — no voice-description prompt, no speaker/gender control
  (unlike Parler-TTS's prompt-driven voice selection).

This confirms the premise of the evaluation: MMS-TTS's architecture is fundamentally
different from Parler-TTS's autoregressive DAC-codec-token decoder, which is the real
reason the memory/speed numbers below differ as much as they do.

---

## 4. Checkpoints downloaded

`dev/agents/models/checkpoints/mms-tts-{en,hi,ml,ta}/` — 139MB each, 556MB total, via
`huggingface_hub.snapshot_download` with `HF_TOKEN` (present in `.env`, no gating issue —
these repos are public, the token was not actually required but was available).

---

## 5. Engine wrapper — `dev/agents/models/mms_tts/`

- `model_loader.py` — `MmsTtsEngine(language=, checkpoint_dir=, device=)`, mirrors
  `QuantizedParlerTTS`'s shape exactly: `.is_loaded`, `.load()`, `.unload()`,
  `.vram_allocated_gb()`, context-manager support. **Key structural difference**: MMS-TTS
  is one checkpoint *per language*, not one multilingual model — this engine holds exactly
  one language at a time; switching languages means `unload()` + `load(language=...)`
  again (or holding multiple engine instances — see §7 for why that's realistic here).
- `inference.py` — `MmsTtsInferencer(engine).synthesize(text)` → `(audio, sample_rate)`.
  Much simpler than Parler's `TTSInferencer`: no description/speaker/gender resolution, no
  `max_new_tokens` — VITS has neither concept.
- **Unload correctness, verified directly** (not assumed): `torch.cuda.memory_allocated()`
  and `memory_reserved()` both drop to the same ~0.033-0.034GB CUDA-context floor Parler's
  own `unload()` leaves behind (confirmed in `tts_memory_log.txt`) — full GPU release,
  same architectural residual (CUDA driver context + cuDNN/cuBLAS workspace, not
  reclaimable in-process, same as documented in the Parler engine's own docstring). Host
  RSS shows the same expected non-return-to-baseline pattern for the same reason.

---

## 6. Audio quality — real generated audio, sanity-checked, NOT just "it ran"

`dev/agents/mms_tts_test.ipynb` (executed; outputs are real, not fabricated) generated real
`.wav` files for all 4 languages at `dev/agents/sample_audio/pipeline_outputs/
mms_tts_{en,hi,ml,ta}.wav` from real sample text:

- **en**: `Q1_TEXT_EN` verbatim from `test_orchestrated_pipeline.py`.
- **hi/ml/ta**: real ASR transcriptions (this project's own `ai4bharat/
  indic-conformer-600m-multilingual` engine) of the actual native-language question audio
  already in the repo (`sample_audio/pipeline_inputs/q1_{hi,ml,ta}.wav`) — not hand-written
  or translated, so this doesn't flatter the checkpoint with training-distribution text.

**Important honest limitation**: this notebook was run by an AI agent with no ability to
literally listen to audio. All 4 `.wav` files are real, playable, and a human on this
project should listen to them directly before trusting the quality conclusion below —
`dev/agents/sample_audio/pipeline_outputs/mms_tts_{en,hi,ml,ta}.wav`. What *was* run as a
real, automated proxy: round-tripping the hi/ml/ta output back through the project's own
ASR engine and comparing to the original text (English has no ASR support in this repo, so
no automated proxy exists for it — needs direct listening only).

| Language | Word overlap (original vs. round-trip ASR text) | Round-trip transcript |
|---|---|---|
| Hindi | **95.2%** | `आलू को कीकों और चूहों से बचाने के लिए मुझे अपने छोटे से खेत में सबसे अच्छे कीटनाशकों का उपयोग करना चाहिए` (one word differs: कीकों vs कीटों) |
| Malayalam | **71.4%** | `ഉറവക്കിഴങ്ങ കീടങ്ങളിൽ നിന്നും എലികളിൽ നിന്നും തടയാൻ എൻറെ ചെറിയ കൃഷിയിടത്തിൽ ഞാൻ ഉപയോഗിക്കേണ്ട ഏറ്റവും മികച്ച കീടനാശിനികളേറെ ഉണ്ടാക്കിയാണ്` |
| Tamil | **60.0%** | `உருளைக்கிழங்குப் பூச்சிகள் மட்டும் எலிகிலிருந்து வெளியேறுவதைத் தடுக்க எனது சிறிய பனையில் நான் பயன்படுத்த வேண்டிய சிறந்த பூச்சிக்க கொல்லிகள் யாவ` |

**Flagging this plainly rather than smoothing it over**: Hindi's round-trip is nearly
perfect. Malayalam and Tamil's word-overlap numbers are meaningfully lower, and this
metric is *confounded* in a way worth being explicit about — the "original" hi/ml/ta text
itself came from ASR transcription of real audio, not ground-truth text, so some divergence
reflects ASR noise on **both** ends (input transcription error + output transcription
error), not necessarily TTS quality alone. Still, a 60-71% overlap is a real, lower signal
than Hindi's 95% and should not be waved away as "probably fine" — **a human on this project
should listen to `mms_tts_ml.wav` and `mms_tts_ta.wav` specifically** before trusting
Malayalam/Tamil quality for this checkpoint. This project has the least first-hand listening
experience with MMS-TTS's Malayalam/Tamil output of any of the 4 languages, and that gap is
not closed by this evaluation alone.

All 4 clips passed basic non-silence / plausible-duration / non-clipping automated checks
(rms > 1e-4, 0.3s < duration < 60s, peak amplitude < 0.999) — this only rules out
completely-broken output, not quality.

---

## 7. Real measured load/inference/memory numbers

`dev/local_model_test/test_mms_tts_memory.py`, 3 repeats per language, same structure as
`test_tts_memory.py`/`test_timing.py`. Full raw data:
`dev/local_model_test/mms_tts_memory_results.json`, `mms_tts_memory_log.txt`.

| Language | Load time (mean, s) | Steady VRAM (alloc / reserved, GB) | Synth time, single utterance (mean, s) | Audio duration (s) | RTF | Peak VRAM during synth (alloc / reserved, GB) | Unload time (mean, s) | VRAM after unload |
|---|---|---|---|---|---|---|---|---|
| en | 1.584 | 0.169 / 0.184 | 0.464 | ~7.4 | 0.062 | 0.297 / 0.365 | 0.133 | 0.034GB |
| hi | 1.661 | 0.180 / 0.195 | 0.135 | ~8.6 | 0.016 | 0.310 / 0.377 | 0.131 | 0.034GB |
| ml | 2.013 | 0.180 / 0.195 | 0.153 | ~10.2 | 0.015 | 0.333 / 0.422 | 0.122 | 0.034GB |
| ta | 2.004 | 0.180 / 0.195 | 0.176 | ~12.4 | 0.014 | 0.368 / 0.514 | 0.174 | 0.034GB |

RTF (real-time factor) < 1 means faster than real-time. **All 4 languages synthesize
7-12 seconds of audio in well under 0.5 seconds — 15-70x faster than real-time**, every
single repeat, no outliers.

**Worst-case-scale stress test** (separate one-off run, not part of the 3-repeat table
above): a 643-character, 4x-repeated real question pair (`Q1_TEXT_EN` + `Q2_TEXT_EN`,
mirroring Parler's own worst-case methodology of testing long multi-sentence input)
produced **38.08s of audio in 1.139s** (RTF **0.030**), peak VRAM **0.787GB allocated /
1.028GB reserved**. Unload confirmed clean (0.034GB residual, same floor as every other
measurement here).

**All 4 languages loaded simultaneously** (one-off check, not the default engine design):
`en` 0.146GB → `+hi` 0.294GB → `+ml` 0.441GB → `+ta` **0.587GB allocated / 0.604GB
reserved total**. Small enough that keeping all 4 languages resident at once inside the
7GB Jetson budget is realistic, which would eliminate the per-language-switch reload cost
entirely — a real design option for the orchestrator, not evaluated further here (would
need its own load-balancer-plan update if pursued).

---

## 8. Head-to-head: MMS-TTS vs. current Indic Parler-TTS (AWQ+TorchAO int4)

Parler-TTS figures below are pulled directly from this project's own existing measurements
(`TIMING_RESULTS.md`, `tts_memory_log.txt`, `load_balancer_plan.md`) — not re-measured here.

| Metric | Indic Parler-TTS (current) | MMS-TTS (this evaluation) |
|---|---|---|
| Architecture | Autoregressive, DAC codec-token decoder (KV-cache grows with output length) | VITS, non-autoregressive, single forward pass |
| License | (not re-checked in this evaluation) | **CC-BY-NC 4.0 — non-commercial only, confirmed** |
| Per-language coverage | One shared model, many languages via voice-description prompt | One checkpoint per language — confirmed real weights for en/hi/ml/ta |
| Checkpoint size | ~820MB state_dict (int4-packed) | ~139MB per language |
| Steady VRAM | 1.27-1.94GB | **0.15-0.18GB** (~8-10x smaller) |
| Peak VRAM, typical single utterance | ~1.17-1.30GB (cuda `max_memory_allocated`, 4.4-4.5s audio) | **~0.30-0.37GB alloc** (7-12s audio — longer utterance, still smaller) |
| Peak VRAM, worst-case long input | 2.99GB alloc / 4.28GB reserved (34.7s audio, single `generate()` call, hit the 3000-token cap — truncated) | **0.79GB alloc / 1.03GB reserved** (38.1s audio, completed naturally, no cap to hit) |
| Peak VRAM, real batched multi-chunk answer (TTS alone, nothing else resident) | 4.46-5.2GB (real orchestrator observation, `load_balancer_plan.md`) | Not directly tested at this scale, but the worst-case single-call number above (1.03GB) is already ~4-5x under this Parler figure |
| Load time (engine.load() alone) | 3.319s (server-reported) | **1.58-2.01s** |
| Synthesis time, typical utterance | ~9.9-11.3s for 4.4-4.5s audio (**RTF ~2.2-2.5, slower than real-time**) | **0.13-0.46s for 7-12s audio (RTF 0.01-0.06, 15-70x faster than real-time)** |
| Synthesis time, worst-case long input | 88.7-105.9s for 34.7s audio (RTF ~2.6-3.05, and truncated by the 3000-token cap — didn't actually finish the intended text) | **1.14s for 38.1s audio (RTF 0.03), completed the full text, no cap** |
| Unload — VRAM residual | ~0.034GB (same CUDA-context floor) | ~0.034GB (same CUDA-context floor) |
| Multi-language flexibility | One model, switch language via prompt — no reload | One model per language — reload (~1.6-2s) to switch, **or** keep multiple resident (all 4 together: 0.59GB) |

**The gap is not close.** On every memory and speed axis measured, MMS-TTS beats the
current Parler-TTS engine by roughly an order of magnitude, and does so *more reliably*:
Parler's worst-case test didn't even finish the intended text (hit its `max_new_tokens`
cap), while MMS-TTS's equivalent-scale test completed cleanly with a comfortable memory
margin, because there is no autoregressive cap to hit in the first place.

---

## 9. Recommendation

**Replace, but gate strictly on the license — not a "keep both" or "don't switch" call.**

Reasoning:

1. **License is the entire question, not a technical one.** MMS-TTS's memory/speed
   advantage over Parler-TTS is large enough (roughly 8-10x smaller steady footprint,
   4-5x smaller worst-case peak, 15-70x faster synthesis) that if licensing were clean this
   would be an easy, unambiguous replace. It is not clean: CC-BY-NC 4.0 is a real,
   confirmed, non-negotiable-without-a-separate-Meta-license blocker for any commercial
   GramSahayak deployment. **This recommendation is conditional on the project remaining
   non-commercial**, exactly as scoped by the project owner before this evaluation
   proceeded. The moment monetization is on the table, this entire recommendation needs to
   be revisited — either drop MMS-TTS, negotiate a commercial license from Meta, or find a
   commercially-licensed VITS-family alternative (out of scope here).
2. **Technical case for replacement is strong and broad-based, not a single cherry-picked
   number.** Every measured axis — steady VRAM, peak VRAM (both typical and worst-case),
   load time, and synthesis time — favors MMS-TTS by a wide margin, and the worst-case
   comparison is the most telling: Parler's own worst-case test *failed to complete the
   intended text* (truncated by its generation cap) while consuming more memory than
   MMS-TTS's *comfortably-completed* equivalent. For a memory-constrained 8GB device, this
   removes an entire class of orchestrator complexity: `load_balancer_plan.md`'s Rule 8
   (evict Agent unconditionally before every TTS peak) exists specifically because Parler's
   peak VRAM isn't reliably boundable ahead of time. MMS-TTS's peak is small and
   architecturally bounded (no KV-cache growth) — worth re-evaluating whether Rule 8's
   unconditional-eviction cost is still needed at all if MMS-TTS becomes the TTS engine.
3. **Quality is the one open question, and it's not uniform across languages.** Hindi's
   round-trip intelligibility proxy (95.2% word overlap) is strong. Malayalam (71.4%) and
   Tamil (60.0%) are meaningfully weaker by the same automated proxy, and this evaluation's
   own limitation (an AI agent cannot listen) means that gap has not been resolved by a
   human ear yet. **Before committing to replacement, a human on this project must listen
   to `sample_audio/pipeline_outputs/mms_tts_{en,hi,ml,ta}.wav` directly** — particularly
   ml/ta — and judge naturalness/prosody/acceptability for farmer-facing use, not just
   "does it produce the right words." If Malayalam/Tamil quality turns out to be
   unacceptable on a real listen, "keep both, selectable per-language" becomes the right
   fallback (e.g. MMS-TTS for en/hi where it's clearly strong, Parler-TTS retained for
   ml/ta) rather than an all-or-nothing switch — the engine wrapper built here
   (`MmsTtsEngine`) is already structured to make that per-language selection trivial to
   implement if needed.
4. **Not yet re-run on the actual Jetson Orin Nano.** Every number here, like every other
   number in this project's timing docs, is from the NVIDIA GB10 dev machine. Given the
   scale of the advantage (order-of-magnitude, not a close call), it's very unlikely
   Jetson-specific overhead flips the conclusion, but re-run `test_mms_tts_memory.py`
   on-device before finalizing, same caveat every other timing doc in this repo already
   carries.

**Concrete next step**: a human listening pass on the 4 generated clips (5 minutes of
actual work) is the single highest-value action before deciding between "full replace" and
"replace en/hi, keep Parler for ml/ta" — everything else in this evaluation already points
toward replacement.

---

## 10. Post-integration correction — §7's steady/peak numbers were VRAM-only

mms_tts shipped as the default engine (`config.TTS_ENGINE`) after this evaluation, wired
into `tts_worker.py`, and exercised through a real live run of
`test_orchestrated_pipeline.py`. That run caught something this evaluation's §7 numbers got
wrong: **the orchestrator budgets against RSS+VRAM combined** (`orchestrator.py`'s
`snapshot()`/`total_bytes`), but §7's "steady VRAM" and "peak VRAM" figures were exactly
that — VRAM only, from the isolated bare-Python benchmark. They were accurate labeled as
VRAM, but incomplete for pool-budgeting, the same gap `load_balancer_plan.md`'s own
update-log point 7 already flagged for worker-process RSS in general (Python + torch +
transformers + FastAPI overhead is real, non-trivial RSS, not VRAM).

Real combined numbers, confirmed directly against the actual `tts_worker.py` process
(`/status`, all 4 `preload_languages` resident):

| | VRAM only (§7's original number) | Real combined RSS+VRAM (corrected) |
|---|---|---|
| Steady (4 languages loaded, idle) | 0.18-0.20GB | **1.47GB** |
| Peak (real synthesis, long answer) | 0.30-1.03GB | **~2.5-3.7GB** (RSS-dominated, not VRAM-dominated — confirmed the jump is mostly host-side, not GPU-side) |

`config.py`'s `_TTS_ENGINE_CONFIGS["mms_tts"]` now carries the corrected combined figures.
**The head-to-head conclusion in section 8-9 still holds** — 3.7GB real worst-case combined
pool is still meaningfully under Parler-TTS's 4.46-5.2GB real combined peak — but the margin
is smaller than §7 made it look, and anyone reading §7's numbers in isolation should read
this correction alongside them rather than trust the VRAM-only figures for pool budgeting.

**Not yet done**: `suno-sutra-sw/python/pocketinfer/memory_orchestrator/
load_balancer_plan.md`'s Section 2 (Module Footprints) and Section 9 (config JSON) still
describe Parler-TTS's footprint only — that doc was never updated to reflect mms_tts as the
new default engine or the corrected numbers above. Worth a follow-up pass before trusting
that document's own worked examples (Rule 8 etc.) for an mms_tts-default deployment.
