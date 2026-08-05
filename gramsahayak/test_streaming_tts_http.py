"""Real end-to-end test of the NEW `/infer_stream` HTTP path -- starts the actual gateway,
loads TTS for real, and calls `streaming.py`'s `play_http_stream()` against it, over real
HTTP, through the real gateway proxy (not the local in-process `play_stream()` path
`test_streaming_tts_only.py` exercises). This is what actually answers the question
`test_orchestrated_pipeline.py`'s docs previously couldn't: does a caller going through the
gateway get the real time-to-first-audio benefit, or does it get buffered away somewhere in
the stack? Engine is config-driven (`api_server.config.TTS_ENGINE`) -- same real Hindi
answer either way, but mms_tts (a single non-chunked forward pass) is expected to just play
immediately with no buffering phase, while parler's real batching/prebuffering behavior is
the one worth watching closely (`debug=True` prints the live buffer-threshold decision).

Run: source venv/bin/activate && python test_streaming_tts_http.py
"""
import os
import subprocess
import sys
import time

import requests

AGENTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AGENTS_DIR)

from api_server import config  # noqa: E402
from models.tts_exports.streaming import play_http_stream  # noqa: E402

GATEWAY = f"http://{config.GATEWAY_HOST}:{config.GATEWAY_PORT}"

# Real translated_answer, verbatim from vyoma_v4.ipynb's Demo 3 Hindi run -- same real text
# every other TTS timing test in this project has used, for direct comparability.
HINDI_TEXT = (
    "आपके विवरण के आधार पर, आलू के पत्तों में छोटे छेद और चूहों से कंधे के काटने के निशान केवल "
    "सामान्य कीट क्षति के बजाय जीवाण्विक पत्ते के धब्बे * * (78 प्रतिशत आत्मविश्वास) का सुझाव देते "
    "हैं। क्षेत्र के किनारों के पास चूहे के नियंत्रण के लिए, वारफेरिन 10% * * या डिपासिनन एम * * "
    "जैसे कृन्तनाशक का उपयोग करें, जो आलू के लिए सुरक्षित हैं क्योंकि वे विशेष रूप से कृन्तकों को "
    "लक्षित करते हैं और कंदों में अवशेष का स्तर कम होता है।\n\n"
    "कीटों से आलू की सुरक्षा के लिएः-कार्बोसल्फान * * (अत्यधिक विषाक्त कीटनाशक) का उपयोग अनुशंसित "
    "दरों पर करें, लेकिन यह आलू के लिए पंजीकृत नहीं है-पहले अपने स्थानीय कृषि विस्तार अधिकारी से "
    "संपर्क करें-वैकल्पिक रूप से क्लॉथियानिडिन 50 प्रतिशत डब्ल्यू. डी. जी. *\n\n"
    "महत्वपूर्णः किसी भी कीटनाशक को लगाने से पहले हमेशा अपने केवीके/एफपीओ या राज्य कृषि विभाग से "
    "परामर्श लें, विशेष रूप से कार्बोसल्फान (बेहद विषाक्त)-कुछ उपयोग दिखाने के बावजूद आलू के लिए "
    "पंजीकृत नहीं है।"
)


def banner(title):
    print("\n" + "=" * 88)
    print(title)
    print("=" * 88)


def wait_for_gateway(timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if requests.get(f"{GATEWAY}/health", timeout=1.0).status_code == 200:
                return True
        except requests.exceptions.RequestException:
            pass
        time.sleep(0.3)
    return False


def main():
    banner(f"TTS engine (from config.TTS_ENGINE): {config.WORKERS['tts']['engine']!r}")

    banner("Starting real gateway (run_all.py)...")
    gateway_proc = subprocess.Popen(
        [sys.executable, "run_all.py"], cwd=os.path.join(AGENTS_DIR, "api_server")
    )
    try:
        if not wait_for_gateway():
            print("gateway did not become healthy in time", file=sys.stderr)
            return 1

        banner("Loading TTS (real /tts/load call)...")
        t0 = time.perf_counter()
        r = requests.post(f"{GATEWAY}/tts/load", timeout=120)
        r.raise_for_status()
        print(f"loaded in {time.perf_counter() - t0:.2f}s -- {r.json()}")

        banner(
            "REAL HTTP STREAMING PLAYBACK -- via /tts/infer_stream, through the real gateway\n"
            "proxy, over real HTTP -- not the local in-process play_stream() path.\n"
            "Watch for [buffer]/[play] lines: same smart-prebuffer decision as the local path,\n"
            "now driven by chunks arriving over the network instead of a local generator."
        )
        t0 = time.perf_counter()
        handle = play_http_stream(
            GATEWAY, HINDI_TEXT, language="Hindi", batch_size=3,
            backend="sounddevice", blocking=True, debug=True,
        )
        wall_clock = time.perf_counter() - t0
        audio, sr = handle.full_audio()
        print(f"\ntotal wall-clock (network + generation + playback): {wall_clock:.2f}s")
        print(f"received {len(handle.chunks)} chunk(s), {len(audio) / sr:.2f}s of audio total")

        banner("Unloading TTS...")
        requests.post(f"{GATEWAY}/tts/unload", timeout=60)

    finally:
        gateway_proc.terminate()
        try:
            gateway_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            gateway_proc.kill()

    return 0


if __name__ == "__main__":
    sys.exit(main())
