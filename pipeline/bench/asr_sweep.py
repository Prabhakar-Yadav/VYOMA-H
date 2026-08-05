"""Find the best ASR configuration on the 20 real clips.

Four axes, all cheap to test and none requiring a different model:

  int8 vs fp32   we quantised the encoder ourselves; fp32 measured 27.2% vs
                 29.0% on the 40-clip set, so it is worth confirming here
  RNNT vs CTC    two decoders ship in the same checkpoint
  CPU vs CUDA    measured to cost only ~0.4 WER, but confirm on this set

Scored with one function throughout, so the numbers are comparable with each
other - the previous 38 vs 28.7 confusion came from two scripts normalising
differently, not from any real difference.
"""
import importlib.util
import itertools
import json
import re
import sys
import time
from pathlib import Path

HERE = Path.home() / "vyoma_pipeline"
sys.path.insert(0, str(HERE / "bhashini-eval"))
import asr_scoring as scoring

import soundfile as sf
import torch
import torchaudio

TESTS = HERE / "pipeline/audio-tests"
man = json.loads((TESTS / "manifest.json").read_text(encoding="utf-8"))
cases = [c for c in man if int(c["id"]) <= 20]

VARIANTS = {
    "int8": HERE / "pipeline/models/ai4bharat-int8/indic-conformer-600m-multilingual",
    "fp32": sorted((Path.home() / ".cache/huggingface/hub"
                    "/models--ai4bharat--indic-conformer-600m-multilingual"
                    "/snapshots").iterdir())[0],
}


def load(model_dir, device):
    """Hindi head only; device chosen explicitly."""
    src = (model_dir / "model_onnx.py").read_text(encoding="utf-8")
    src = re.sub(r"\+ \[f'joint_post_net_\{z\}' for z in \[[^\]]*\]\]",
                 "+ ['joint_post_net_hi']", src)
    prov = ("['CUDAExecutionProvider', 'CPUExecutionProvider']"
            if device == "cuda" else "['CPUExecutionProvider']")
    src = src.replace(
        "providers = ['CUDAExecutionProvider', 'CPUExecutionProvider'] "
        "if torch.cuda.is_available() else ['CPUExecutionProvider']",
        "providers = " + prov)
    p = Path("/tmp/_sweep_asr.py")
    p.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("sweep_asr", str(p))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.IndicASRModel(m.IndicASRConfig(ts_folder=str(model_dir)))


clips = []
for c in cases:
    data, sr = sf.read(str(TESTS / c["audio"]), dtype="float32", always_2d=True)
    w = torch.from_numpy(data.T).mean(0, keepdim=True)
    if sr != 16000:
        w = torchaudio.functional.resample(w, sr, 16000)
    clips.append((int(c["id"]), w, c["reference_hindi"]))
print("loaded {} clips\n".format(len(clips)))

print("{:22} {:>8} {:>8} {:>9} {:>8}".format(
    "config", "WER%", "CER%", "under20", "secs"))
print("-" * 60)

results = {}
for variant, device, decode in itertools.product(
        ("int8", "fp32"), ("cpu", "cuda"), ("rnnt", "ctc")):
    tag = "{}-{}-{}".format(variant, device, decode)
    try:
        asr = load(VARIANTS[variant], device)
    except Exception as e:
        print("{:22} load failed: {}".format(tag, str(e)[:40]))
        continue
    t0 = time.time()
    refs, hyps = [], []
    for cid, w, ref in clips:
        try:
            with torch.no_grad():
                out = asr(w, "hi", decode)
            heard = out[0] if isinstance(out, (list, tuple)) else out
        except Exception as e:
            if not hyps:
                print("    first failure: {}: {}".format(
                    type(e).__name__, str(e)[:150]))
            heard = ""
        refs.append(ref)
        hyps.append(str(heard))
    dt = time.time() - t0
    # asr_scoring.score() applies the Devanagari normalisation this project
    # needs - notably stripping the danda, which sits inside the Indic Unicode
    # range and otherwise survives as a letter and inflates WER.
    sc = scoring.score(refs, hyps)
    W = sc.get("wer", 0) * (100 if sc.get("wer", 0) <= 1 else 1)
    C = sc.get("cer", 0) * (100 if sc.get("cer", 0) <= 1 else 1)
    import jiwer
    per = [jiwer.wer(scoring.normalise(r), scoring.normalise(h)) * 100
           for r, h in zip(refs, hyps)]
    u20 = sum(1 for x in per if x < 20)
    results[tag] = dict(wer=W, cer=C, under20=u20, secs=dt)
    print("{:22} {:8.1f} {:8.1f} {:9} {:8.0f}".format(tag, W, C, u20, dt))
    del asr

print()
best = min(results.items(), key=lambda kv: kv[1]["wer"])
print("BEST: {}  WER {:.1f}%  CER {:.1f}%".format(
    best[0], best[1]["wer"], best[1]["cer"]))
cur = results.get("int8-cpu-rnnt")
if cur:
    print("current (int8-cpu-rnnt): WER {:.1f}%  CER {:.1f}%".format(
        cur["wer"], cur["cer"]))
    print("improvement available: {:.1f} WER points".format(cur["wer"] - best[1]["wer"]))
Path("/tmp/asr_sweep.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
