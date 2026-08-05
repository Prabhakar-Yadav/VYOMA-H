# Offline speech pipeline — Krishi advisory device

Voice in, voice out, entirely offline:

```
farmer speaks  ->  ASR  ->  NMT (hi->en)  ->  RAG  ->  NMT (en->hi)  ->  TTS  ->  device speaks
```

Retrieval only ever sees English. The RAG is a separate component and lives on
a different branch — see [Getting the RAG](#getting-the-rag) below.

Everything here was measured on **40 real farmer recordings** from the
DigiGreen Agri STT benchmark, not on synthetic text.

---

## What we ended up using, and why

| stage | model | why this one |
|---|---|---|
| **ASR** | `ai4bharat/indic-conformer-600m-multilingual`, **int8**, **RNNT**, **CPU** | best of 8 configurations tested — see [Choosing the ASR](#choosing-the-asr) |
| **NMT** | IndicTrans2 distilled 200M, CTranslate2 int8, both directions | already int8; 452 MB per direction |
| **TTS** | `facebook/mms-tts-hin` (VITS, 145 MB) | smallest and fastest of five engines tried, 18 Indian languages |
| **RAG** | `krishi-rag` on branch `plant-disease-rag` | grounded, refuses to invent a dose |

### Headline numbers

| | value |
|---|---|
| **peak memory, whole pipeline** | **2234 MB** (1829 MB RAM + 405 MB GPU) |
| ASR word error | **25.9%** |
| ASR character error | **14.1%** |
| per question, models resident | **1.97 s** |
| per question, load/unload | 18.9 s |

Peak is the number that matters on a Jetson. See
[Memory on the Jetson](#memory-on-the-jetson).

---

## Quick start on another PC

Tested on Ubuntu 24.04 with Python 3.12 and an NVIDIA GPU. A GPU is **not**
required — the whole pipeline runs on CPU, just slower.

### 1. Get the code

```bash
git clone https://github.com/vaultstack-ai/vyoma-hackathon-bhashini.git
cd vyoma-hackathon-bhashini
git checkout <this-branch>
```

### 2. Environment

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip

# torch: pick the CUDA build that matches your driver, or the CPU build
.venv/bin/pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu130

.venv/bin/pip install \
  onnxruntime-gpu fastembed ctranslate2 rank_bm25 \
  soundfile jiwer scipy numpy pyyaml nltk sentencepiece \
  "transformers==4.46.1" indic-nlp-library==0.92 sacremoses==0.1.1 \
  mosestokenizer==1.2.1 sacrebleu regex huggingface_hub

.venv/bin/python -c "import nltk; [nltk.download(p, quiet=True) for p in \
  ('punkt','punkt_tab','averaged_perceptron_tagger','averaged_perceptron_tagger_eng','cmudict')]"
```

> **onnxruntime gotcha.** `fastembed` pulls in the CPU `onnxruntime`, which
> silently shadows `onnxruntime-gpu` when both are installed, and the ASR then
> runs on CPU while you believe it is on the GPU. If
> `ort.get_available_providers()` does not list `CUDAExecutionProvider`:
> ```bash
> .venv/bin/pip uninstall -y onnxruntime
> .venv/bin/pip install --force-reinstall --no-deps onnxruntime-gpu
> ```
> The plain uninstall also breaks the GPU build, because both packages share
> one module directory — the force-reinstall is what repairs it.

### 3. Models — not in git, download them

Model weights are deliberately **not** committed. Several exceed GitHub's
100 MB hard limit (`encoder.onnx.data` alone is 838 MB), so the push would be
rejected.

```bash
# ASR - IndicConformer 600M (2.4 GB)
.venv/bin/huggingface-cli download ai4bharat/indic-conformer-600m-multilingual \
  --local-dir pipeline/models/ai4bharat/indic-conformer-600m-multilingual

# VERIFY IT. This is not optional.
.venv/bin/python pipeline/models/verify_asr.py
```

> **Always run `verify_asr.py`.** The first download reported "403/403 files"
> and was wrong: 52 files were missing or truncated, because the counter
> counted *attempts*, and `curl -C -` resumes a partial file into a
> permanently partial file. The failures surfaced much later as confusing
> errors deep inside model loading. `verify_asr.py` asks the repo for the true
> size of every file and re-fetches anything that does not match.

```bash
# int8 ASR - built here, not downloaded. ~40 s.
.venv/bin/python pipeline/models/quantise_asr.py

# NMT - IndicTrans2 distilled, CTranslate2 int8
#   place under pipeline/models/nmt/indicTrans2/checkpoints/{indic-en,en-indic}/ct2_int8_model

# TTS - downloads itself on first use, 145 MB per language
```

### 4. Run it

```bash
# resident: all models stay loaded, fastest
.venv/bin/python pipeline/results/run_full.py \
    --config myrun --asr int8 --tts mms

# 3 cases only, to check the setup
.venv/bin/python pipeline/results/run_full.py \
    --config smoke --asr int8 --tts mms --only 1 2 3

# process-isolated: each stage loads, works and exits. Lowest peak memory.
.venv/bin/python pipeline/chain_batch.py
```

Results land in `pipeline/results/<config>/`, one folder per question:

| file | contents |
|---|---|
| `01_input.ogg` | the farmer's recording |
| `02_asr.txt` | what the ASR heard |
| `03_nmt_en.txt` | English the RAG receives |
| `04_rag.json` | the RAG's decision |
| `05_answer_en.txt` | the answer, in English |
| `06_nmt_back.txt` | the answer, back in Hindi |
| `07_output.wav` | **what the device says out loud** |

---

## Getting the RAG

The pipeline expects `krishi-rag/` **beside** the `pipeline/` folder. It is
maintained on a different branch:

**https://github.com/vaultstack-ai/vyoma-hackathon-bhashini/tree/plant-disease-rag/krishi-rag**

```bash
git worktree add ../rag plant-disease-rag       # or:
git checkout plant-disease-rag -- krishi-rag

# build its index once (~30 s)
cd krishi-rag && ../.venv/bin/python src/cli.py build

# safety suites - these must pass before shipping anything
../.venv/bin/python src/cli.py evalall
```

`run_full.py` looks for `krishi-rag/` first beside the repo root and then
beside `pipeline/`, so either layout works.

---

## Running on the Jetson Orin Nano

The Orin has **8 GB of unified memory**: one pool shared by the OS, the CPU
process and the GPU. There is no separate VRAM. After the OS, roughly
**6–6.5 GB** is usable.

**This means a VRAM-only figure is meaningless here.** Always add GPU and host
memory together. Reporting "713 MB GPU" would suggest 7 GB of headroom that
does not exist.

### Measure the device first

```bash
free -m                  # what the OS actually leaves you
tegrastats               # live unified memory use
```

Nobody has yet measured real Orin headroom — the 6.5 GB above is an
assumption, and every budget below depends on it.

### Use the process-isolated runner

```bash
.venv/bin/python pipeline/chain_batch.py
```

Each stage loads, does its work and exits. **Peak becomes the largest single
stage instead of the sum**, because a process that exits returns memory to the
OS. In-process unloading does **not** do this — measured, `del` plus
`empty_cache()` returned pages to the allocator, raised RSS by 2.7 GB and made
the ASR 13x slower.

| stage | peak RAM |
|---|---|
| **ASR** | **1829 MB** |
| TTS | 1328 MB |
| NMT en->indic | 922 MB |
| NMT indic->en | 777 MB |
| RAG | 765 MB |
| *sum if all resident* | *5621 MB* |
| **actual peak** | **1829 MB + 405 MB GPU = 2234 MB** |

### Budget

| | |
|---|---|
| usable after OS (assumed) | ~6500 MB |
| speech pipeline + crop RAG | −2234 MB |
| **left for the VLM and agent** | **≈ 4270 MB** |

Enough for Qwen 2.5B at int4 with room to spare.

### Two settings that matter on the Orin

**Run the ASR on CPU.** ONNX Runtime's CUDA arena grows without bound —
measured 3045 MB on CUDA against **457 MB on CPU**, with no accuracy loss. On
unified memory it makes no difference where the bytes live, and the CPU path
opens no arena.

**Keep the RAG embedder on CPU** (`CUDA_VISIBLE_DEVICES=""`). It is a 384-dim
MiniLM; on GPU it costs ~350 MB of CUDA context for nothing.

Both are already the default in `stage.py`.

---

## Choosing the ASR

Eight configurations on the same 20 clips:

| config | WER | CER |
|---|---|---|
| **int8 · CPU · RNNT** | **25.9%** | 14.1% |
| int8 · CUDA · RNNT | 26.5% | 13.6% |
| fp32 · CPU · RNNT | 27.0% | 13.6% |
| int8 · CPU · CTC | 28.0% | 14.0% |
| fp32 · CUDA · CTC | 28.6% | 13.6% |

Three things this settled:

- **int8 beat fp32.** Quantising cost nothing in accuracy and saved 1.5 GB.
- **RNNT beat CTC** by ~2 points everywhere.
- **CPU vs CUDA is worth ~0.4 points**, far less than the memory it saves.

### Scoring — read this before quoting a WER

Use `pipeline/models/asr_scoring.py`. It applies Devanagari normalisation the
project needs, in particular stripping the danda (`।`), which sits inside the
Indic Unicode range and otherwise survives as a letter.

Scoring the same audio with raw `jiwer` gave **38.0% WER / 18.5% CER**; the
same output through `asr_scoring.score()` gave **25.9% / 14.1%**. Nothing about
the model changed. Any WER quoted from this project should say which scorer
produced it.

WER is also harsh on Devanagari: `रोक` for `रोग` is one character but marks the
whole word wrong. CER is roughly half of WER throughout, and of 20 clips whose
transcripts differed between CPU and CUDA runs, **only one produced a different
prescription**. Answer-accuracy, not WER, is what the farmer experiences.

---

## Choosing the TTS

Five engines, each measured in its own fresh process on the same sentence:

| engine | GPU | real RAM | total | speed | languages |
|---|---|---|---|---|---|
| **MMS-TTS** | **616 MB** | 1453 MB | **2069 MB** | **0.64 s** | **18 Indian** |
| FastSpeech2_HS | 866 MB | 2142 MB | 3008 MB | 0.79 s | 1 per 1.5 GB install |
| parler int4 | 1934 MB | 1714 MB | 3648 MB | 5.13 s | multilingual |
| VITS rasa_13 | 440 MB | — | — | fast | **no Hindi** |
| Veena | — | — | 7.1 GB disk | 1.21x RT | Hindi |

**MMS wins on every axis.** In the full pipeline it adds only **7 MB** of real
RAM, because its weights are memory-mapped into evictable cache.

Two rejections worth recording so nobody repeats them:

- **`ai4bharat/vits_rasa_13` has no Hindi.** Its 13 languages are Assamese,
  Bengali, Bodo, Dogri, Kannada, Maithili, Malayalam, Marathi, Nepali,
  Punjabi, Sanskrit, Tamil, Telugu. Feeding it Hindi produces sounds that seem
  nearly intelligible because the script is shared with Marathi. Check the
  language list on the card, not the script.
- **parler is 93x slower than MMS** — 13.9 s to speak one answer. Its peak also
  scales with reserved generation length, being autoregressive. MMS is
  non-autoregressive: 16x longer text moved its memory by ~12 MB.

### Licence — flagged for whoever ships this

`facebook/mms-tts-*` is **CC-BY-NC 4.0**, non-commercial. Fine for the
hackathon, demos and internal testing. **A blocker if the device is sold.** The
replacement to line up is `ai4bharat/IndicF5` — MIT licence, 11 Indian
languages, 1.4 GB — which is gated and needs an access request on HuggingFace.

Language samples for all 18: `pipeline/results/mms20-languages/`.
Engine comparison on the same sentence: `pipeline/results/tts-comparison/`.

---

## Layout

```
pipeline/
  stage.py            one stage as its own process (the load/unload design)
  orchestrate.py      runs one question through the stage chain
  chain_batch.py      the 20-case process-isolated run
  models/
    quantise_asr.py   int8 export of the ASR encoder
    verify_asr.py     checks every model file against the source repo
    asr_scoring.py    Devanagari-aware WER/CER - use this, not raw jiwer
  results/
    run_full.py       resident runner, all TTS engines
    aggregate.py      rebuild summaries, compare two runs
  bench/              the scripts that produced the numbers in this README
  docs/REPORT.md      NMT, TTS and ASR evaluation from the earlier tasks
  audio-tests/        40 real farmer recordings + manifest
```

Committed results carry every text artefact plus **10 spoken answers per run**
under `samples/`, so the voices can be compared without a GPU. The remaining
audio is regenerable.

---

## Known problems

**2 of 20 clips are near-100% WER** (cases 13 and 18) and drag the average.
Worth understanding before optimising the other 18.

**Nutrient questions are the weak spot.** When ASR loses the one word that
makes it a fertiliser question — खाद, जिंक — what remains is close enough to a
crop name that the RAG answers with that crop's commonest disease. Two of 20
still do this. It needs ASR that preserves entity words, or intent
classification in the router; retrieval-side gates were tried and made things
worse.

**Load times dominate the isolated runner.** 18.9 s per question against 1.97 s
resident, almost all of it reloading models. On a device some hides behind the
farmer speaking, but it is a real trade for the memory.
