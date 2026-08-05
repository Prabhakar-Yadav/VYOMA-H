"""Where the memory actually is, before trying to quantise the wrong thing.

FastSpeech2's parameters are 142 MB. The pipeline peaks in the gigabytes. If
the weights are a small fraction of the total, quantising them - to int8, int4
or anything else - cannot move the number, and the effort belongs elsewhere.
This measures each layer of the stack in the order it gets paid for.
"""
import gc
import os
import subprocess
import sys
from pathlib import Path


def gpu():
    o = subprocess.run(["nvidia-smi", "--query-gpu=memory.used",
                        "--format=csv,noheader,nounits"],
                       capture_output=True, text=True, timeout=10)
    return int(o.stdout.split()[0])


def rss():
    for line in open("/proc/self/status"):
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024
    return 0.0


rows = []


def mark(tag):
    g, r = gpu(), rss()
    rows.append((tag, g, r))
    print(f"  {tag:36} GPU {g:6}  RSS {r:7.0f}  TOTAL {g + r:7.0f} MB")


print("COST OF EACH LAYER, IN THE ORDER IT IS PAID")
mark("0. bare python")

import torch
mark("1. + import torch")

torch.zeros(1).cuda()
torch.cuda.synchronize()
mark("2. + CUDA context created")

import onnxruntime as ort
mark("3. + import onnxruntime")

D = Path.home() / "vyoma_pipeline/pipeline/models/ai4bharat-int8/indic-conformer-600m-multilingual"
import importlib.util
spec = importlib.util.spec_from_file_location("iasr", str(D / "model_onnx.py"))
iasr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(iasr)
asr = iasr.IndicASRModel(iasr.IndicASRConfig(ts_folder=str(D)))
mark("4. + ASR int8 (28 ORT sessions)")

sys.path.insert(0, str(Path.home() / "vyoma_pipeline/pipeline/models/nmt/indicTrans2"))
from inference.engine import Model
nmt = Model(str(Path.home() / "vyoma_pipeline/pipeline/models/nmt/indicTrans2"
                              "/checkpoints/indic-en/ct2_int8_model"),
            device="cpu", input_lang_code_format="iso", model_type="ctranslate2")
mark("5. + NMT indic-en")

FS2 = sorted((Path.home() / ".cache/huggingface/hub"
              "/models--smtiitm--Fastspeech2_HS/snapshots").iterdir())[0]
cwd = os.getcwd()
os.chdir(FS2)
sys.path.insert(0, str(FS2))
sys.path.insert(0, str(FS2 / "hifigan"))
spec2 = importlib.util.spec_from_file_location("fs2_root", str(FS2 / "inference.py"))
fs2 = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(fs2)
mark("6. + import espnet/FastSpeech2 code")

voc = fs2.load_hifigan_vocoder("hindi", "female", "cuda")
mark("7. + HiFi-GAN vocoder")

tts = fs2.load_fastspeech2_model("hindi", "female", "cuda")
mark("8. + FastSpeech2 WEIGHTS")
os.chdir(cwd)

params = sum(p.numel() * p.element_size() for p in tts.model.parameters()) / 1048576
print()
print(f"FastSpeech2 parameters: {params:.0f} MB")
tot = rows[-1][1] + rows[-1][2]
print(f"Total stack:            {tot:.0f} MB")
print(f"Weights as a share:     {100*params/tot:.1f}%")
print()
print("DELTAS")
for i in range(1, len(rows)):
    t, g, r = rows[i]
    _, pg, pr = rows[i - 1]
    print(f"  {t:36} +{(g-pg)+(r-pr):7.0f} MB")
