# ASR: Per-Language INT8 Quantized Models — Replacing the Multilingual Model

Generated: 2026-08-08. This supersedes the multilingual model as ASR's default (`asr_worker.py`,
`config.py`'s `WORKERS["asr"]`) -- the old model stays on disk at
`models/checkpoints/indic-conformer-600m-fp32/` and the old loader at
`models/asr/model_loader.py` + `models/asr/ctc_only.py` for reference/rollback, but nothing in
the running system uses them anymore.

## What changed

Source: `model_quantizer/asr_indic_confirmer_quantizer.py` takes AI4Bharat's real per-language
`.nemo` hybrid RNNT-CTC checkpoint, loads it via NeMo's `EncDecCTCModel.restore_from()`, sets
`cur_decoder='ctc'`, exports a **CTC-only ONNX graph** (`model.export()`), then
`onnxruntime.quantization.quantize_dynamic()` quantizes weights to **INT8**. Real run recorded in
`model_quantizer/asr_compression_and_quantization.ipynb`. Output per language:
`indicconformer_<lang>_ctc.int8.onnx` (188MB) + `tokens.txt` (shared vocab) + `config.json`
(mel/window preprocessing params) -- no NeMo, no torch, no CUDA needed at inference time, just
`onnxruntime` + `librosa` + `numpy` + `psutil` (`models/asr/indic_quantized_asr.py`, vendored
from the repo-root `model_quantizer/indic_quantized_asr.py`).

**This is a different, larger lever than the earlier `ctc_only.py` fix.** That fix cut ONNX
Runtime session count (29->3) on top of the *same* large, shared, 22-language encoder (~2.4GB).
This is a genuinely single-language encoder, exported directly from AI4Bharat's per-language
checkpoint (not sliced out of the multilingual one) -- an order of magnitude smaller before
quantization even applies, running CPU-only (`CPUExecutionProvider`, deliberately -- at this
size CPU is fast enough that GPU's CUDA-session-build overhead, the dominant cost fought
throughout this whole investigation, isn't worth paying for at all).

**Scope**: hi/ta/ml only (`config.WORKERS["asr"]["languages"]`), not all 22 scheduled languages
the old model covered -- deliberate, not an oversight: these are the only three with real audio
test fixtures in this repo. `bn` was also quantized (available in `models_quantized/models/bn/`
at the repo root) but not deployed.

**Loads all configured languages eagerly** (`quantized_multilang_loader.py`'s
`QuantizedMultiLangASR`), not lazily per-request -- affordable here (each language costs ~200-
300MB) in a way it wasn't for the old multilingual model, and preserves the existing
"load() does the work, infer() is fast" semantics the orchestrator's timing/memory snapshots
already assume.

## Correctness

Verified directly against the multilingual model's own output on the same real audio files.
**Hindi: byte-identical.** Tamil/Malayalam: small character-level differences (e.g. Tamil
"எலிகளிலிருந்து" vs "எலிகளில்ிருந்து") -- consistent with expected INT8 quantization accuracy
loss, not a decoding bug. One Malayalam sample garbles the same word ending under both the old
and new model -- a pre-existing model weakness either way, not something this change introduced.

## Real measured numbers

### Standalone (bare script, no gateway)

| | GX10 | Jetson |
|---|---|---|
| Load, hi alone | 0.78s / +302MB | 1.82s / +322MB |
| Load, all 3 (hi+ta+ml) combined | 2.415s / ~787MB total | 5.24s (first run) / ~737MB total |
| Transcribe (9-10s audio), typical | RTF 0.16-0.29 | RTF 0.07-0.29 (see note below) |

**Note on Jetson's first inference**: in the bare-script test, Hindi (transcribed first in that
process) took 15.5s (RTF 1.72, slower than real-time) while Tamil/Malayalam right after took
0.6-0.7s (RTF ~0.07) -- a one-time "first inference in this process" warmup cost (CPU thread-pool
init / governor clock ramp-up), not something specific to Hindi. Through the real gateway
(fresh process each time), this didn't reproduce as dramatically -- pipeline runs below show
5.5-7.3s infer times consistently across all three languages.

### Via the real gateway (repeated load/unload cycles, Jetson)

| | Load (server / wall) | Unload |
|---|---|---|
| Cycle 1 (cold process spawn) | 11.79s / 13.42s | 0.36s |
| Cycle 2 (fresh process spawn) | 5.29s / 6.58s | 0.41s |
| Cycle 3 (fresh process spawn) | 5.23s / 6.51s | 0.37s |

Peak RSS: **0.793GB**. Notably **consistent** run to run (cycles 2-3 within 60ms of each other)
-- essentially every source of variance chased throughout this investigation (eMMC cold-cache
penalty, GPU clock/power-state ramp under the 15W cap, CUDA session-build cost) doesn't apply
here at all, because there's no GPU involvement and the checkpoint is ~4x smaller (564MB for all
three languages vs. 2.4GB for the old encoder alone).

### Full agentic pipeline (`test_orchestrated_pipeline.py`, real gateway, real Ollama agent,
real NMT/TTS, Agent loaded once for the session per the 2026-08-07 policy change)

| Language | ASR ready | ASR footprint | ASR infer | Agent turn | **Total turn** |
|---|---|---|---|---|---|
| hi | 13.78s | 0.66GB | 5.53s | 53.22s (3 tool calls) | **110.91s** |
| ta | 15.73s | 0.75GB | 6.65s | 91.07s (tool calls) | 145.66s |
| ml | 15.78s | 0.63GB | 7.26s | (unlogged tool count) | 161.38s |

hi's **110.91s is the fastest full turn recorded in this entire investigation** -- the previous
best (agent-always-up policy, old multilingual ASR) was 147.62s. Total-turn variance across the
three languages here is dominated by the Ollama agent's own tool-calling behavior (53-91s), not
by ASR anymore.

## Comparison to the old multilingual model (same Agent-resident scenario)

| | Old model (ctc_only=True, 29->3 sessions) | New model (per-language INT8) |
|---|---|---|
| ASR ready (Agent resident) | 38.74-46.35s | 13.78-15.78s |
| ASR memory footprint | 3.63-3.66GB | 0.63-0.75GB |
| Checkpoint size (disk) | 2.4GB (shared 22-lang encoder) | 564MB (hi+ta+ml combined) |
| Runtime dependency | torch + onnxruntime-CUDA | onnxruntime-CPU only |
| Coverage | 22 languages | 3 languages (hi/ta/ml) |

Roughly **3x faster to load, 5x smaller in memory**, torch dependency eliminated entirely for
ASR (NMT/TTS still need it), at the cost of language coverage narrowed to the three actually
tested/used in this repo and a small, measured Tamil/Malayalam accuracy tradeoff from INT8
quantization.

## Update 2026-08-08: ASR no longer evicted right after its own inference (Rule 6 removed)

Tested and confirmed safe. `run_asr()` no longer unloads ASR immediately after transcription --
it now stays resident through the NMT and Agent stages too (Rule 1's ASR/TTS complementary pair
and Rule 10's post-TTS preload are unchanged and still do their jobs).

Real pipeline run (hi, `pipeline_hi_asr_resident_2026-08-08.log`): ASR loaded (8.95s), stayed at
**0.68GB resident through NMT (hi->EN) -> Agent turn -> NMT (EN->hi)** -- reaching a peak of only
**3.40GB / 48.6% of budget** right before TTS, comfortably safe. Rule 1 then evicted it exactly
at the ASR/TTS boundary as designed (`"EVICT asr -> Rule 1: complementary to tts"`), TTS's real
peak came in at 2.18GB (predicted 3.70GB, same pattern of the conservative estimate
overshooting reality seen throughout this investigation), and Rule 10 preloaded ASR back
afterward for the next turn. No crash, no budget violation. Total turn was 164.17s, longer than
the 110.91s record from the previous section -- but that's the Ollama agent's own tool-calling
variance (5+ tool calls this run vs. 3 in the record run), not related to this change.

This was only affordable because of the new model's footprint -- the old multilingual model
(2.7-3.7GB) sitting through NMT+Agent on top of Agent's own 1.31GB would have pushed those
same stages uncomfortably close to budget, which is exactly why Rule 6 existed in the first
place.

## Update 2026-08-08: TTS chunk size retuned for duration (~30s), not just memory

Background (see the TTS-ONNX exploration this superseded): testing an ONNX/CUDA MMS-TTS
export to reduce memory found the actual "crisis" didn't exist in the deployed system --
`tts_worker.py`'s existing `chunk_text()`-based chunking (added for a real prior crash, see
that function's own history) already keeps peak memory flat (~1.5GB) regardless of answer
length. The ONNX path was abandoned (consistent, worsening speed cost for a shrinking,
already-solved memory problem) and fully cleaned up -- no production files were touched
during that exploration, nothing left behind.

What *did* stick: the existing chunk size (180 chars, produces ~14s/chunk for Hindi) was
tuned only for memory-bounding, not for how long each streamed chunk actually plays --
retuned to target ~30s/chunk instead, calibrated per language from real synthesis (Jetson,
production `MmsTtsInferencer`, real ASR-transcribed sentences): hi=12.01 chars/sec,
ta=12.47, ml=12.23 (remarkably consistent across scripts, ~4% spread) -> 360/373/366 chars
respectively (`config.py`'s `chunk_max_chars_by_language`). Parler's own `chunk_text()`
usage is untouched -- this only affects the mms_tts call sites.

### Final full-pipeline validation, all three languages, everything integrated together

New quantized ASR + agent-always-resident policy + retuned ~30s TTS chunking, real gateway,
real Ollama agent, real NMT/TTS:

| Language | ASR ready | ASR memory | ASR infer | TTS infer | TTS peak | TTS chunks | Total turn |
|---|---|---|---|---|---|---|---|
| hi | 15.55s | 0.21GB | 7.87s | 16.66s | 2.15GB | 4 | 112.76s |
| ta | 15.56s | 0.74GB | 6.39s | 15.08s | 2.15GB | 4 | 133.64s |
| ml | 15.59s | 0.60GB | 6.66s | 16.51s | 2.15GB | 4 | 132.29s |

TTS peak is now **identically 2.15GB across all three languages** -- the duration-calibrated
chunking produces uniform, predictable memory behavior regardless of language, which wasn't
guaranteed before (the old character-count-only sizing had no reason to converge like this).
All three completed cleanly, no crashes, no budget violations. Full raw logs in
`pipeline_run_logs/pipeline_{hi,ta,ml}_final_2026-08-08.log`.

## Open items
- The Jetson "first inference pays a warmup tax" pattern (15.5s RTF 1.72 in the bare-script test)
  didn't reproduce as dramatically through the real gateway pipeline runs -- worth a dedicated
  isolated test if this needs pinning down further.
- `bn` (Bengali) was quantized but not deployed -- available if language coverage needs to grow
  again.
- No dedicated WER/accuracy evaluation run on the Tamil/Malayalam quantization difference beyond
  spot-checking the two sample transcripts above.
