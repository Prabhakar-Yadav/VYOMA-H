# Jetson full recovery, 2026-08-12/13 — SSD→NVMe swap wiped everything

## What happened

The team swapped the Jetson's storage (SSD → NVMe). This wiped the OS entirely, not just
data — the device came back on a **new Tailscale IP** (100.117.13.115, old 100.118.21.46 is
dead) running **JetPack 7.2** (confirmed via web search: NVIDIA's real, current, officially
supported Orin release, June 2026 — not a broken/unsupported state), which is a genuinely
different platform from whatever the box ran before:

| | Old box | New box (post-recovery) |
|---|---|---|
| OS | Ubuntu 22.04-class (inferred) | Ubuntu 24.04.4 LTS |
| L4T / JetPack | R36-class / JetPack 6.x (inferred) | R39.2.1 / **JetPack 7.2** |
| CUDA | 12.x (inferred) | **13.2** |
| Python | 3.10.8 | **3.12.3** |
| Ollama | older | 0.32.9 |

The Python-version change alone (3.10.8 → 3.12.3) is the tell — that maps directly to the
Ubuntu 22.04→24.04 jump, which is what JetPack 6→7 actually is under the hood. This was **not**
a deliberate upgrade choice; it's just what the NVMe swap happened to land on. Confirmed via
real web search at the time (not assumed): JetPack 7.2 packages Jetson Linux 39.2, kernel 6.8,
CUDA Toolkit 13.0/13.2, Ubuntu 24.04 rootfs, targeting the Orin family specifically (not just
Thor) — a real, current, supported release, so there was no reason to fight it by trying to
reflash back to JetPack 6.

## Real consequence: three GPU-dependent packages needed re-sourcing

Everything CUDA-version-pinned that "just worked" on the old JetPack 6/CUDA 12 box needed
redoing for CUDA 13.2. Checked real availability for each before touching anything (not
assumed):

### torch — official wheels exist, straightforward
`pip install torch==2.13.0+cu132 torchvision==0.28.0+cu132 torchaudio --extra-index-url
https://download.pytorch.org/whl/cu132`. Confirmed via the real index listing
(`download.pytorch.org/whl/cu132/torch/`) before installing — `torch-2.13.0+cu132-cp312-cp312-
manylinux_2_28_aarch64.whl` genuinely exists. **Gotcha**: an unpinned `pip install --pre torch
...` (no exact version) made pip's resolver churn for 5+ minutes with almost no real download
progress (real, observed: `~/.cache/pip` barely grew) — pinning the exact version found on the
index made it a direct download instead. **Real verification** (not just import success): loaded
a real CUDA tensor, ran a real matmul on the GPU, got a correct result back.

One real, non-fatal warning worth knowing about: PyTorch's own compatibility table for this
release doesn't explicitly list compute capability 8.7 (Orin's) as one of the CCs this specific
build was compiled for — it very likely runs via PTX JIT-compilation rather than native sm_87
SASS kernels. Confirmed still functionally correct (real matmul succeeded), not confirmed
whether this costs real performance vs a hypothetical native-8.7 build — worth watching in a
real TTS speed comparison later, not re-litigated here.

### ctranslate2 (NMT) — no prebuilt wheel exists anywhere, built from source successfully
Real search confirmed: PyPI's aarch64 wheel is CPU-only (no GPU support ever, on any JetPack).
No CUDA-13.2-for-Orin prebuilt wheel exists in the wild. Built from source:

```bash
git clone --recursive https://github.com/OpenNMT/CTranslate2.git
cd CTranslate2 && mkdir build && cd build
cmake -DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc -DCMAKE_CUDA_ARCHITECTURES=87 \
      -DWITH_CUDA=ON -DWITH_CUDNN=ON -DWITH_MKL=OFF -DWITH_OPENBLAS=ON \
      -DOPENMP_RUNTIME=COMP -DCMAKE_BUILD_TYPE=Release ..
cmake --build . --config Release -j 2
sudo make install && sudo ldconfig
cd ../python && pip install -r install_requirements.txt
CTRANSLATE2_ROOT=/usr/local python setup.py bdist_wheel
pip install dist/ctranslate2-4.8.1-cp312-cp312-linux_aarch64.whl
```

Real host prerequisites needed first (not present by default): `build-essential cmake
libopenblas-dev cuda-toolkit-13-2 libcudnn9-dev-cuda-13 python3.12-dev`.

**Two real gotchas hit and fixed, not hypothetical:**
1. `CMake Error ... Intel OpenMP runtime libiomp5 not found` — CTranslate2's default OpenMP
   config wants Intel's MKL-associated `libiomp5`, which doesn't exist on ARM. Fix:
   `-DOPENMP_RUNTIME=COMP` (uses the compiler's own OpenMP, GNU libgomp here, already detected
   fine via `-fopenmp`).
2. Building the *Python bindings* separately failed with `fatal error: Python.h: No such file
   or directory` — needed `python3.12-dev` (headers only, separate from the interpreter
   package). The C++ library itself built fine without it; only the pybind11 bindings needed it.

A real, documented risk from a GitHub issue (`OpenNMT/CTranslate2#1771`, still open) was a build
failure compiling flash-attention's sm80-hardcoded CUDA kernels on a similar Orin device.
Checked the actual CMakeLists.txt before building: `WITH_FLASH_ATTN` defaults **OFF** in the
current release, so a normal build never touches those files at all — confirmed directly in the
real build log (no flash-attention `.cu` files ever compiled), not just assumed from the flag
default.

**Real verification, not just import success**: loaded the actual production IndicTrans2
checkpoint (`en-indic/ct2_int8_model`) with `device='cuda'`, ran a real translation
(`translate_batch`), got real output tokens back, no `cudaErrorNoKernelImageForDevice` (the
failure mode a wrong-architecture build would hit). Model load 0.73s, inference 0.27s.

### onnxruntime-gpu (ASR) — no prebuilt wheel anywhere, built from source (the long pole)
Real search confirmed this is a **known, structural gap**, not specific to us: `pip install
onnxruntime-gpu` only ships x86_64/Windows wheels — there has never been a PyPI aarch64 build,
on any JetPack. The community's own compatibility notes (from the build kit used here) list real
tested failures for every "looks-right" candidate: jetson-ai-lab's SBSA build targets Grace's
sm_90 not Orin's sm_87; a HuggingFace cuda13-sm121 build targets Thor/Blackwell; even an
ultralytics-hosted wheel with the right filename and provider list fails at actual runtime with
`cudaErrorNoKernelImageForDevice` — the lesson being that `get_available_providers()` is a
compile-time list, not proof a matching kernel actually exists for this GPU; only a real
inference call tells the truth.

Used `github.com/straga/jetson-jp7-onnxruntime` — a real, reproducible Docker-based build kit
specifically for JetPack 7.2 + Orin's sm_87, developed and verified on an Orin Nano Super (same
class of device as this one). Real prerequisites installed first (none present by default):
`docker.io`, `nvidia-container-toolkit` (+ `nvidia-ctk runtime configure --runtime=docker` +
restart docker), confirmed real GPU passthrough into a container via `docker run --runtime=nvidia
--gpus all ubuntu:24.04 nvidia-smi` before trusting the build to use the GPU at all.

```bash
git clone https://github.com/straga/jetson-jp7-onnxruntime.git
cd jetson-jp7-onnxruntime && make all   # base image -> ort compile -> smoke test
```

Real, honest time cost: `make base` (assembling the CUDA13.2+TensorRT10.16 base image) took
roughly 30-45 min, dominated by downloading TensorRT's dev packages (several GB, including a
single 2.3GB `libnvinfer-dev` file). `make ort` (the actual onnxruntime compile) is the real long
pole — this doc's own build kit README states ~4 hours, memory-bound not CPU-bound (confirmed
`--parallel 3`, not full core count, in the real `build.py` invocation), 16GB+ swap recommended
(this device has 31GB configured, real headroom confirmed via `free -h`/`tegrastats` throughout).

**Real completion**: `make ort` finished after ~4 hours total (04:37→08:37), matching the kit's
own README estimate closely. The compile's own pace was informative: 0%→65% took ~49min, but
65%→94% (entirely `contrib_ops/cuda/bert/flash_attention/` — dozens of per-headdim × per-dtype
× fwd/fwd_split CUTLASS template instantiations) took ~1h43min alone — by far the single slowest
section, individual files sometimes taking 5-10min each even with `--parallel 3`. Confirmed
throughout via live process inspection (not just log-tail trust): real `ptxas -arch sm_87` and
`cicc` child processes actively burning 85-99% CPU, `--generate-code=arch=compute_87,code=[sm_87]`
present on every real nvcc invocation, RAM/swap never under pressure (peak ~1.6GB/7.5GB used, no
swap thrashing). `make smoke` (run automatically as part of `make all`) passed for real, not just
`get_available_providers()`: `test_cuda_ep.py` → "OK: CUDA EP ran on GPU", `test_providers.py` →
"OK: ort 1.23.0, providers=['TensorrtExecutionProvider','CUDAExecutionProvider',
'CPUExecutionProvider']", `test_trt_ep.py` → "OK: TRT EP session ran" — all three via a real
`InferenceSession.run()`, not import-level checks. Wheel:
`onnxruntime_gpu-1.23.0-cp312-cp312-linux_aarch64.whl` (100MB), filename confirms `cp312`/
`aarch64` as required.

**Installing the wheel surfaced a real, separate venv-copy bug**: `~/gramsahayak/venv` (created
via `cp -a` from `~/dev-local-test/.../gramsahayak/venv` to avoid a second multi-hour GPU-stack
build — see above) had its own `bin/pip`'s shebang still pointing at the *other* venv's
`bin/python`. `venv/bin/pip install <wheel>` reported success, but silently installed into the
wrong venv's site-packages — `import onnxruntime` in the real `gramsahayak/venv` then failed with
`ModuleNotFoundError` despite pip's own "Successfully installed" message moments earlier. This is
exactly `run_app.md`'s already-documented gotcha #5, now confirmed to actually bite in practice,
not just a theoretical risk. Fix: `venv/bin/python -m pip install --force-reinstall --no-deps
pip` (repairs the shebang, since `python -m pip` can't be fooled by a stale shebang), then
reinstall via `venv/bin/python -m pip install <wheel>`. Applied to both `~/gramsahayak/venv` and
`~/dev-local-test/.../gramsahayak/venv`.

**Real, load-bearing discovery: ASR's actual production code path was hardcoded CPU-only, and
that assumption doesn't hold on Jetson.** `asr_worker.py` (the real worker `orchestrator.py`
talks to) uses `QuantizedMultiLangASR` → `IndicConformerASR`
(`models/asr/indic_quantized_asr.py`), whose `load()` hardcoded
`providers=['CPUExecutionProvider']` — a *deliberate* 2026-08-07 design decision per that file's
own docstring, based on "CPU is fast enough (RTF 0.17-0.28 observed)" **measured on GX10's CPU**.
Real measurement on the actual Jetson Orin CPU: **RTF 3.83** (34.5s to transcribe a 9s clip) —
14-22x slower than the GX10 baseline the decision was built on, and a severe real per-turn latency
problem for a voice assistant. The whole reason `onnxruntime-gpu` was built at all was for this
component, so this was worth fixing now that it exists: same real model, same real audio, CUDA
measured at **RTF ~0.03-0.05** (~100-150x faster), transcript byte-identical either way.

Fix applied to `models/asr/indic_quantized_asr.py` (GX10 canonical copy + both Jetson checkouts):
`load()` now picks `['CUDAExecutionProvider','CPUExecutionProvider']` when
`'CUDAExecutionProvider' in ort.get_available_providers()`, else stays `['CPUExecutionProvider']`
— no platform-sniffing needed, since GX10 only ever installs plain `onnxruntime` (not `-gpu`) per
`requirements.txt`, so the same code naturally stays CPU-only there. Two real one-time warmup
costs were found and folded into `load()` (paid once at load, before the assistant reports ready,
instead of on a real user's first question):
1. **librosa's own first-call JIT cost** (numba-compiling its DSP code) — confirmed directly: a
   fresh process's first `melspectrogram()` call took 3.2s, second call 0.02s. This is completely
   unrelated to onnxruntime/CUDA and hits the CPU-only path (GX10) exactly as hard — an
   unconditional warmup now runs for every provider.
2. CUDA's own first-call kernel-selection cost on top of session creation — a throwaway
   synthetic-tensor `sess.run()`, CUDA-only.

**Real memory-growth finding from testing longer audio** (prompted by a direct question): a 66s
real audio clip (9 files concatenated + resampled via `sox`) grew CUDA's memory arena by an
additional +0.7-1.3GB *on top of* the base session's +1.4-2.1GB, and — confirmed by running
short clips immediately after — that growth is **permanently held** for the process's lifetime
(ONNX Runtime's CUDA arena allocator keeps its high-water mark, doesn't return memory to the OS).
Investigated whether this is a real production risk: `worker_base.py`'s own docstring confirms
`?full=true` unload (`orchestrator.py`'s `_unload()` default) is "a gateway-triggered
**kill+respawn**... a *guaranteed* memory reclaim", and `config.py`'s
`COMPLEMENTARY_PAIRS = [("asr","tts")]` means ASR gets evicted (full process kill+respawn) via
Rule 1 on essentially every real turn, right after transcribing, to make room for TTS. So this
growth cannot accumulate across turns in real operation — worst case is elevated *for that one
turn* (proportional to that question's real length), then unconditionally reset by the existing
ASR→TTS handoff before the next turn starts. No code change made for this — the existing
eviction design already solves it more reliably than an ONNX Runtime arena-shrinkage config
would have.

## Real gaps found and fixed along the way (unrelated to the GPU platform jump)

- **rsync silently dropped the real model weights the first time.** `models/checkpoints/`
  contains symlinks to files *outside* the gramsahayak tree (e.g.
  `~/Downloads/nmt_trans/.../indicTrans2/checkpoints`, a different repo's `models/checkpoints`
  dir). Plain `rsync -a` does **not** follow symlinks by default — it copies the link itself, not
  the target's content. Real, serious miss: the first sync left `models/` looking small (a few
  hundred KB of symlink files) while claiming success. Fix: `rsync -avL` (`--copy-links`,
  dereference and copy real file content). Real size behind those links: ~1.83GB the plain sync
  had completely skipped.
- **`datasets/weather/` had ~2.5GB of build-only files not needed at runtime** — `cache/` (NASA
  POWER API response cache, 542MB), `weather_data_csv/` (1.6GB raw source CSVs),
  `weather_data/` (324MB intermediate). Only `full_weather.sqlite` (2.8GB) and the small
  `pincode_*`/`grid_cells.csv` lookup files are actually read at runtime (confirmed by checking
  what `datasets/weather/DEPLOYMENT.md` and the weather tools actually load). Excluded the three
  build-only directories from the real sync.
- Similarly excluded `sample_audio/pipeline_outputs/`, `audio-results/`,
  `sample_outputfromjetson/`, `api_server/pipeline_run_logs/` — old test-run *outputs*, not
  source data, regenerated fresh by any real test run, never read by the app itself.
- **`streamlit` and `parler-tts`'s transitive deps have a real, unresolvable protobuf conflict**
  on this Python/dep combination (streamlit wants `protobuf>=5.26`, `descript-audiotools`
  wants `<5.0`). Streamlit is explicitly optional per its own comment in `requirements.txt`
  ("dev/monitoring only, not needed for the pipeline itself") — dropped from this device's
  install rather than chasing a fix for a tool that isn't part of the real pipeline.
- **`pyaudio` needs `portaudio19-dev`** (the C headers) to build its wheel — not installed by
  default. Real, standard, quick fix.
- Ollama had the **wrong model already pulled** (`qwen3:4b`, not `qwen3.5:2b` — presumably from
  someone's earlier manual recovery attempt before this session started). Removed it, pulled the
  correct `qwen3.5:2b` + `granite-embedding:30m` (the exact pair validated all through tonight's
  earlier session).
- `~/gramsahayak` (the real `GRAMSAHAYAK_DIR` default, what `pocketinfer-service` actually runs
  against) needs its **own** venv, separate from `~/dev-local-test/.../gramsahayak`'s — mirroring
  code with `rsync --exclude=venv` (correct, code should stay in sync) left it with *no* venv at
  all the first time. Fix: once the dev-local-test venv had the full GPU stack built and verified,
  a plain local `cp -a` of the whole venv directory into `~/gramsahayak/venv` worked cleanly and
  avoided repeating the ~5-hour build a second time — confirmed the copied venv's `torch`/
  `ctranslate2` still correctly detect CUDA after the copy (venvs invoked directly via their own
  `bin/python3` path, not `source`-activated, aren't sensitive to being moved).
- `README.md`'s setup instructions still say `python3.10 -m venv venv` — now stale for this
  recovered device (3.12). Left as-is pending a proper doc pass (not urgent — the venv is already
  correctly created; this only matters if someone blindly follows the README on a fresh clone).

## Real state as of this writing

- `~/gramsahayak` and `~/dev-local-test/vyoma-hackathon-bhashini/gramsahayak`: code in sync,
  RAG DB checksum-verified identical to GX10's copy, real model checkpoint weights present
  (symlinks properly dereferenced this time), zero broken symlinks (verified via `find -xtype l`).
- `suno-sutra-sw` / `suno-sutra-hw`: fresh clones from `github.com/currentai-org/...`, git-lfs
  content pulled correctly on initial clone (no manual `git lfs pull` fix needed this time, unlike
  the earlier session on the old box).
- torch: real GPU verified. ctranslate2: real GPU verified. onnxruntime-gpu: **built, installed
  into both venvs, real GPU inference verified** (CUDA + TensorRT providers, real transcription
  correct on 9s and 66s real audio). ASR's provider selection is now device-conditional (CUDA on
  Jetson, CPU on GX10) — see the real RTF numbers and the memory-growth finding above.
- pocketinfer's own venv: built, real hardware-layer board auto-detection confirmed working
  (`PocketInferDevboardUI`, matching the real EEPROM-identified board).
- Systemd unit staged at `~/suno-sutra-sw/python/pocketinfer.service` with this device's real
  paths (user `jetson`, not the generic `ubuntu` template) — **not installed/enabled**, matching
  the earlier session's deliberate choice to leave that as an explicit step, not something a
  recovery does automatically.
- Not yet done: full end-to-end multi-turn validation run (real ASR→agent/RAG→NMT→TTS pipeline,
  multiple languages, via `pocketinfer-service --dummy-board` or `test_orchestrated_pipeline.py`).
- RAG (G1/G2 hybrid BM25+sqlite-vec retrieval) and the weather DB/tools (`get_weather_data`,
  `query_spray_window`) were also verified for real on this device while the onnxruntime-gpu build
  ran in the background — both already came along for free via the recovery rsync (current GX10
  tree, not a stale snapshot) and needed no fixes.

## Continuation, 2026-08-13/14 — ASR root-cause fix, NMT/TTS fixes, and a real NVIDIA platform bug

### ASR: real root cause found and fixed

Symptom: every real ASR call through the actual pipeline (both `pocketinfer-service` and
`test_orchestrated_pipeline.py`, independently) took 8-33s, while the exact same model/audio
called directly in an isolated script was always fast (RTF 0.03-0.05, 0.2-0.7s). Spent a long
investigation ruling out memory pressure, background-process contamination, network/HTTP
overhead, CPU nice/cgroup restriction, GPU-activity adjacency to a real Ollama generation, and
`onnxruntime`'s `EXHAUSTIVE` conv-algorithm search (real, partial contributor — fixed separately,
see below) before finding the actual cause.

**Root cause**: `orchestrator.py`'s `run_asr()` called `self._load("asr", reason=...)` without
passing `language=`. `_load()`'s own `language` parameter defaults to `None`, so
`QuantizedMultiLangASR.load(None)` only marked the engine "ready" (a fast no-op) instead of
eagerly building the real per-language CUDA session — that ~6-12s real cost was silently
deferred to the first `/infer` call instead, disguised as transcription time, every single turn
(since ASR gets process-killed and respawned fresh each turn). `preload_asr()` (Rule 10's
golden-window preload, used for turns 2+) already had this right; only the two fallback/cold-start
`_load()` calls inside `run_asr()` itself were missing it.

**Fix**: added `language=language` to both call sites. Verified directly: `asr infer` dropped
from 8.28s to 0.82s using the real `MemoryOrchestrator` class under identical conditions. Also
fixed ASR's memory attribution as a side effect — `asr=X.XXGB` now shows correctly in snapshot
lines for the first time (was always `0.00GB` before, same underlying bug).

Secondary, real fix applied at the same time: `models/asr/indic_quantized_asr.py`'s
`CUDAExecutionProvider` now explicitly sets `cudnn_conv_algo_search="HEURISTIC"` (was unset,
defaulting to onnxruntime's own `"EXHAUSTIVE"`, which times every candidate conv algorithm per
new input shape -- real audio is a different length every turn). Confirmed real, partial
contributor on its own (33.11s -> 11.01s on one repeatable test) before the `language=` fix was
found; kept as a genuine improvement.

**Known follow-on, not yet fixed**: fixing the accounting exposed that Rule 10's async ASR
preload can now genuinely fail under this device's real thin memory margins (a real
`cudaErrorMemoryAllocation` OOM was hit once), since ASR's real ~1.5GB cost is no longer masked
-- the preload now has to actually find that headroom, and sometimes can't. The app recovers
gracefully (falls back to a synchronous reload) but that fallback still pays close to the full
original cost. This is the next real thing to fix, separate from tonight's core fix.

### NMT: CUDA + batching (see also RAG-BUILD-LOG.md's own NMT section)

`NMTEngine` now auto-detects real CUDA support via `ctranslate2.get_cuda_device_count()` (was
hardcoded `device="cpu"`, a stale workaround for a since-superseded PyPI-wheel limitation).
`infer_long()` now batches all paragraphs of a real multi-paragraph answer through one real
`translate_batch()` call instead of one call per paragraph. Combined effect, verified directly
on this Jetson: a real 1934-char/7-paragraph EN->hi answer went from 32.34s (CPU, sequential) to
1.24s (CUDA, batched) -- CUDA mode also uses *less* real memory (858MB vs 2.3GB), not a
speed/memory tradeoff.

### TTS: peak-prediction formula fixed (not a raw-speed fix)

`_predict_tts_peak_bytes()`'s old linear-in-text-length formula (calibrated from two early,
pre-saturation data points) was producing real, false alarms -- a genuine 2042-char answer
predicted a fabricated "projected-at-peak=14.39GB vs budget=7.0GB". Real isolated measurement on
this Jetson (matching production's exact chunking behavior) showed the true behavior: memory
growth saturates almost immediately per language (~650MB) and stays flat regardless of answer
length. Rewrote the formula to match. Also fixed a separate bug in the same code path:
`run_tts()`'s live "observed peak" log was sampling whole-system total memory but comparing it
against a TTS-isolated prediction -- now correctly isolates growth-above-steady before comparing.

**TTS's own raw synthesis speed was not a focus of these fixes and is unchanged** -- see current
numbers below.

### Real NVIDIA platform bug found (not our code): NvMap post-security-patch memory restriction

The `NvMapMemAllocInternalTagged failed: error 12` / `cudaErrorMemoryAllocation` errors seen in
real crash logs this session (both tonight and the original 2026-08-12 recovery) are a
**confirmed NVIDIA-side regression**, not a bug in this project. Per NVIDIA staff on their own
developer forum (thread: "Intermittent NvMapMemAlloc error 12 and CUDA allocator crash during
PyTorch inference on Jetson Orin Nano"), a recent JetPack security patch (fixing CVE-2025-33182
and CVE-2025-33177) made the NvMap kernel driver more conservative about memory allocation --
the patch "adds a mechanism to prevent the allocation from going into the OOM path", which as a
side effect "led to some limitations in the allocable memory". Ollama is explicitly named in the
same thread as hitting the identical error, confirming it's not framework-specific.

Affected transitions named in that thread: r36.4.4->r36.4.7, r38.2.1->r38.2.2, r35.6.2->r35.6.3.
This device is on **R39.2.1** (dated 2026-08-07) -- newer than those, but since the CVEs predate
this build, the same conservative-allocation behavior is very likely baked in here too, not
something this recovery introduced. No fix has been released by NVIDIA as of that thread's most
recent activity; status is "under investigation". Suggested partial mitigations from the thread
(TensorRT conversion, power-mode tuning, lower precision/batch size, explicit
`torch.cuda.empty_cache()`) -- this project already does versions of several of these (int8
quantization throughout, `tts_worker.py`'s `_release_chunk_memory()` already calls
`empty_cache()` per chunk).

Practical implication confirmed by direct testing (not assumed): keeping Agent+Embedder+ASR+NMT
all resident simultaneously (skipping the orchestrator's eviction policy, to avoid the repeated
CUDA-context-churn this restriction seems to interact badly with) was tried directly and made
things *worse*, not better -- real swap usage hit 2.17GB with just those four loaded together,
before TTS was even added. The orchestrator's aggressive evict-when-not-needed design is
confirmed to be the correct tradeoff for this device's real memory budget, not over-caution.

### Current real timing, this session (post-fixes)

| Component | Load (cold) | Infer | Notes |
|---|---|---|---|
| ASR | ~6-12s (real CUDA session build, now honestly attributed) | **0.2-0.8s** when Rule 10's preload succeeds; 5.6-10.9s when it falls back to a synchronous reload (see follow-on above) |
| NMT | ~5-11s first cold load, then resident/fast | hi->EN: 0.5-1.6s. EN->hi: 0.5-2.5s (was 26s+ before tonight's CUDA+batching fix) |
| TTS | ~8.7-11.9s (evicted+reloaded fresh most turns, Rule 1 complementary-to-ASR) | ~8.9-10.5s real synthesis (unchanged by tonight's fixes -- these were accounting fixes, not speed work) |

Real memory margins remain thin throughout a live multi-turn session (`real_avail` regularly
0.05-0.3GB even after all of tonight's fixes) -- this is now understood to be a combination of
(a) this device's genuinely tight real budget for this component set, confirmed via the
all-resident test above, and (b) the NvMap platform restriction described above, not a
remaining bug in this project's own accounting.

## Continuation, 2026-08-14 (Canada daytime) — TTS preload double bug, Ollama tuning

### TTS: real preload was completely non-functional in production (two stacked bugs)

Found via a direct user question about TTS's own real `load`+`infer` cost (~9s+~9s, ~17-18.5s
total per turn, every turn). Same class of bug as the ASR fix above, but two layers deep:

1. **The real production app never called `orch.preload_tts()` at all.** Rule 5's whole design
   (see `run_agent()`'s own docstring) is that the caller must explicitly call
   `preload_tts(language=...)` right after `run_agent()` returns, to overlap TTS's ~8-12s cold
   load with the NMT-out stage's own downtime. `test_orchestrated_pipeline.py` already did
   this correctly; `gramsahayak_app.py` (the real app) never did. Every real turn paid TTS's
   full load cost inline at the TTS stage instead. Fixed: added the missing call.
2. **Once added, `preload_tts()`'s own headroom check rejected every real attempt anyway** --
   it compared real available memory against `tts_steady` (1.47GB, the OLDER eager-all-4-
   languages figure), not the real ~0.11-0.15GB single-language lazy-load cost. Observed real
   available memory at the check point (0.59/1.25/1.34GB) was comfortably enough for the real
   cost every time, but nowhere near the stale 1.47GB threshold. Fixed: added a new
   `tts_single_language` config key (250MB, real margin over the measured 0.108GB GX10 /
   0.122GB Jetson figures) and switched the check to use it.

**Real, verified result after both fixes**: the preload now genuinely starts (confirmed no more
"skipping tts preload" lines) and the TTS stage now shows "waited N.NNs for tts's async
preload to finish" instead of a full cold load -- a real but *partial* improvement (observed
~6.53s wait vs ~8-9s full load, so ~2-3s saved per turn, not the full ~9s). Root cause of the
partial-only benefit: the preload starts right after `run_agent()` returns, and the real
available overlap window (NMT-out) is now only ~0.5-2.5s (thanks to this session's earlier
NMT-CUDA fix) -- much shorter than TTS's own ~8-9s load, so most of the load still has to be
waited for synchronously, just now correctly reported as a wait on an in-progress preload
rather than a cold load from scratch. Directly tested (not assumed) that NMT-on-CUDA doesn't
reintroduce the severe Agent+TTS-style GPU contention this design was built to avoid: NMT
concurrent with a TTS load showed real but mild slowdown (0.53s solo -> 3.54s concurrent),
total wall-clock for both running together still bounded by TTS's own load time (8.60s) -- a
net win, just not a full one. Getting the full benefit would mean starting the preload earlier
(during the agent's own generation, which is long enough to fully hide it) -- but that's
specifically the window already confirmed to cause severe contention; not attempted tonight,
flagged as a real, deeper architectural question for later.

### Ollama/llama.cpp tuning: flash attention + KV-cache quantization

Real, confirmed gap on this freshly-recovered device: `/etc/systemd/system/ollama.service` had
**no** `OLLAMA_FLASH_ATTENTION` or `OLLAMA_KV_CACHE_TYPE` set at all (only `PATH`) -- whatever
tuning existed on the device before the SSD->NVMe wipe didn't carry over. Backed up the
original file (`ollama.service.bak-2026-08-14`) before changing anything.

Applied and verified live in the real `llama-server` process command line (`--cache-type-k
q8_0 --cache-type-v q8_0 --flash-attn on`):
```
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_KV_CACHE_TYPE=q8_0"
```

**Real, honest result**: negligible memory change for this specific model (2.66GB VRAM after
vs 2.56GB before -- essentially flat, not the "~halves KV-cache memory" some general Ollama
tuning guides advertise). Model-weight quantization (this model's own Q8_0 GGUF format) and
KV-cache quantization (this runtime setting) are independent axes -- for a small 2.3B-parameter
model like `qwen3.5:2b`, model weights dominate the real footprint far more than the KV-cache
does, so quantizing just the KV-cache doesn't move the total much here. The claim is real, it
just applies more to larger models or much longer contexts where KV-cache is a bigger fraction
of the total. Kept anyway -- zero real downside (well-documented negligible quality cost,
flash-attention now explicit rather than relying on Ollama's own "auto" default).

**q4_0 tested directly and reverted, not kept.** Real measurement: RSS 4.34GB (q4_0) vs 4.52GB
(q8_0) -- a real but small ~180MB difference, small enough it could be within normal
measurement noise. A single real tool-calling test looked correct (well-formed JSON, sensible
reasoning) under q4_0, but one test isn't enough evidence to accept q4_0's real, documented
*"larger, measurable"* quality cost (vs q8_0's negligible one) for an uncertain, marginal
memory gain -- especially on a real farmer-facing agricultural advisory system where a subtly
degraded tool-calling/reasoning quality compounding over a long conversation matters more than
~180MB. **Decision: keep q8_0. q4_0 is confirmed available and working as a real fallback
option if a future, more memory-desperate situation ever calls for it** -- to re-apply: edit
`/etc/systemd/system/ollama.service`, change `OLLAMA_KV_CACHE_TYPE=q8_0` to `q4_0`,
`sudo systemctl daemon-reload && sudo systemctl restart ollama`. Re-verify tool-calling quality
carefully (not just memory) before trusting it in real use if this is ever revisited.
