"""What the speech pipeline would really cost on a Jetson, excluding the VLM.

Adding "GPU used" to "host RSS" is a pessimistic upper bound and probably
double counts: CUDA maps device memory into the process address space, so some
of it appears in RSS as well. RSS also includes file-backed pages - the model
files mmap'd from disk - which the kernel evicts under pressure and which are
therefore not a hard requirement.

This separates the categories that actually matter on a unified-memory device:

  anonymous RSS  heap and weights loaded into RAM. Real, non-evictable.
  file-backed    mmap'd model files. Evictable; costs disk reads, not RAM.
  GPU            device allocations reported by nvidia-smi.

The honest Jetson figure is anonymous + GPU, with file-backed as headroom the
kernel can reclaim.
"""
import gc
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path.home() / "vyoma_pipeline"
sys.path.insert(0, str(HERE / "krishi-rag" / "src"))
sys.path.insert(0, str(HERE / "pipeline" / "models" / "nmt" / "indicTrans2"))


def gpu_mb():
    o = subprocess.run(["nvidia-smi", "--query-gpu=memory.used",
                        "--format=csv,noheader,nounits"],
                       capture_output=True, text=True, timeout=10)
    return int(o.stdout.split()[0])


def mem_breakdown():
    """(rss, anon, file_backed, pss) in MB from smaps_rollup."""
    d = {}
    try:
        for line in open("/proc/self/smaps_rollup"):
            parts = line.split()
            if len(parts) >= 2 and parts[0].endswith(":"):
                key = parts[0][:-1]
                try:
                    d[key] = int(parts[1]) / 1024
                except ValueError:
                    pass
    except FileNotFoundError:
        return (0, 0, 0, 0)
    rss = d.get("Rss", 0)
    anon = d.get("Anonymous", 0)
    pss = d.get("Pss", 0)
    return (rss, anon, max(rss - anon, 0), pss)


def report(tag):
    g = gpu_mb()
    rss, anon, filebacked, pss = mem_breakdown()
    print("  {:26} GPU {:5}  RSS {:6.0f}  anon {:6.0f}  file {:6.0f}  PSS {:6.0f}".format(
        tag, g, rss, anon, filebacked, pss))
    return dict(gpu=g, rss=rss, anon=anon, file=filebacked, pss=pss)


print("STAGE-BY-STAGE, with RSS split into real vs evictable")
print()
snaps = {}
snaps["0 bare"] = report("0. bare python")

import torch
snaps["1 torch"] = report("1. + torch")

# --- ASR on CPU, Hindi head only (the 457 MB configuration) --------------
import importlib.util
D = HERE / "pipeline/models/ai4bharat-int8/indic-conformer-600m-multilingual"
src = (D / "model_onnx.py").read_text(encoding="utf-8")
import re
src = re.sub(r"\+ \[f'joint_post_net_\{z\}' for z in \[[^\]]*\]\]",
             "+ ['joint_post_net_hi']", src)
src = src.replace(
    "providers = ['CUDAExecutionProvider', 'CPUExecutionProvider'] "
    "if torch.cuda.is_available() else ['CPUExecutionProvider']",
    "providers = ['CPUExecutionProvider']")
patched = Path("/tmp/model_onnx_hi2.py")
patched.write_text(src, encoding="utf-8")
spec = importlib.util.spec_from_file_location("iasr_hi2", str(patched))
iasr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(iasr)
asr = iasr.IndicASRModel(iasr.IndicASRConfig(ts_folder=str(D)))
snaps["2 asr"] = report("2. + ASR (CPU, hi only)")

# --- NMT both directions -------------------------------------------------
from inference.engine import Model
nmt_in = Model(str(HERE / "pipeline/models/nmt/indicTrans2/checkpoints/indic-en/ct2_int8_model"),
               device="cpu", input_lang_code_format="iso", model_type="ctranslate2")
snaps["3 nmt_in"] = report("3. + NMT indic-en")
nmt_out = Model(str(HERE / "pipeline/models/nmt/indicTrans2/checkpoints/en-indic/ct2_int8_model"),
                device="cpu", input_lang_code_format="iso", model_type="ctranslate2")
snaps["4 nmt_out"] = report("4. + NMT en-indic")

# --- RAG -----------------------------------------------------------------
from okf import load_bundle
from retrieval import HybridRetriever
concepts = load_bundle(HERE / "krishi-rag" / "bundle")
retr = HybridRetriever.load(HERE / "krishi-rag" / "index" / "krishi.pkl")
retr.search("orange powder on wheat leaves", top_k=4)
snaps["5 rag"] = report("5. + RAG index + embedder")

# --- MMS TTS on CPU ------------------------------------------------------
from transformers import AutoTokenizer, VitsModel
tok = AutoTokenizer.from_pretrained("facebook/mms-tts-hin")
tts = VitsModel.from_pretrained("facebook/mms-tts-hin").eval()   # CPU
snaps["6 tts"] = report("6. + MMS TTS (CPU)")

# --- one real end-to-end question ---------------------------------------
print()
print("running one full question through the loaded stack ...")
import soundfile as sf
import torchaudio
clip = HERE / "pipeline/audio-tests/audio/11.ogg"
data, sr = sf.read(str(clip), dtype="float32", always_2d=True)
w = torch.from_numpy(data.T).mean(0, keepdim=True)
if sr != 16000:
    w = torchaudio.functional.resample(w, sr, 16000)
t0 = time.time()
with torch.no_grad():
    heard = asr(w, "hi", "rnnt")
heard = heard[0] if isinstance(heard, (list, tuple)) else heard
eng = nmt_in.batch_translate([str(heard)], "hi", "en")[0]
reply_en = "Your crop has potato late blight. Mix two grams in one litre of water."
native = nmt_out.batch_translate([reply_en], "en", "hi")[0]
ins = tok(native, return_tensors="pt")
with torch.no_grad():
    audio = tts(**ins).waveform[0].numpy()
dt = time.time() - t0
snaps["7 after"] = report("7. after one full question")
print("  heard   : {}".format(str(heard)[:60]))
print("  english : {}".format(str(eng)[:60]))
print("  spoke   : {:.1f}s of audio in {:.2f}s total".format(
    len(audio) / tts.config.sampling_rate, dt))

peak = snaps["7 after"]
print()
print("=" * 66)
print("JETSON ESTIMATE  (speech pipeline only, VLM and agent NOT included)")
print("=" * 66)
print("  anonymous RSS (real, cannot be evicted)   {:7.0f} MB".format(peak["anon"]))
print("  GPU device memory                         {:7.0f} MB".format(peak["gpu"]))
print("  ---------------------------------------------------")
print("  HARD REQUIREMENT                          {:7.0f} MB".format(
    peak["anon"] + peak["gpu"]))
print()
print("  file-backed mmap (evictable, disk cache)  {:7.0f} MB".format(peak["file"]))
print("  naive RSS+GPU (what I quoted before)      {:7.0f} MB".format(
    peak["rss"] + peak["gpu"]))
print()
print("  On an Orin with ~6.5 GB usable, headroom left for")
print("  the VLM and agent:                        {:7.0f} MB".format(
    6500 - (peak["anon"] + peak["gpu"])))
