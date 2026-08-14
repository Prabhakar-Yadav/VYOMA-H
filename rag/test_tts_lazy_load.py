#!/usr/bin/env python3
"""Isolated, real verification of the 2026-08-11 TTS lazy-load fix -- no gateway, no HTTP,
directly exercises models/mms_tts/model_loader.py's MultiLangMmsTtsEngine in-process so the
measurement isn't muddied by whatever else is resident in a shared gateway process.

Checks, in order:
  1. load() with no language argument loads NOTHING (real RSS delta ~0).
  2. load(language="hi") loads ONLY Hindi -- confirmed by inspecting ._engines directly,
     not just trusting a memory delta.
  3. A real chunked synthesis of a genuinely long (~1200 char) Hindi answer, with live
     peak-RSS polling during the call, to get a fresh real number for the "does chunking +
     _release_chunk_memory() actually bound peak near ~1.6GB" question -- not reused from
     old docs.

Run: source venv/bin/activate && cd gramsahayak && python3 rag/test_tts_lazy_load.py
"""
import os
import sys
import threading
import time

import psutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from api_server import config  # noqa: E402
from models.mms_tts import MultiLangMmsTtsEngine, MmsTtsInferencer  # noqa: E402

PROC = psutil.Process(os.getpid())


def rss_gb():
    return PROC.memory_info().rss / 1e9


def main():
    cfg = config.WORKERS["tts"]["engines"]["mms_tts"]

    print("=" * 88)
    print("STEP 1: load() with no language -- should load nothing")
    print("=" * 88)
    before = rss_gb()
    engine = MultiLangMmsTtsEngine(checkpoint_root=cfg["checkpoint_root"],
                                    languages=cfg["preload_languages"])
    engine.load()
    after = rss_gb()
    print(f"RSS before={before:.3f}GB after={after:.3f}GB delta={after - before:.3f}GB")
    print(f"is_loaded={engine.is_loaded}  resident languages={list(engine._engines.keys())}")
    assert engine.is_loaded, "engine should report ready after load()"
    assert not engine._engines, "load() with no language should NOT eagerly load anything"
    print("PASS: lazy load() loaded zero languages, engine still reports ready\n")

    print("=" * 88)
    print("STEP 2: load(language='hi') -- should load ONLY Hindi")
    print("=" * 88)
    before = rss_gb()
    t0 = time.perf_counter()
    engine2 = MultiLangMmsTtsEngine(checkpoint_root=cfg["checkpoint_root"],
                                     languages=cfg["preload_languages"])
    engine2.load(language="hi")
    load_time = time.perf_counter() - t0
    after = rss_gb()
    print(f"RSS before={before:.3f}GB after={after:.3f}GB delta={after - before:.3f}GB "
          f"(load_time={load_time:.2f}s)")
    print(f"resident languages={list(engine2._engines.keys())}")
    assert list(engine2._engines.keys()) == ["hi"], \
        f"expected ONLY hi resident, got {list(engine2._engines.keys())}"
    print("PASS: exactly one language (hi) resident, ta/ml/en never touched\n")

    print("=" * 88)
    print("STEP 3: real chunked synthesis of a long Hindi answer, live peak-RSS polling")
    print("=" * 88)
    long_text = (
        "आलू की फसल में झुलसा रोग एक गंभीर समस्या है जो पत्तियों पर भूरे धब्बों के रूप में शुरू होती है। "
        "यह रोग नम और गर्म मौसम में तेजी से फैलता है और अगर समय पर नियंत्रण न किया जाए तो पूरी फसल को नुकसान पहुंचा सकता है। "
        "किसानों को सलाह दी जाती है कि वे नियमित रूप से अपने खेतों का निरीक्षण करें और शुरुआती लक्षण दिखते ही उचित कवकनाशी का छिड़काव करें। "
        "मैनकोजेब 75 प्रतिशत डब्ल्यूपी का उपयोग एक एकड़ में छह सौ ग्राम प्रति दो सौ लीटर पानी की दर से किया जा सकता है। "
        "छिड़काव के बाद सात दिनों तक फसल की कटाई नहीं करनी चाहिए ताकि रसायन का प्रभाव कम हो सके। "
        "इसके अलावा फसल चक्र अपनाना और खेत की स्वच्छता बनाए रखना भी इस रोग की रोकथाम में सहायक होता है। "
        "बारिश के बाद खेत में पानी जमा न होने दें और उचित जल निकासी की व्यवस्था करें। "
        "यदि रोग के लक्षण गंभीर हों तो नजदीकी कृषि विज्ञान केंद्र से संपर्क करना बेहतर रहेगा। "
    ) * 3  # ~1200+ chars, matches the real crash-inducing length from the docs
    print(f"text length: {len(long_text)} chars")

    peak = [rss_gb()]
    stop = threading.Event()

    def poll():
        while not stop.is_set():
            peak[0] = max(peak[0], rss_gb())
            time.sleep(0.1)

    poll_thread = threading.Thread(target=poll, daemon=True)
    poll_thread.start()

    t0 = time.perf_counter()
    tts = MmsTtsInferencer(engine2.get("hi"))
    from models.tts_exports.streaming import chunk_text
    chunks = chunk_text(long_text, sentence_lang="hi",
                         max_chunk_chars=cfg["chunk_max_chars_by_language"]["hi"])
    print(f"chunked into {len(chunks)} pieces (max_chars={cfg['chunk_max_chars_by_language']['hi']})")
    for i, chunk in enumerate(chunks):
        audio, sr = tts.synthesize(chunk)
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        print(f"  chunk {i+1}/{len(chunks)}: {len(chunk)} chars -> {len(audio)/sr:.1f}s audio, "
              f"RSS now={rss_gb():.3f}GB")
    elapsed = time.perf_counter() - t0
    stop.set()
    poll_thread.join(timeout=2)

    print(f"\nreal synthesis time: {elapsed:.2f}s")
    print(f"REAL PEAK RSS during this call: {peak[0]:.3f}GB")
    print(f"(this process's RSS only -- add real VRAM separately if CUDA is in use, "
          f"see vram_allocated_gb() below)")
    vram = engine2.vram_allocated_gb()
    if vram is not None:
        print(f"VRAM allocated: {vram:.3f}GB")
        print(f"REAL PEAK COMBINED (this process RSS + VRAM): {peak[0] + vram:.3f}GB")


if __name__ == "__main__":
    main()
