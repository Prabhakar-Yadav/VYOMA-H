# Cross-Device Timing Results — GB10 (GX10) dev machine vs. Jetson Orin

Generated: 2026-08-07. Consolidates every real measurement taken across this investigation --
see `TIMING_RESULTS.md` (original GB10 numbers), `ASR_CTC_ONLY_TIMING.md` (the ASR session-count
fix + eMMC disk findings) for the narrative. This doc is the flat data reference across both
devices, plus NVMe-projected numbers and the ASR CPU-vs-GPU comparison.

**Devices**: "GX10" = this dev machine (NVIDIA GB10, unified CPU/GPU memory, no 8GB ceiling,
hostname `gx10-4cae`). "Jetson" = `jetson-orin`/`vaultstackai` over Tailscale, `nvpmodel` 15W
mode (not MAXN), eMMC rootfs (`/dev/mmcblk0p1`), 7.4GB usable RAM.

## 1. Cold-load wall-clock, current deployed code, both devices

| Worker | GX10 (dev, TIMING_RESULTS.md) | Jetson, current (this doc) |
|---|---|---|
| ASR (ctc_only=True, deployed) | 6.641s wall / 5.088s server | **9.2s – 28.0s** wall (see §2, wide variance) |
| NMT (unmodified) | 3.296s wall / 0.749s server | **7.1s – 23.3s** wall |
| TTS (unmodified) | 7.45s wall / 3.319s server | **11.3s – 31.8s** wall |

Jetson numbers are ranges, not single values, because run-to-run variance on this device is
real and large (see §4) -- driven mostly by page-cache warmth (eMMC is slow, §4) and secondarily
by GPU clock state (15W power cap, unconfirmed magnitude, see `ASR_CTC_ONLY_TIMING.md`).

## 2. ASR — before/after the CTC-only session fix (Jetson)

`ctc_only=True` is the default in `model_loader.py` as of this fix and **is what's currently
deployed on Jetson right now** -- if you run the gateway there today, this is the "after" row.

| | Load 1 | Load 2 | Unload |
|---|---|---|---|
| Before (29 ONNX sessions, `ctc_only=False`) | 22.4s server / 25.9s wall | 40.9s server / 46.8s wall | 0.66s |
| After (3 artifacts, `ctc_only=True`) | 24.5s server / 28.0s wall | 15.6s server / 21.2s wall | 0.60s |
| After, isolated correctness-check run | 9.2s server (single load) | -- | -- |
| After, cache fully primed (§3 methodology) | 16.4s server / 20.2s wall | -- | 0.56s |

Correctness: verified byte-identical CTC output vs. the full model, both on GX10
(`sample_audio/pipeline_inputs/q1_hi.wav`) and on Jetson through the real gateway
(`POST /asr/infer`, real Hindi payload → `"भारत एक महान देश है"`, coherent).

## 3. NVMe-projected numbers (cache fully primed before load — simulates near-zero disk latency)

Methodology: drop page cache, `cat` every file the worker's code path actually reads (torch's
`.so` libs + the full checkpoint) into page cache, then time a real load. This removes disk I/O
from the load path the same way NVMe would (NVMe doesn't make a cold read free, but its per-op
latency and throughput are close enough to a "warm cache" experience for this comparison to be a
reasonable proxy) -- **it does NOT remove ONNX Runtime's own CUDA session-build compute**, which
turned out to be the dominant remaining cost for both ASR and TTS (see §5).

| Worker | Cold (current, eMMC) | NVMe-projected (cache-primed) | What's left after NVMe |
|---|---|---|---|
| ASR | 46.8s wall (worst observed) | **20.2s wall** / 16.4s server | ONNX CUDA session build (encoder+ctc_decoder) |
| NMT | 23.3s wall | **12.5s wall** / 1.46s server | `transformers`/tokenizer import + torch (server-reported is tiny -- the 11s gap is spawn/import overhead, not disk) |
| TTS | 31.8s wall | **21.2s wall** / 17.5s server | ONNX/torch CUDA session build (17.5s is inside the model's own `load()`, not spawn overhead) |

**NVMe would not make loads "instant."** It removes disk-cold-cache spikes (the 40-47s
outliers) and gets things into a more consistent, lower range, but each worker still has its own
non-disk floor (CUDA session-build compute, `transformers` import, etc.) that's a separate
problem from storage speed.

## 4. Raw disk I/O findings (eMMC, `/dev/mmcblk0p1`, ~87.5MB/s measured sequential)

Methodology: `sync && echo 3 | sudo tee /proc/sys/vm/drop_caches`, confirmed via `free -h`
(`buff/cache` dropping to ~170MB each time), then time reading the exact files each worker's
`load()` touches.

| | Size / file count | Cold read | Warm re-read | Ratio |
|---|---|---|---|---|
| ASR checkpoint | 2.3GB / 361 files | 28.4s | 0.67s | 42x |
| TTS checkpoint | 833MB / 40 files | 10.1s | 0.37s | 27x |
| NMT checkpoint | 428MB / 19 files | 5.3s | 0.21s | 25x |
| torch `.so` libs | 433MB (libtorch_cpu 206MB + libtorch_cuda 193MB + others) | 10.2s | 2.5s | 4x |

All four line up with the same ~87.5MB/s eMMC throughput model (e.g. 428MB÷87.5≈4.9s ≈ measured
5.3s) -- confirms this is a systemic, single-root-cause storage bottleneck across every worker,
not anything ASR-specific. torch's own import is disk-bound too (see `ASR_CTC_ONLY_TIMING.md`'s
correction on this) -- initially mis-attributed as "CPU-bound, unaffected by storage" in an
earlier pass of this investigation; direct cold/warm measurement proved that wrong.

## 5. ASR: CPU-only vs. GPU (CUDA EP) — real measurement, not assumption

Question tested: since the ASR model's own encoder isn't huge, would forcing CPU-only execution
(`CUDA_VISIBLE_DEVICES=""`, zero code changes needed -- `model_onnx.py`/`ctc_only.py` already
fall back to `CPUExecutionProvider` when CUDA isn't visible) avoid the CUDA session-build cost
and be just as fast, or faster, given the memory savings? **Tested directly. Answer: no --
GPU wins on speed, CPU wins on memory. Real tradeoff, not a free win either way.**

| | Load | Transcribe (9.00s Hindi clip) | RTF | System-wide memory delta (`free -m`, ground truth) |
|---|---|---|---|---|
| **GPU (CUDA EP)** | 10.73s | 7.24s | **0.80** (faster than real-time) | 4.42GB |
| **CPU-only** | 18.14s | 9.93s | **1.10** (slower than real-time) | 2.20GB |

Cold-load comparison (separate runs, more variance, same direction): CPU-only cold load hit
**47.2s / 50.95s wall** -- worse than any GPU cold-load number observed. CPU-only warm-ish load
(11.96s / 15.39s) was comparable to GPU's better-case numbers, not clearly better.

**Recommendation: stay on GPU.** CPU-only's RTF>1 means transcription would fall behind
real-time for a live conversational agent -- the 2.2GB memory saving doesn't outweigh that for
this use case. CPU-only would only be worth revisiting if memory becomes the harder constraint
than latency (e.g. trying to keep ASR permanently resident -- see next section).

## 6. Correction: the orchestrator's memory accounting under-counts CUDA-loaded workers on Jetson

The worker `/status` endpoint's `rss_bytes`/`vram_bytes` (what `load_balancer_plan.md`'s
eviction rules budget against) reported ASR's peak footprint as **0.777-0.844GB** in GPU mode.
The real, ground-truth system-wide `free -m` delta for the same load+transcribe was **4.42GB** --
over 5x higher. `vram_bytes` reads `torch.cuda.memory_allocated()`, which only tracks memory
**PyTorch's own allocator** manages -- it misses onnxruntime's separately-managed CUDA memory
arena entirely (ASR and NMT both run their bulk compute through onnxruntime, not torch tensors,
so both report `vram_bytes: 0.0` regardless of real GPU memory use). TTS, which runs its
generation through torch directly, reports real nonzero `vram_bytes` (0.587GB) -- consistent
with this being an instrumentation gap specific to onnxruntime-backed workers, not a universal
bug.

**This means `load_balancer_plan.md`'s eviction/budget math has likely been working off
under-counted numbers for ASR (and possibly NMT) this whole time on real hardware.** Not yet
checked: whether NMT has the same real-vs-reported gap as ASR (both are onnxruntime-backed, so
likely yes, unconfirmed). This changes the earlier "could ASR stay always-resident instead of
being unloaded" analysis -- at a real ~4.4GB footprint (not 0.8GB), it does not fit alongside the
documented 7.79GB Agent+NMT+TTS worst case under any real budget. Fixing the `/status`
instrumentation itself (reading real system memory delta, or onnxruntime's own memory-arena
stats, instead of `torch.cuda.memory_allocated()`) is a separate, real piece of follow-up work
this investigation surfaced but did not fix.

## 7. Full orchestrated pipeline runs — real end-to-end, all three ASR-supported languages

`python test_orchestrated_pipeline.py --language <lang> --no-play` (real gateway, real
`MemoryOrchestrator`, real Ollama agent with tool-calling, real ASR/NMT/TTS, run from Jetson's
own `venv`), run back to back for hi (with `--with-image`, Q2 -- photo diagnosis), ml, and ta
(plain Q1, no photo). Full raw `[ORCH]`/`[PIPE]` logs saved in `pipeline_run_logs/` alongside
this doc. All three completed cleanly end to end -- coherent transcripts, coherent agent
answers, coherent back-translations, real `.wav` output written for each.

| Language | ASR ready | ASR infer | NMT ready (in) | Agent turn | NMT infer (out) | TTS infer | **Total turn** |
|---|---|---|---|---|---|---|---|
| hi (+image, Q2) | 48.74s | 15.59s | 24.16s | 152.26s (4 tool calls) | 8.87s | 11.43s | **268.08s** |
| ml (Q1) | 56.10s | 15.51s | 23.41s | 42.31s (1 tool call, no photo attached) | 12.03s | 15.67s | **172.66s** |
| ta (Q1) | 56.09s | 15.73s | 23.62s | 71.39s (2 tool calls) | 9.77s | 12.87s | **197.29s** |

**Important real-world finding, not visible in any isolated worker benchmark above: ASR's
"ready" time inside a real pipeline run (48.7-56.1s) is noticeably worse than any isolated
ASR-only measurement in §1-§2 (9.2-28.0s).** Root cause, visible directly in the `[ORCH]` log:
Rule 9 preloads the Agent (Ollama, `qwen3.5:2b`) in a background thread **concurrently** with
ASR's foreground load -- the two compete for this device's limited disk I/O, CPU, and GPU
bandwidth at the same time, and lose more to that contention than either costs in isolation.
This is a real, orchestrator-level effect that isolated single-worker timing (§1-§3) cannot
surface -- worth keeping in mind before trusting any isolated number as a proxy for real
pipeline latency.

Transcripts (spot-check, not exhaustive -- see the full logs for agent tool-call traces):
- **hi**: ASR → `"इस पौधे में क्या गड़बड़ है..."` → agent correctly identified cassava leaf symptoms via `analyze_photo` + 2 lookup tools → coherent Hindi answer.
- **ml**: ASR → `"ഉരുളക്കിഴങ്ങ് കീടങ്ങളിൽ നിന്നും..."` → agent noted no image attached, answered from general pesticide knowledge → coherent Malayalam answer.
- **ta**: ASR → `"உருளைக்கிழங்கு பூச்சிகள்..."` → agent called `query_entomologist` twice, answered from general + tool knowledge → coherent Tamil answer.

## 8. Memory-accounting fix — shipped, tested, and a real worst-case it uncovered

Fixed the Sec. 6 under-counting at the source: `worker_base.py` now measures each worker's
real footprint as a system-wide `psutil.virtual_memory().used` delta around its own `load()`
call (`system_mem_delta_bytes`, new field on `/status` and `/unload`), instead of trusting
`torch.cuda.memory_allocated()`/per-process RSS (which miss onnxruntime's CUDA memory arena on
Jetson's unified memory). `orchestrator.py`'s `snapshot()`/`_component_bytes()` and
`gateway.py`'s `/system/memory` both now prefer this field over the old rss+vram sum. Ollama's
agent/embedder tracking untouched (already accurate via its own subprocess self-report).

**Validated directly on Jetson**: loading ASR alone, the new `system_mem_delta_bytes` reported
**2.76GB** against an independently-measured real `free -m` delta of **~2.78-2.9GB** (two
separate cross-checks, both within ~5%) -- versus the old method's **0.78GB** for the exact same
load. Real, working fix, not just a theoretical one.

**What it uncovered, re-running the hi+image pipeline with the fix live**: at the real
Agent+ASR concurrent-load peak (Rule 9), the system reported **agent=1.31GB + asr=5.33GB =
6.64GB total -- 94.8% of the 7.0GB budget**, only 0.36GB of headroom. The *exact same moment* in
an earlier run (old accounting) reported total=1.97GB (28.2%). This gap is not cosmetic -- the
orchestrator's eviction rules make real load/evict decisions off this number, and were
operating with a 5x-blind-spot at the tightest point in the whole pipeline. This is a live,
previously-invisible near-the-ceiling risk, not a hypothetical one.

**Follow-up this surfaces, not yet done**: any budget number computed under the old accounting
(e.g. `load_balancer_plan.md`'s documented "7.79GB worst case" that triggered the original
standing-pool revert) needs re-deriving with this fix live before being trusted for further
decisions -- it was built on the same undercounting this section just corrected.

## 9. Soft-unload — tested directly, more promising than expected

Question raised: since Rule 9's concurrent Agent+ASR preload costs real time to contention (Sec.
7), could keeping ASR's *process* alive between turns (soft-unload: release the model, don't
kill the process) dodge that cost instead of fully killing+respawning every time? Two real
concerns going in -- (a) does `engine.unload()` even preserve anything worth keeping, since
onnxruntime's CUDA sessions get destroyed on `del self.model` either way, and (b) memory cost of
staying resident, given the standing-pool design was already tried and reverted once
(`load_balancer_plan.md`'s update log) for exactly this reason.

**Tested directly, same process, no gateway restart between calls:**

| | Time | System memory used |
|---|---|---|
| Load 1 (cold, fresh process) | 24.16s | 1344MB → 4126MB (+2782MB) |
| Soft-unload (process stays alive) | 0.51s | 4126MB → 1853MB (**+509MB residual**) |
| Load 2 (same process, after soft-unload) | **8.67s** (separate run: 5.98s) | 1853MB → 4179MB |

**Result: soft-unload reload (6-9s) is faster than even a fresh process with fully-primed
cache (16.4-20.2s, Sec. 3)** -- a real, additional lever, not just disk/session-count
overlap. Some of the "CUDA session-build" cost attributed to onnxruntime in Sec. 5/§2 is
actually a one-time "first CUDA touch in this process" tax that soft-unload genuinely
amortizes away by keeping the process (and its already-initialized CUDA context) alive.
Residual idle cost (~509MB) is a modest, real, quantifiable tax -- close to what
`load_balancer_plan.md` already measured for ASR's old standing-pool baseline (0.54GB), so the
CTC-only fix didn't change this specific number much (expected -- idle residual is dominated by
torch/onnxruntime being imported, not by how many sessions get built when actually loaded).

**Not yet done**: this is not wired into anything real. The gateway's `/unload` proxy currently
kills the process unconditionally regardless of `full=` (see its own code comment: "every
unload is a full process kill now"), and every eviction rule in `orchestrator.py` explicitly
requests a full kill. Actually using this would mean (1) making the gateway forward `full=false`
to the worker's real soft-unload path instead of short-circuiting to a kill, and (2) changing at
least Rule 6/9's ASR handling to soft-unload instead of kill -- a deliberate change revisiting
the previously-reverted standing-pool design, now with much better-understood numbers (0.5GB for
ASR alone, not 2.06GB for all three at once) than existed the first time. Worth doing, not done
yet -- and any decision here should be made against the re-derived worst-case from Sec. 8, not
the stale one.

## Open items not yet done

- `nvpmodel -m 2` (MAXN) / `jetson_clocks` test -- still not run, needs explicit go-ahead (device-wide power/thermal change).
- Whether NMT's `vram_bytes`/`rss_bytes` under-counts the same way ASR's does -- flagged, not measured.
- Actually adding NVMe hardware and re-measuring for real (everything in §3 is a cache-primed proxy, not a real NVMe device).
- Hindi-only (single-language) NeMo→ONNX conversion, scoped but not attempted.
