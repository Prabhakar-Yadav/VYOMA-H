"""Full ASR -> NMT -> Agent -> NMT -> TTS pipeline, run through the real gateway
(api_server/gateway.py) with every load/unload decision made by MemoryOrchestrator
(api_server/orchestrator.py) -- i.e. the actual load_balancer_plan.md rules acting on the
actual checkpoints, not a simulation. Every [ORCH] line is a real decision (load, evict,
preload, budget check) with real memory numbers read live from the gateway; every [PIPE]
line is this script's own pipeline progress.

This is gramsahayak/'s own end-to-end validation script -- run it after `setup/
download_models.py` to confirm a fresh install actually works. See gramsahayak/README.md.

Real agent, real tool-calling loop (agent/agent.py's GramSahayakAgent -- same SYSTEM_PROMPT,
same 5 mock + 2 real tools as the original vyoma_v5.ipynb this was extracted from), real ASR
transcription, real NMT translation, real batched TTS synthesis. The Embedder only loads if
the agent actually calls a tool needing vector search -- not exercised by today's mock tools,
but Rule 7 (on-demand only) is implemented and ready for when real retrieval tools replace them.

Run: source venv/bin/activate && cd gramsahayak && python test_orchestrated_pipeline.py --language hi
     python test_orchestrated_pipeline.py --all          # every language back to back, one session
     python test_orchestrated_pipeline.py --language hi --no-play   # save the .wav, skip playback
     python test_orchestrated_pipeline.py --language hi --with-image  # attach the sample photo
        (Q1, the plain pesticide question, has no photo -- the agent asking for one on that
        question is correct behavior, not a bug. --with-image switches to Q2 -- "what's wrong
        with this plant" -- WITH datasets/sample-images/pepper_diseased.png attached, so
        analyze_photo has something real to look at, using q2_<lang>.wav for non-English input.)
     python test_orchestrated_pipeline.py --language hi --stream-tts  # real incremental TTS
        playback over /tts/infer_stream instead of the default blocking /tts/infer -- see
        TTS_HTTP_STREAMING_RESULTS.md. Opt-in, not the default: /tts/infer remains the
        simpler, more proven fallback path if streaming ever causes a real-world problem.

Audio is played live through this machine's default output device after each turn (via
sounddevice) -- the TTS worker runs in its own subprocess and only returns audio bytes over
HTTP, so playback happens here in the demo script, not inside the worker (--stream-tts is the
one exception: it plays live *during* the /tts/infer_stream call itself, inside
orchestrator.py's own timed TTS stage, not as a separate step afterward). Every turn's audio
is also always saved to sample_audio/pipeline_outputs/orchestrated_<lang>.wav regardless of
--no-play (--stream-tts ignores --no-play -- playback IS the point of that path).
"""
import argparse
import base64
import io
import os
import subprocess
import sys
import time
from pathlib import Path

import requests
import soundfile as sf

try:
    import sounddevice as sd
    _HAS_SOUNDDEVICE = True
except (ImportError, OSError):
    _HAS_SOUNDDEVICE = False

AGENTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AGENTS_DIR)

from api_server import config  # noqa: E402
from api_server.orchestrator import MemoryOrchestrator  # noqa: E402
from agent import GramSahayakAgent  # noqa: E402
from models.tts_exports.streaming import play_http_stream  # noqa: E402

GATEWAY = f"http://{config.GATEWAY_HOST}:{config.GATEWAY_PORT}"

LANGUAGES = {
    "en": {"tts_name": "English", "asr_supported": False},
    "hi": {"tts_name": "Hindi", "asr_supported": True},
    "ml": {"tts_name": "Malayalam", "asr_supported": True},
    "ta": {"tts_name": "Tamil", "asr_supported": True},
}

Q1_TEXT_EN = (
    "What are the best pesticides I should use in my small farm to prevent potatoes "
    "from pests and rats?"
)
Q2_TEXT_EN = "What's wrong with this plant, and what should I do about it?"
# Self-contained within this package (gramsahayak/datasets/sample-images/) -- this file sits
# directly at the package root (AGENTS_DIR == gramsahayak/), one level shallower than
# dev/agents/test_orchestrated_pipeline.py was relative to the wider blue-parrot repo, and
# gramsahayak/ carries its own copy of this fixture rather than reaching outside itself.
SAMPLE_IMAGE_PATH = Path(AGENTS_DIR) / "datasets" / "sample-images" / "pepper_diseased.png"


def banner(title):
    print("\n" + "=" * 88)
    print(title)
    print("=" * 88)


def play_audio(path):
    if not _HAS_SOUNDDEVICE:
        print(f"[PIPE] sounddevice not available -- skipping playback (audio saved at {path})")
        return
    audio, sr = sf.read(path, dtype="float32")
    print(f"[PIPE] playing audio ({len(audio) / sr:.1f}s)...")
    sd.play(audio, sr)
    sd.wait()


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


def run_full_pipeline(language, orch, agent, play=True, with_image=False, stream_tts=False):
    cfg = LANGUAGES[language]
    orch.reset_turn()
    image_path = SAMPLE_IMAGE_PATH if with_image else None
    if with_image:
        assert image_path.exists(), f"sample image not found: {image_path}"
    banner(f"FULL PIPELINE -- language={language} ({cfg['tts_name']})"
           f"{' + image' if with_image else ''}")
    turn_t0 = time.perf_counter()

    # Rule 9: fire Agent's load in the background right now, at the earliest possible point
    # in the turn -- overlaps its ~5-7.5s real load time with ASR+NMT's own work below (or,
    # for English, gives it a head start before the agent stage needs it).
    orch.preload_agent()

    question_key = "q2" if with_image else "q1"
    question_en = Q2_TEXT_EN if with_image else Q1_TEXT_EN

    if language == "en":
        english_query = question_en
        print(f"[PIPE] English input -- skipping ASR and input-NMT")
        print(f"[PIPE] query: {english_query}")
    else:
        audio_path = Path(AGENTS_DIR) / "sample_audio" / "pipeline_inputs" / f"{question_key}_{language}.wav"
        assert audio_path.exists(), f"sample audio not found: {audio_path}"
        with open(audio_path, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode("utf-8")

        def _asr_call():
            r = requests.post(
                f"{GATEWAY}/asr/infer",
                json={"audio_base64": audio_b64, "language": language},
                timeout=60,
            )
            r.raise_for_status()
            return r.json()["text"]

        raw_query = orch.run_asr(language, _asr_call)
        print(f"[PIPE] transcribed ({language}): {raw_query}")

        def _nmt_to_en_call():
            r = requests.post(
                f"{GATEWAY}/nmt/infer",
                json={"text": raw_query, "src_lang": language, "tgt_lang": "EN"},
                timeout=30,
            )
            r.raise_for_status()
            return r.json()["translated_text"]

        # keep_loaded=True: NMT is reused again after the agent turn (EN->target below), so
        # it stays resident through the agent stage per load_balancer_plan.md's Section 4-B --
        # Rule 2 (inside run_tts) is what evicts it, right at the TTS-peak boundary, not here.
        english_query = orch.run_nmt(f"{language}->EN", _nmt_to_en_call, keep_loaded=True)
        print(f"[PIPE] translated to English: {english_query}")

    def _agent_call():
        # Real tool-calling agent (dev/agents/agent.py, extracted from vyoma_v5.ipynb) --
        # not a bare chat() call. Prints its own [agent iter N] timing + any tool calls it
        # makes, interleaved with the [ORCH]/[PIPE] lines above/below. image_path=None on the
        # Q1 (no --with-image) path -- the agent asking for a photo there is expected, correct
        # behavior for a question that never attached one, not a pipeline bug.
        turn_messages = agent.run_turn(english_query, image_path=image_path, verbose=True)
        return turn_messages[-1].content

    english_answer = orch.run_agent(_agent_call)
    print(f"[PIPE] agent answer (English): {english_answer}")

    if language == "en":
        target_text = english_answer
    else:
        def _nmt_to_target_call():
            r = requests.post(
                f"{GATEWAY}/nmt/infer",
                json={"text": english_answer, "src_lang": "EN", "tgt_lang": language, "long": True},
                timeout=30,
            )
            r.raise_for_status()
            return r.json()["translated_text"]

        # keep_loaded=True here too: leave the eviction decision to run_tts's Rule 2 check,
        # which will unload it right before TTS's peak rather than eagerly right now.
        target_text = orch.run_nmt(f"EN->{language}", _nmt_to_target_call, keep_loaded=True)
        print(f"[PIPE] translated answer ({language}): {target_text}")

    tts_batch_size = config.WORKERS["tts"]["default_batch_size"]

    def _tts_call():
        r = requests.post(
            f"{GATEWAY}/tts/infer",
            json={"text": target_text, "language": cfg["tts_name"], "batch_size": tts_batch_size},
            timeout=180,
        )
        r.raise_for_status()
        return r.json()

    def _tts_call_streaming():
        # Real incremental playback through the actual gateway -- /tts/infer_stream, not the
        # blocking /tts/infer _tts_call() above uses. See TTS_HTTP_STREAMING_RESULTS.md for
        # what this actually buys (real measured time-to-first-audio) and two real bugs found
        # getting it to be stall-free. Deliberately NOT the default path (--stream-tts opts
        # in) -- /tts/infer stays the simpler, more proven fallback if streaming ever causes
        # a problem in practice (context loss across batches, network reliability on a real
        # device, etc.) that hasn't shown up in dev-machine testing yet.
        if not _HAS_SOUNDDEVICE:
            raise RuntimeError(
                "--stream-tts needs the optional `sounddevice` package (playback is the "
                "whole point of this path) -- pip install sounddevice, or drop --stream-tts "
                "to use the non-streaming /tts/infer path instead."
            )
        handle = play_http_stream(
            GATEWAY, target_text, language=cfg["tts_name"], batch_size=tts_batch_size,
            backend="sounddevice", blocking=True, debug=False,
        )
        audio, sample_rate = handle.full_audio()
        buf = io.BytesIO()
        sf.write(buf, audio, sample_rate, format="WAV")
        return {
            "audio_base64": base64.b64encode(buf.getvalue()).decode("utf-8"),
            "sample_rate": sample_rate,
            "language": cfg["tts_name"],
            "engine": f"{config.WORKERS['tts']['engine']}_streaming",
            "num_chunks": len(handle.chunks),
        }

    if stream_tts:
        tts_result = orch.run_tts(cfg["tts_name"], _tts_call_streaming, batch_size=tts_batch_size)
    else:
        tts_result = orch.run_tts(cfg["tts_name"], _tts_call, batch_size=tts_batch_size)

    out_dir = Path(AGENTS_DIR) / "sample_audio" / "pipeline_outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"orchestrated_{language}.wav"
    with open(out_path, "wb") as f:
        f.write(base64.b64decode(tts_result["audio_base64"]))
    # "batch_size" is parler-only (mms_tts never batches -- see tts_worker.py's module
    # docstring) and "engine" can differ per call now (mms_tts / parler / parler_fallback,
    # the last one when the requested language has no real MMS-TTS checkpoint -- see
    # config.MMS_TTS_UNSUPPORTED_INDIAN_LANGUAGES) -- .get() both rather than assuming
    # every response shares parler's shape.
    batch_note = f", batch_size={tts_result['batch_size']}" if "batch_size" in tts_result else ""
    print(
        f"[PIPE] audio written to {out_path} "
        f"(engine={tts_result.get('engine', '?')}, {tts_result['num_chunks']} chunks{batch_note})"
    )
    # stream_tts already played live, inside orch.run_tts()'s timed call above -- playing
    # play_audio(out_path) again here would be a second, redundant full playback.
    if play and not stream_tts:
        play_audio(out_path)
    print(f"[PIPE] total turn wall-clock: {time.perf_counter() - turn_t0:.2f}s")

    return {
        "english_query": english_query,
        "english_answer": english_answer,
        "target_text": target_text,
        "audio_path": str(out_path),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--language", choices=list(LANGUAGES), default="hi")
    parser.add_argument("--all", action="store_true", help="run every language back to back, one session")
    parser.add_argument("--no-play", action="store_true", help="save the .wav but skip live playback")
    parser.add_argument("--with-image", action="store_true",
                         help="use Q2 (\"what's wrong with this plant\") + the sample photo instead of Q1")
    parser.add_argument("--stream-tts", action="store_true",
                         help="use the new /tts/infer_stream path (real incremental playback, lower "
                              "time-to-first-audio -- see TTS_HTTP_STREAMING_RESULTS.md) instead of the "
                              "default blocking /tts/infer + play-after-complete path. Opt-in, not the "
                              "default -- /tts/infer stays the simpler, more proven fallback.")
    args = parser.parse_args()

    gateway_proc = subprocess.Popen(
        [sys.executable, "run_all.py"], cwd=os.path.join(AGENTS_DIR, "api_server")
    )
    try:
        if not wait_for_gateway():
            print("gateway did not become healthy in time", file=sys.stderr)
            return 1

        orch = MemoryOrchestrator()
        agent = GramSahayakAgent()
        banner("INITIAL STATE (nothing loaded)")
        orch._snapshot_line("startup")

        languages = list(LANGUAGES) if args.all else [args.language]
        for lang in languages:
            run_full_pipeline(lang, orch, agent, play=not args.no_play, with_image=args.with_image,
                               stream_tts=args.stream_tts)

        banner("SESSION TEARDOWN")
        orch.teardown()

    finally:
        gateway_proc.terminate()
        try:
            gateway_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            gateway_proc.kill()

    return 0


if __name__ == "__main__":
    sys.exit(main())
