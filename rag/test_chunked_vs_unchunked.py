#!/usr/bin/env python3
"""Direct, real, same-text head-to-head: does chunking actually bound peak memory, or is it
no better than one giant call? Same 2397-char Hindi answer both ways, in two separate fresh
processes (so one run's allocator growth can't contaminate the other's baseline) -- this
script runs ONE mode per invocation, a wrapper shells out to run both cleanly.

Run: source venv/bin/activate && cd gramsahayak && python3 rag/test_chunked_vs_unchunked.py
"""
import os
import subprocess
import sys

LONG_TEXT_HI = (
    "आलू की फसल में झुलसा रोग एक गंभीर समस्या है जो पत्तियों पर भूरे धब्बों के रूप में शुरू होती है। "
    "यह रोग नम और गर्म मौसम में तेजी से फैलता है और अगर समय पर नियंत्रण न किया जाए तो पूरी फसल को नुकसान पहुंचा सकता है। "
    "किसानों को सलाह दी जाती है कि वे नियमित रूप से अपने खेतों का निरीक्षण करें और शुरुआती लक्षण दिखते ही उचित कवकनाशी का छिड़काव करें। "
    "मैनकोजेब 75 प्रतिशत डब्ल्यूपी का उपयोग एक एकड़ में छह सौ ग्राम प्रति दो सौ लीटर पानी की दर से किया जा सकता है। "
    "छिड़काव के बाद सात दिनों तक फसल की कटाई नहीं करनी चाहिए ताकि रसायन का प्रभाव कम हो सके। "
    "इसके अलावा फसल चक्र अपनाना और खेत की स्वच्छता बनाए रखना भी इस रोग की रोकथाम में सहायक होता है। "
    "बारिश के बाद खेत में पानी जमा न होने दें और उचित जल निकासी की व्यवस्था करें। "
    "यदि रोग के लक्षण गंभीर हों तो नजदीकी कृषि विज्ञान केंद्र से संपर्क करना बेहतर रहेगा। "
) * 3


def run_mode(mode):
    """One mode per subprocess -- see module docstring for why."""
    import threading
    import time

    import psutil

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from api_server import config
    from models.mms_tts import MultiLangMmsTtsEngine, MmsTtsInferencer

    proc = psutil.Process(os.getpid())
    cfg = config.WORKERS["tts"]["engines"]["mms_tts"]

    engine = MultiLangMmsTtsEngine(checkpoint_root=cfg["checkpoint_root"], languages=cfg["preload_languages"])
    engine.load(language="hi")
    baseline = proc.memory_info().rss / 1e9
    print(f"[{mode}] baseline RSS after load: {baseline:.3f}GB", flush=True)

    tts = MmsTtsInferencer(engine.get("hi"))

    peak = [baseline]
    stop = threading.Event()

    def poll():
        while not stop.is_set():
            peak[0] = max(peak[0], proc.memory_info().rss / 1e9)
            time.sleep(0.05)

    t = threading.Thread(target=poll, daemon=True)
    t.start()

    t0 = time.perf_counter()
    if mode == "unchunked":
        print(f"[{mode}] ONE call, full {len(LONG_TEXT_HI)}-char text, no chunking", flush=True)
        audio, sr = tts.synthesize(LONG_TEXT_HI)
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    else:
        from models.tts_exports.streaming import chunk_text
        chunks = chunk_text(LONG_TEXT_HI, sentence_lang="hi",
                             max_chunk_chars=cfg["chunk_max_chars_by_language"]["hi"])
        print(f"[{mode}] {len(chunks)} chunks", flush=True)
        for i, chunk in enumerate(chunks):
            audio, sr = tts.synthesize(chunk)
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            print(f"[{mode}]   chunk {i+1}/{len(chunks)} ({len(chunk)} chars): RSS={proc.memory_info().rss/1e9:.3f}GB", flush=True)
    elapsed = time.perf_counter() - t0
    stop.set()
    t.join(timeout=2)

    vram = engine.vram_allocated_gb() or 0.0
    print(f"[{mode}] DONE in {elapsed:.2f}s -- PEAK RSS={peak[0]:.3f}GB  VRAM={vram:.3f}GB  "
          f"COMBINED_PEAK={peak[0]+vram:.3f}GB  growth_from_baseline={peak[0]-baseline:.3f}GB", flush=True)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_mode(sys.argv[1])
    else:
        # Wrapper: run both, each in a fresh process.
        this_file = os.path.abspath(__file__)
        for mode in ("unchunked", "chunked"):
            print("\n" + "=" * 90)
            print(f"MODE: {mode}")
            print("=" * 90)
            subprocess.run([sys.executable, this_file, mode], check=True)
