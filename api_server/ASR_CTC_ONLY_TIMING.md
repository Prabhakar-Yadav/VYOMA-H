# ASR CTC-Only Load Fix — Measured Results

Generated: 2026-08-07 (real Jetson Orin numbers, `jetson-orin` / `vaultstackai` over Tailscale,
`nvpmodel` 15W mode, GPU devfreq observed at 306MHz/612MHz max, `schedutil` CPU governor)

## Background

`TIMING_RESULTS.md`'s ASR numbers (5.09s server-reported / 6.64s wall-clock) were measured on
the GB10 dev machine and explicitly flagged there as not-yet-validated for Jetson. Running the
same script on the actual Jetson Orin (this doc) surfaced real cold-load times of **22-47s**,
matching a live deployment observation of ~40s reloads — a ~6-8x gap from the dev-machine number,
not a regression.

Root-caused to `model_onnx.py` (the `trust_remote_code` class cached from
`ai4bharat/indic-conformer-600m-multilingual`): its `__init__` eagerly builds **29 separate model
artifacts** — `preprocessor` (torch.jit) + `encoder` + `ctc_decoder` + `rnnt_decoder` +
`joint_enc`/`joint_pred`/`joint_pre_net` + one `joint_post_net_<lang>` ONNX session **per each of
the 22 supported languages** — regardless of which `decoding=` mode is ever requested.
`asr_worker.py` always calls `decoding="ctc"` in production (`decoding="rnnt"` is only ever
exercised by the standalone comparison script, `dev/local_model_test/test_asr_memory.py`), so 26
of those 29 loads build real `ort.InferenceSession` objects — each paying its own CUDA-EP
session-creation overhead (graph parse, provider registration, CUDA context/kernel setup) — for a
decode path that's never taken.

This is **not** a checkpoint-size problem: the RNNT-side files (`rnnt_decoder.onnx` + all
`joint_*.onnx`) total 57MB against the shared encoder's ~2.4GB (confirmed directly against the
on-disk checkpoint) — trimming them saves ~2% of bytes read. The real cost is session *count*.

## The fix

`models/asr/ctc_only.py` — a trimmed clone of the cached `model_onnx.py` that builds only 3
artifacts (`preprocessor`, `encoder`, `ctc_decoder`) instead of 29. Same on-disk checkpoint, same
weights, same CTC decode logic (byte-for-byte copy of `_ctc_decode`/`compute_timestamps`, which
never touched the RNNT-side sessions anyway). Wired in via `IndicConformerASR(ctc_only=True)`
(the new default) in `model_loader.py`; pass `ctc_only=False` to get the original 29-session
model back (needed only for `decoding="rnnt"` comparisons).

**Correctness**: verified identical output to the full model on the same input, both on the dev
machine (`sample_audio/pipeline_inputs/q1_hi.wav`, byte-for-byte identical transcript) and on the
Jetson itself through the real gateway (`POST /asr/load` → `POST /asr/infer` with
`dev/local_model_test/audio_samples/asr_hi_payload.json`, returned `"भारत एक महान देश है"` —
coherent, correct Hindi).

## Real Jetson numbers — before vs. after (2 cold loads each, gateway lazy-spawn per load)

| | Load 1 (server / wall) | Load 2 (server / wall) | Unload |
|---|---|---|---|
| **Before** (29 sessions, `ctc_only=False`) | 22.426s / 25.900s | 40.863s / 46.761s | 0.658s |
| **After** (3 artifacts, `ctc_only=True`) | 24.521s / 28.003s | 15.562s / 21.179s | 0.605s |

A third, isolated real-`/asr/infer` run (correctness check above) loaded in **9.235s**
server-reported — the low end of what this fix makes achievable.

The worst-case load — the one that matched the live "~40s" observation — dropped from **46.8s to
21.2s wall-clock, more than 2x**. Load 1 stayed roughly flat between before/after; see "remaining
variance" below.

Peak RSS also dropped slightly: 0.844GB (before) → 0.777GB (after) — small, as expected, since
the trimmed sessions were individually tiny in file size (this was always a session-count fix,
not a memory-footprint fix).

## Remaining variance — not yet fixed, flagged for follow-up

Even after the fix, load time varies run-to-run (24.5s vs 15.6s, and a separate 9.2s run) far
more than the ~0.3s spread seen on the GB10 dev machine. Checked directly:

- **Not thermal**: `cpu-thermal`/`gpu-thermal` sat at 49°C during testing — well under any Orin
  throttle threshold.
- **Power-capped**: `nvpmodel` is in **15W mode** (`pmode:0000`), not MAXN. GPU devfreq showed
  **306MHz current vs. 612MHz max** (50%) at idle between loads.
- CPU governor is `schedutil` (dynamic, ramps from idle) rather than a fixed/performance
  governor.

Hypothesis: clocks settle back toward idle during the gap between calls under the 15W cap, and
`schedutil`/GPU devfreq's ramp-up latency on the next cold load is itself inconsistent. Not yet
tested: `sudo nvpmodel -m 2` (MAXN) and/or `sudo jetson_clocks` (pins clocks at max, disables
dynamic scaling) — device-wide, semi-persistent power/thermal profile change, so deliberately not
applied without explicit confirmation. Re-run this same script after that change to see if it
also flattens the variance.

**Update — a bigger, better-evidenced explanation found**: dropped the page cache directly
(`echo 3 | sudo tee /proc/sys/vm/drop_caches`, confirmed via `free -h`: buff/cache 2.5GB → 171MB)
and re-timed reading the real checkpoint files (the same 361 tensor files + `encoder.onnx` +
`ctc_decoder.onnx` this loader actually opens, 2.3GB total):

| | Time |
|---|---|
| Cold read (cache just dropped) | **28.391s** |
| Warm re-read (same files, immediately after) | 0.668s |
| Raw eMMC sequential throughput (`dd`, independent check) | 87.5 MB/s |

`2.3GB ÷ 87.5MB/s ≈ 26.9s` — matches the measured 28.4s cold read almost exactly. **This eMMC is
genuinely slow, and disk I/O is the single biggest lever on a truly cold load** — bigger than the
session-count fix above, and a better explanation for the 15.6s-47s run-to-run variance than power
mode: whichever test iteration's page cache happened to still hold the checkpoint's pages from a
recent prior run paid ~0.7s; whichever hit a partially-evicted cache paid up to ~28s more. A
typical NVMe SSD (1,500-3,500 MB/s sequential) is 17-40x this eMMC's measured throughput — if that
holds, the disk-bound portion of a cold load could drop from ~28s to roughly 1-2s, on top of (not
instead of) the CTC-only session-count fix. Untested: actually adding NVMe and re-measuring; the
15W power-mode hypothesis above is still plausible as a secondary contributor but unconfirmed and
likely smaller than this.

**Same eMMC bottleneck confirmed on NMT and TTS too** (same cold-cache-drop methodology,
2026-08-07): NMT (428MB, 19 files) cold-read **5.29s** vs 0.205s warm; TTS (833MB, 40 files)
cold-read **10.12s** vs 0.367s warm. Both line up with the same ~87.5MB/s eMMC throughput model
(428MB÷87.5≈4.9s, 833MB÷87.5≈9.5s) — this is a systemic device-storage bottleneck, not
ASR-specific. Important nuance: NVMe would shrink all three cold-reads to ~1-2s combined, but
each worker still pays its own ~8-9s `torch` import cost on every load (lazy-spawn = fresh
process per load, see `TIMING_RESULTS.md`'s `spawn overhead` column) — that's CPU-bound, not
disk-bound, so post-NVMe all three workers would likely converge toward a shared floor set by
that import cost rather than by checkpoint size. Going further than that floor would mean
revisiting the standing-pool-vs-lazy-spawn tradeoff (`load_balancer_plan.md`'s update log already
covers why the standing pool was abandoned), not another storage upgrade.

## Also still true from the original `TIMING_RESULTS.md` — and one correction

`torch` import costs ~8-10s on a cold cache on this Jetson (vs. a fraction of a second on GB10).
**Correction to an earlier claim in this doc**: this was first assumed to be pure CPU-bound
Python import cost, unaffected by storage speed. Direct measurement (2026-08-07, same
cache-drop methodology as above) shows that's wrong -- it's mostly the *same* eMMC bottleneck as
the model checkpoints:

| | Time |
|---|---|
| Cold `import torch` (cache just dropped) | 10.23s |
| Warm `import torch` (immediately after) | 2.53s |

torch's own shared libraries (`venv/lib/python3.10/site-packages/torch/lib/*.so`) total **433MB**
-- dominated by `libtorch_cpu.so` (206MB) and `libtorch_cuda.so` (193MB). `433MB ÷ 87.5MB/s ≈
4.95s` accounts for most of the ~7.7s cold/warm gap; the rest is dynamic-linking/relocation
overhead for `.so` files this large, which is CPU-bound but not the dominant term. **Practical
upshot: the NVMe fix above would also fix most of the torch-import tax**, not just the checkpoint
reads -- no separate fix needed for this specifically. `torch.cuda.is_available()` itself only
adds ~0.17s once torch is imported, confirmed directly -- CUDA init is not the bottleneck.

Separately, `LD_LIBRARY_PATH` must include the hand-installed `libcudss` archive
(`~/libcudss-linux-aarch64-0.8.0.10_cuda12-archive/lib`) for `torch.cuda` to work at all on this
device -- currently only set in `.bashrc` (interactive-shell-only); confirm the actual production
launch path (systemd/cron/boot) sources it too, or CUDA silently fails to init.
