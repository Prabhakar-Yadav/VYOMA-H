"""Every TTS measured identically, each in its own fresh process.

Earlier figures were taken at different points with different methods, so they
were not comparable. This runs one engine per process, from a cold start, on
the same sentence, and reports the same three numbers each time:

  GPU        device memory from nvidia-smi
  real RAM   anonymous resident memory - heap and weights actually in RAM,
             excluding memory-mapped model files the kernel can evict
  total      what a unified-memory device like the Orin would have to find

Run as:  python tts_clean.py <engine>
"""
import gc
import os
import subprocess
import sys
import time
from pathlib import Path

TEXT = "आपकी फसल में आलू का झुलसा रोग है। एक लीटर पानी में दो ग्राम मिलाएं।"


def gpu():
    o = subprocess.run(["nvidia-smi", "--query-gpu=memory.used",
                        "--format=csv,noheader,nounits"],
                       capture_output=True, text=True, timeout=10)
    return int(o.stdout.split()[0])


def anon():
    for line in open("/proc/self/smaps_rollup"):
        if line.startswith("Anonymous:"):
            return int(line.split()[1]) / 1024
    return 0.0


def run(engine):
    g0, a0 = gpu(), anon()
    peak_g = peak_a = 0
    audio_s = gen_s = 0.0
    load_s = 0.0

    if engine == "mms":
        t = time.time()
        import torch
        from transformers import AutoTokenizer, VitsModel
        tok = AutoTokenizer.from_pretrained("facebook/mms-tts-hin")
        m = VitsModel.from_pretrained("facebook/mms-tts-hin").to("cuda").eval()
        load_s = time.time() - t
        ins = tok(TEXT, return_tensors="pt").to("cuda")
        t = time.time()
        with torch.no_grad():
            out = m(**ins)
        torch.cuda.synchronize()
        gen_s = time.time() - t
        w = out.waveform[0].detach().cpu().numpy()
        audio_s = len(w) / m.config.sampling_rate

    elif engine == "fastspeech2":
        t = time.time()
        import torch
        FS2 = sorted((Path.home() / ".cache/huggingface/hub"
                      "/models--smtiitm--Fastspeech2_HS/snapshots").iterdir())[0]
        cwd = os.getcwd()
        os.chdir(FS2)
        sys.path.insert(0, str(FS2))
        sys.path.insert(0, str(FS2 / "hifigan"))
        import importlib.util
        spec = importlib.util.spec_from_file_location("fs2", str(FS2 / "inference.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        pre = mod.TTSDurAlignPreprocessor()
        voc = mod.load_hifigan_vocoder("hindi", "female", "cuda")
        tts = mod.load_fastspeech2_model("hindi", "female", "cuda")
        load_s = time.time() - t
        t = time.time()
        with torch.no_grad():
            p, _ = pre.preprocess(TEXT, "hindi", "female", {})
            o = tts(" ".join(p), decode_conf={"alpha": 1.0})
            x = o["feat_gen_denorm"].T.unsqueeze(0) * 2.3262
            a = voc(x.to("cuda")).squeeze().detach().cpu().numpy()
        torch.cuda.synchronize()
        gen_s = time.time() - t
        audio_s = len(a) / mod.SAMPLING_RATE
        os.chdir(cwd)

    elif engine == "parler":
        t = time.time()
        import torch
        sys.path.insert(0, str(Path.home() / "vyoma_hackathon"))
        from tts_exports import QuantizedParlerTTS, TTSInferencer
        eng = QuantizedParlerTTS()
        eng.load()
        tts = TTSInferencer(eng)
        load_s = time.time() - t
        t = time.time()
        out = tts.synthesize(TEXT, description=(
            "A female speaker delivers a clear and steady explanation in a calm "
            "voice, with very close recording and almost no background noise."),
            language="hi")
        gen_s = time.time() - t
        wav, sr = out if isinstance(out, tuple) else (out, 24000)
        import numpy as np
        audio_s = len(np.asarray(wav).squeeze()) / sr

    peak_g, peak_a = gpu(), anon()
    print("{:14} GPU {:6.0f} MB   real RAM {:7.0f} MB   TOTAL {:7.0f} MB   "
          "load {:5.1f}s  gen {:6.2f}s for {:5.1f}s audio".format(
              engine, peak_g - g0, peak_a - a0,
              (peak_g - g0) + (peak_a - a0), load_s, gen_s, audio_s))


if __name__ == "__main__":
    run(sys.argv[1])
