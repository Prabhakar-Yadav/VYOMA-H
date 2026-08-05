"""MMS-TTS across 20 Indian languages: CPU, peak GPU, and time per language.

One model per language, so the device only ever loads the farmer's own. Each is
measured in isolation - load, generate, unload - which is exactly the swap
pattern the Orin will use, and gives the peak the device would really see.

Sentences are real device output for each language: a diagnosis plus a dose.
Each is written in that language's own script rather than transliterated from
Hindi, so no model is fed the wrong orthography.
"""
import gc
import json
import resource
import subprocess
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from transformers import AutoTokenizer, VitsModel

OUT = Path("/tmp/mms20")
OUT.mkdir(exist_ok=True)

LANGS = [
    ("hin", "Hindi", "आपकी फसल में आलू का झुलसा रोग है। एक लीटर पानी में दो ग्राम मिलाएं।"),
    ("ben", "Bengali", "আপনার ফসলে আলুর ধসা রোগ হয়েছে। এক লিটার পানিতে দুই গ্রাম মিশিয়ে নিন।"),
    ("mar", "Marathi", "तुमच्या पिकावर बटाट्याचा करपा रोग आहे. एक लिटर पाण्यात दोन ग्रॅम मिसळा."),
    ("tel", "Telugu", "మీ పంటలో బంగాళాదుంప ఆకుమచ్చ తెగులు ఉంది. ఒక లీటరు నీటిలో రెండు గ్రాములు కలపండి."),
    ("tam", "Tamil", "உங்கள் பயிரில் உருளைக்கிழங்கு கருகல் நோய் உள்ளது. ஒரு லிட்டர் தண்ணீரில் இரண்டு கிராம் கலக்கவும்."),
    ("guj", "Gujarati", "તમારા પાકમાં બટાટાનો સૂકારો રોગ છે. એક લિટર પાણીમાં બે ગ્રામ મિક્સ કરો."),
    ("kan", "Kannada", "ನಿಮ್ಮ ಬೆಳೆಯಲ್ಲಿ ಆಲೂಗಡ್ಡೆ ಅಂಗಮಾರಿ ರೋಗವಿದೆ. ಒಂದು ಲೀಟರ್ ನೀರಿನಲ್ಲಿ ಎರಡು ಗ್ರಾಂ ಬೆರೆಸಿ."),
    ("mal", "Malayalam", "നിങ്ങളുടെ വിളയിൽ ഉരുളക്കിഴങ്ങ് കരിച്ചിൽ രോഗമുണ്ട്. ഒരു ലിറ്റർ വെള്ളത്തിൽ രണ്ട് ഗ്രാം കലർത്തുക."),
    ("pan", "Punjabi", "ਤੁਹਾਡੀ ਫ਼ਸਲ ਵਿੱਚ ਆਲੂ ਦਾ ਝੁਲਸ ਰੋਗ ਹੈ। ਇੱਕ ਲੀਟਰ ਪਾਣੀ ਵਿੱਚ ਦੋ ਗ੍ਰਾਮ ਮਿਲਾਓ।"),
    ("ory", "Odia", "ଆପଣଙ୍କ ଫସଲରେ ଆଳୁ ପୋଡ଼ା ରୋଗ ହୋଇଛି। ଏକ ଲିଟର ପାଣିରେ ଦୁଇ ଗ୍ରାମ ମିଶାଇ ଦିଅନ୍ତୁ।"),
    ("asm", "Assamese", "আপোনাৰ শস্যত আলুৰ পচন ৰোগ হৈছে। এক লিটাৰ পানীত দুই গ্ৰাম মিহলাই লওক।"),
    ("mai", "Maithili", "अहाँक फसल में आलू के झुलसा रोग अछि। एक लीटर पानी में दू ग्राम मिलाउ।"),
    ("urd-script_arabic", "Urdu", "آپ کی فصل میں آلو کا جھلساؤ ہے۔ ایک لیٹر پانی میں دو گرام ملائیں۔"),
    ("dgo", "Dogri", "तुंदी फसल च आलू दा झुलसा रोग ऐ। इक लीटर पानी च दो ग्राम मिलाओ।"),
    ("mag", "Magahi", "आपके फसल में आलू के झुलसा रोग बा। एक लीटर पानी में दू ग्राम मिलाईं।"),
    ("awa", "Awadhi", "तोहार फसल मां आलू के झुलसा रोग बा। एक लीटर पानी मां दुई ग्राम मिलावा।"),
    ("hne", "Chhattisgarhi", "तोर फसल म आलू के झुलसा रोग हे। एक लीटर पानी म दू ग्राम मिलाव।"),
    ("new", "Newari", "छिगु बालीनाप आलुया झुलसा रोग दु। छगू लिटर लखय् निगू ग्राम ल्वाकछ्याय्।"),
    ("npi", "Nepali", "तपाईंको बालीमा आलुको डढुवा रोग छ। एक लिटर पानीमा दुई ग्राम मिसाउनुहोस्।"),
    ("snd", "Sindhi", "توهان جي فصل ۾ آلو جو جھلسا مرض آهي. هڪ لٽر پاڻي ۾ ٻه گرام ملايو."),
]


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


def cpu_seconds():
    ru = resource.getrusage(resource.RUSAGE_SELF)
    return ru.ru_utime + ru.ru_stime


def energy(w):
    """Speech is bursty, noise is flat. Guards against a silently broken load."""
    w = np.asarray(w, dtype="float32")
    fr = max(1, w.size // 60)
    e = np.array([np.sqrt((w[i:i + fr] ** 2).mean() + 1e-12)
                  for i in range(0, w.size - fr, fr)])
    return float(e.max() / (e.mean() + 1e-12))


base_g, base_r = gpu(), rss()
print("baseline before CUDA   GPU {} MB  RSS {:.0f} MB".format(base_g, base_r))
torch.zeros(1).cuda()
torch.cuda.synchronize()
warm_g, warm_r = gpu(), rss()
print("after CUDA context     GPU {} MB  RSS {:.0f} MB".format(warm_g, warm_r))
print()
hdr = "{:16} {:>7} {:>7} {:>8} {:>7} {:>8} {:>8} {:>7} {:>7}".format(
    "language", "load_s", "gen_s", "audio_s", "xRT", "GPUpeak", "RSSpeak",
    "cpu_s", "energy")
print(hdr)
print("-" * len(hdr))

rows = []
for code, name, text in LANGS:
    repo = "facebook/mms-tts-" + code
    c_before = cpu_seconds()
    try:
        t0 = time.time()
        tok = AutoTokenizer.from_pretrained(repo)
        m = VitsModel.from_pretrained(repo).to("cuda").eval()
        load_s = time.time() - t0

        ins = tok(text, return_tensors="pt").to("cuda")
        t1 = time.time()
        with torch.no_grad():
            out = m(**ins)
        torch.cuda.synchronize()
        gen_s = time.time() - t1

        g_peak, r_peak = gpu(), rss()
        cpu_s = cpu_seconds() - c_before
        w = out.waveform[0].detach().cpu().numpy().astype("float32")
        sr = m.config.sampling_rate
        secs = len(w) / sr
        sf.write(str(OUT / (code + "_" + name + ".wav")), w, sr)
        e = energy(w)

        rows.append(dict(code=code, name=name, ok=True,
                         load_s=round(load_s, 2), gen_s=round(gen_s, 3),
                         audio_s=round(secs, 2), xrt=round(secs / gen_s, 1),
                         gpu_peak_mb=g_peak, gpu_delta_mb=g_peak - warm_g,
                         rss_peak_mb=round(r_peak), cpu_s=round(cpu_s, 2),
                         energy=round(e, 2)))
        print("{:16} {:7.2f} {:7.3f} {:8.2f} {:7.1f} {:8} {:8.0f} {:7.2f} {:7.2f}".format(
            name, load_s, gen_s, secs, secs / gen_s, g_peak, r_peak, cpu_s, e))

        del m, tok, out, ins
        gc.collect()
        torch.cuda.empty_cache()
    except Exception as ex:
        rows.append(dict(code=code, name=name, ok=False,
                         error=type(ex).__name__ + ": " + str(ex)[:110]))
        print("{:16}   FAILED  {}: {}".format(name, type(ex).__name__, str(ex)[:48]))
        gc.collect()
        torch.cuda.empty_cache()

ok = [r for r in rows if r.get("ok")]
print()
print("SUMMARY  {}/{} languages generated".format(len(ok), len(LANGS)))
if ok:
    print("  peak GPU across all       {:6} MB".format(max(r["gpu_peak_mb"] for r in ok)))
    print("  peak GPU above CUDA ctx   {:6} MB".format(max(r["gpu_delta_mb"] for r in ok)))
    print("  peak RSS across all       {:6} MB".format(max(r["rss_peak_mb"] for r in ok)))
    print("  unified peak (GPU+RSS)    {:6} MB".format(
        max(r["gpu_peak_mb"] + r["rss_peak_mb"] for r in ok)))
    print("  mean load                 {:6.2f} s".format(sum(r["load_s"] for r in ok) / len(ok)))
    print("  mean generate             {:6.3f} s".format(sum(r["gen_s"] for r in ok) / len(ok)))
    print("  mean CPU per language     {:6.2f} s".format(sum(r["cpu_s"] for r in ok) / len(ok)))
    print("  slowest                   {:6.1f}x real time".format(min(r["xrt"] for r in ok)))
    weak = [r["name"] for r in ok if r["energy"] < 1.8]
    print("  suspicious audio          {}".format(weak if weak else "none"))
failed = [r["name"] for r in rows if not r.get("ok")]
if failed:
    print("  FAILED                    {}".format(failed))

(OUT / "_results.json").write_text(
    json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
print("\nwavs + _results.json in " + str(OUT))
