#!/usr/bin/env python3
"""Exercises the checklist from API_DESIGN.md's "What 'test the API' means" section against
the real checkpoints already present in dev/agents/models/checkpoints/. Starts the gateway
(workers spawn lazily, on their first /load -- see gateway.py's module docstring), runs
through status/load/unload/reload/async/concurrent checks, prints a report, then tears
everything down.

Run from dev/agents/: `python -m api_server.test_api`
"""
import base64
import os
import subprocess
import sys
import time

import requests

AGENTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AGENTS_DIR)

from api_server import config  # noqa: E402

GATEWAY = f"http://{config.GATEWAY_HOST}:{config.GATEWAY_PORT}"
PASS, FAIL, INFO = "PASS", "FAIL", "INFO"
_results = []


def record(kind, label, detail=""):
    _results.append((kind, label, detail))
    print(f"[{kind:4s}] {label}{' -- ' + detail if detail else ''}")


def gb(n):
    return f"{(n or 0) / 1e9:.3f}GB"


def wait_for_gateway(timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{GATEWAY}/health", timeout=1.0)
            if r.status_code == 200:
                return True
        except requests.exceptions.RequestException:
            pass
        time.sleep(0.3)
    return False


def get_memory():
    return requests.get(f"{GATEWAY}/system/memory", timeout=10).json()


def load(name, mode=None):
    params = {"mode": mode} if mode else {}
    return requests.post(f"{GATEWAY}/{name}/load", params=params, timeout=120)


def unload(name):
    return requests.post(f"{GATEWAY}/{name}/unload", params={"full": "true"}, timeout=60)


def status(name):
    return requests.get(f"{GATEWAY}/{name}/status", timeout=10).json()


def main():
    gateway_proc = subprocess.Popen(
        [sys.executable, "run_all.py"], cwd=os.path.dirname(os.path.abspath(__file__))
    )
    try:
        if not wait_for_gateway():
            record(FAIL, "gateway startup", "did not become healthy in time")
            return 1
        record(PASS, "gateway healthy (workers not spawned yet -- lazy spawn)")

        # 1. Baseline -- with lazy spawn, "unloaded" now means genuinely zero cost, not just
        # a freshly-spawned-but-empty process. Assert rss_bytes == 0 exactly, not "close to
        # some baseline" -- there's no longer a baseline to be close to.
        baseline = get_memory()
        record(INFO, "baseline /system/memory", f"total={gb(baseline['total_bytes'])} "
                                                  f"util={baseline['utilization_pct']}%")
        if baseline["total_bytes"] == 0:
            record(PASS, "baseline total is exactly 0 bytes (no standing worker processes)")
        else:
            record(FAIL, "baseline total is exactly 0 bytes", f"got {gb(baseline['total_bytes'])}")

        for name in ("asr", "nmt", "tts"):
            st = status(name)
            if st["state"] == "unloaded" and st.get("pid") is None and st["rss_bytes"] == 0:
                record(PASS, f"{name} starts UNLOADED with no process running (pid=None, rss=0)")
            else:
                record(FAIL, f"{name} starts UNLOADED with no process running", f"got {st}")

        # 2 & 3. Load (cold -- spawns a fresh process) then unload (kills it entirely) each
        # component, twice each, to confirm repeated lazy-spawn cycles are reliable, not just
        # a one-shot fluke.
        for name in ("asr", "nmt", "tts"):
            for cycle in (1, 2):
                r = load(name)
                if r.status_code != 200 or r.json().get("state") != "loaded":
                    record(FAIL, f"{name} cold load (cycle {cycle})", f"status={r.status_code} body={r.text[:200]}")
                    continue
                load_time = r.json().get("load_time_sec")
                st = status(name)
                record(PASS, f"{name} loaded (cycle {cycle})",
                       f"server_load_time={load_time:.2f}s rss={gb(st['rss_bytes'])} vram={gb(st['vram_bytes'])}")

                r = unload(name)
                body = r.json()
                after = body.get("rss_after_bytes")
                if after == 0:
                    record(PASS, f"{name} unload returns to exactly 0 bytes (cycle {cycle})")
                else:
                    record(FAIL, f"{name} unload returns to exactly 0 bytes (cycle {cycle})", f"got {gb(after)}")
                st = status(name)
                if st["state"] == "unloaded" and st.get("pid") is None:
                    record(PASS, f"{name} genuinely unspawned after unload (cycle {cycle})")
                else:
                    record(FAIL, f"{name} genuinely unspawned after unload (cycle {cycle})", f"got {st}")

        # 4. Async load timing -- the golden-window mechanism itself, now against a cold spawn.
        t0 = time.time()
        r = load("nmt", mode="async")
        immediate_state = r.json().get("state")
        dispatch_time = time.time() - t0
        if immediate_state == "loading" and dispatch_time < 0.5:
            record(PASS, "nmt async load returns immediately", f"dispatch={dispatch_time:.3f}s")
        else:
            record(FAIL, "nmt async load returns immediately",
                   f"state={immediate_state} dispatch={dispatch_time:.3f}s")
        deadline = time.time() + 30
        while time.time() < deadline and status("nmt")["state"] == "loading":
            time.sleep(0.2)
        final = status("nmt")
        if final["state"] == "loaded":
            record(PASS, "nmt async load completes", f"load_time={final['load_time_sec']:.2f}s")
        else:
            record(FAIL, "nmt async load completes", f"final state={final}")

        # 5. Concurrent load: NMT already loaded above; async-load TTS (cold spawn) at the
        # same time as an NMT infer call, simulating the golden-window overlap.
        t0 = time.time()
        tts_resp = load("tts", mode="async")
        infer_resp = requests.post(
            f"{GATEWAY}/nmt/infer",
            json={"text": "Hello, how are you?", "src_lang": "EN", "tgt_lang": "hi"},
            timeout=30,
        )
        concurrent_elapsed = time.time() - t0
        if tts_resp.status_code == 200 and infer_resp.status_code == 200:
            record(PASS, "concurrent nmt-infer + tts-async-cold-spawn, no crash/race",
                   f"elapsed={concurrent_elapsed:.2f}s translated={infer_resp.json()}")
        else:
            record(FAIL, "concurrent nmt-infer + tts-async-cold-spawn, no crash/race",
                   f"tts={tts_resp.status_code} infer={infer_resp.status_code}/{infer_resp.text[:200]}")
        deadline = time.time() + 60
        while time.time() < deadline and status("tts")["state"] == "loading":
            time.sleep(0.3)
        tts_final = status("tts")
        record(INFO, "tts async cold-spawn (fired during nmt infer) final state", str(tts_final["state"]))

        # ASR infer smoke test against a real sample file.
        sample = os.path.join(AGENTS_DIR, "sample_audio", "hindi_50w.wav")
        if os.path.exists(sample) and status("asr")["state"] != "loaded":
            load("asr")
        if os.path.exists(sample):
            with open(sample, "rb") as f:
                audio_b64 = base64.b64encode(f.read()).decode("utf-8")
            r = requests.post(f"{GATEWAY}/asr/infer", json={"audio_base64": audio_b64, "language": "hi"}, timeout=60)
            if r.status_code == 200:
                record(PASS, "asr infer smoke test", str(r.json())[:200])
            else:
                record(FAIL, "asr infer smoke test", f"{r.status_code} {r.text[:200]}")

        # infer without loading -> expect 409, not a crash, not an accidental spawn.
        unload("nmt")
        r = requests.post(f"{GATEWAY}/nmt/infer", json={"text": "hi", "src_lang": "EN", "tgt_lang": "hi"}, timeout=10)
        if r.status_code == 409:
            record(PASS, "infer on unloaded (unspawned) model returns 409, not a crash")
        else:
            record(FAIL, "infer on unloaded (unspawned) model returns 409, not a crash", f"got {r.status_code}")

        # status/health must never themselves cause a spawn -- confirm nmt is still unspawned
        # after the 409 check above and a few status polls.
        for _ in range(3):
            status("nmt")
        st = status("nmt")
        if st.get("pid") is None:
            record(PASS, "polling /status repeatedly never spawns a process")
        else:
            record(FAIL, "polling /status repeatedly never spawns a process", f"got {st}")

        final_mem = get_memory()
        record(INFO, "final /system/memory", f"total={gb(final_mem['total_bytes'])} "
                                              f"util={final_mem['utilization_pct']}%")

    finally:
        for name in ("asr", "nmt", "tts"):
            try:
                unload(name)
            except requests.exceptions.RequestException:
                pass
        gateway_proc.terminate()
        try:
            gateway_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            gateway_proc.kill()

    n_fail = sum(1 for kind, _, _ in _results if kind == FAIL)
    n_pass = sum(1 for kind, _, _ in _results if kind == PASS)
    print(f"\n{n_pass} passed, {n_fail} failed")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
