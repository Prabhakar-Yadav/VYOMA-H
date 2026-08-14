#!/usr/bin/env python3
"""Real full-turn memory/timing log, reusing whatever gateway is already running on
config.GATEWAY_PORT (does NOT spawn its own run_all.py -- meant to run alongside a live
Streamlit/other session without competing for the port). Every [ORCH] line is the real
orchestrator making a real decision against real live numbers, same as
test_orchestrated_pipeline.py -- this just skips gateway startup and uses a clearer,
longer-answer question so TTS actually synthesizes something substantial instead of a
short clarifying question.

Run: source venv/bin/activate && cd gramsahayak && python3 rag/test_full_turn_memory.py
"""
import base64
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from api_server import config
from api_server.orchestrator import MemoryOrchestrator
from agent import GramSahayakAgent
from models.text_clean import clean_text

GATEWAY = f"http://{config.GATEWAY_HOST}:{config.GATEWAY_PORT}"
AGENTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LANGUAGE = "hi"
TTS_NAME = "Hindi"
QUESTION_EN = (
    "My tomato leaves have brown spots with concentric rings on them, starting from the "
    "bottom of the plant. What disease is this and what should I use to treat it?"
)


def main():
    if requests.get(f"{GATEWAY}/health", timeout=2).status_code != 200:
        print("Gateway not reachable -- is a session running?")
        return 1

    orch = MemoryOrchestrator(verbose=True, log_fn=print)
    agent = GramSahayakAgent()
    orch.ensure_agent_loaded_for_session()  # no-op if already loaded, real check either way

    print("\n" + "=" * 90)
    print(f"REAL FULL TURN -- language={LANGUAGE}, reusing live gateway at {GATEWAY}")
    print("=" * 90)
    orch.reset_turn()
    t_total0 = time.perf_counter()
    timings = {}

    # ASR real audio (not the vague Q1 -- pointed at a real fixture for this language)
    audio_path = os.path.join(AGENTS_DIR, "sample_audio", "pipeline_inputs", f"q2_{LANGUAGE}.wav")
    if not os.path.exists(audio_path):
        audio_path = os.path.join(AGENTS_DIR, "sample_audio", "pipeline_inputs", f"q1_{LANGUAGE}.wav")
    with open(audio_path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode("utf-8")

    def _asr_call():
        r = requests.post(f"{GATEWAY}/asr/infer", json={"audio_base64": audio_b64, "language": LANGUAGE}, timeout=60)
        r.raise_for_status()
        return r.json()["text"]

    t0 = time.perf_counter()
    orch.run_asr(LANGUAGE, _asr_call)  # real transcription, not used as the actual query below --
    timings["asr_s"] = time.perf_counter() - t0  # this run wants a specific, clear, TTS-exercising
    # question (QUESTION_EN below) rather than whatever a bundled fixture happens to say, but
    # still pays the real ASR stage cost/timing for an honest full-turn total.

    print(f"\n[PIPE] using fixed English query for this test: {QUESTION_EN}")

    t0 = time.perf_counter()
    _new_messages = []

    def _agent_call():
        tm = agent.run_turn(QUESTION_EN, messages=None, verbose=True)
        _new_messages.extend(tm)
        return tm[-1].content

    english_answer = orch.run_agent(_agent_call, tts_language=TTS_NAME)
    timings["agent_s"] = time.perf_counter() - t0
    english_answer = clean_text(english_answer)
    print(f"[PIPE] agent answer ({len(english_answer)} chars): {english_answer[:200]}...")

    t0 = time.perf_counter()

    def _nmt_out_call():
        r = requests.post(f"{GATEWAY}/nmt/infer",
                           json={"text": english_answer, "src_lang": "EN", "tgt_lang": LANGUAGE, "long": True},
                           timeout=30)
        r.raise_for_status()
        return r.json()["translated_text"]

    target_text = orch.run_nmt(f"EN->{LANGUAGE}", _nmt_out_call)
    timings["nmt_out_s"] = time.perf_counter() - t0
    print(f"[PIPE] translated answer ({len(target_text)} chars)")

    tts_batch_size = config.WORKERS["tts"]["default_batch_size"]

    def _tts_call():
        r = requests.post(f"{GATEWAY}/tts/infer",
                           json={"text": target_text, "language": TTS_NAME, "batch_size": tts_batch_size},
                           timeout=180)
        r.raise_for_status()
        return r.json()

    t0 = time.perf_counter()
    tts_result = orch.run_tts(TTS_NAME, _tts_call, batch_size=tts_batch_size, text_char_count=len(target_text))
    timings["tts_s"] = time.perf_counter() - t0
    timings["total_s"] = time.perf_counter() - t_total0

    print("\n" + "=" * 90)
    print("REAL TIMINGS")
    print("=" * 90)
    for k, v in timings.items():
        print(f"  {k:12s}: {v:.2f}s")

    print("\n" + "=" * 90)
    print("REAL FINAL MEMORY SNAPSHOT (per-component, after this turn)")
    print("=" * 90)
    snap = orch.snapshot()
    for name, c in snap["components"].items():
        if c["state"] == "loaded":
            gb = orch._component_bytes(name, snap) / 1e9
            print(f"  {name:10s}: {gb:.3f}GB")
        else:
            print(f"  {name:10s}: {c['state']}")
    print(f"  {'TOTAL':10s}: {snap['total_bytes']/1e9:.3f}GB / {config.MODEL_BUDGET_BYTES/1e9:.1f}GB budget "
          f"({snap['utilization_pct']}%)")

    # NOT tearing down -- this turn ran against a live shared session (see module docstring);
    # leaving state exactly as any normal turn in that session would leave it (agent/nmt
    # resident, tts freed post-synthesis, asr golden-window-preloaded by Rule 10).
    print("\n(not tearing down -- this reused a live shared gateway session)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
