#!/usr/bin/env python3
"""Force a full clean slate: unload everything resident (Ollama's agent + embedder, and any
ASR/NMT/TTS worker still holding memory), whether or not a gateway process is currently alive
to ask nicely through.

Why this exists (2026-08-13): `orchestrator.py`'s own `teardown()` only unloads through a
*live* gateway (HTTP `/unload` calls) -- fine at the end of a clean run, useless if that run
crashed and took the gateway down with it, or if you're just starting a fresh test and Ollama
has a model resident with `keep_alive=-1` from an unrelated earlier session (confirmed real:
this is what caused a memory-accounting bug to resurface after being fixed once already --
`MemoryOrchestrator._component_bytes()`'s real per-load delta measurement only works for
components loaded *by this orchestrator instance*, so "agent already resident from before" is
a real, common gap this script closes by guaranteeing there's nothing already resident to find).

Talks to Ollama directly (`keep_alive=0` unload -- doesn't need the gateway at all), and to the
gateway's `/unload?full=true` for workers *if* one happens to be reachable (real, guaranteed
process-kill+respawn memory reclaim, see `worker_base.py`'s own docstring) -- but doesn't
require it. Falls back to directly `pkill`-ing any leftover `run_all.py`/worker subprocess by
pattern as a hard safety net, in case a previous run crashed uncleanly and left orphans no HTTP
call can reach anymore.

Usage: venv/bin/python reset_session.py
"""
import subprocess
import sys
import time

import requests

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from api_server import config  # noqa: E402


def _free_mb():
    out = subprocess.check_output(["free", "-m"]).decode()
    line = [l for l in out.splitlines() if l.startswith("Mem:")][0]
    parts = line.split()
    return int(parts[2]), int(parts[3])  # used, free


def unload_ollama():
    """2026-08-16: was `for model in config.OLLAMA_MODELS` -- a real, confirmed bug once
    AVAILABLE_AGENT_MODELS/AGENT_MODEL_CHOICE made it easy to have something OTHER than
    config.OLLAMA_MODELS[0] resident (e.g. a candidate loaded directly via an isolated test
    script, or a --agent-model test run): this only ever knew how to unload whatever config
    CURRENTLY names, not whatever's ACTUALLY loaded, so a real off-roster model (confirmed:
    4skl/gemma4-e2b-mtp:latest, loaded by a real isolated test, left resident at 5.18GB real
    RSS after config.py was edited to point AGENT_MODEL_CHOICE back at qwen3.5:2b) silently
    survived every "clean slate" call this script made, misreporting a dirty baseline as
    clean. Read the REAL resident set from /api/ps directly and unload everything found
    there, not a config-driven guess -- config.OLLAMA_MODELS is no longer consulted here at
    all."""
    print("--- unloading Ollama-served components (whatever's REALLY resident, not a config guess) ---")
    try:
        r = requests.get("http://127.0.0.1:11434/api/ps", timeout=5)
        resident = [m["name"] for m in r.json().get("models", [])]
    except requests.RequestException as exc:
        print(f"  Ollama unreachable ({exc}) -- nothing to unload or Ollama itself is down")
        return
    if not resident:
        print("  nothing resident")
        return
    for model in resident:
        try:
            r = requests.post(
                "http://127.0.0.1:11434/api/generate",
                json={"model": model, "keep_alive": 0}, timeout=15,
            )
            print(f"  {model}: unload requested (status {r.status_code})")
        except requests.RequestException as exc:
            print(f"  {model}: unload request failed ({exc})")
    # Ollama's own unload call returns before the model is actually gone (same real gotcha
    # orchestrator.py's own _unload() already works around) -- poll /api/ps until it's
    # actually empty, not just trust the response.
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            r = requests.get("http://127.0.0.1:11434/api/ps", timeout=5)
            still_loaded = [m["name"] for m in r.json().get("models", [])]
            if not still_loaded:
                print("  confirmed: nothing resident anymore")
                return
        except requests.RequestException:
            return
        time.sleep(0.3)
    print(f"  WARNING: still showing loaded after {15}s wait: {still_loaded}")


def unload_workers_via_gateway():
    gateway = f"http://{config.GATEWAY_HOST}:{config.GATEWAY_PORT}"
    try:
        requests.get(f"{gateway}/health", timeout=2).raise_for_status()
    except requests.RequestException:
        print("--- no live gateway found -- skipping graceful /unload, relying on pkill below ---")
        return
    print("--- live gateway found -- requesting full (process-kill) unload for each worker ---")
    for name in config.WORKERS:
        try:
            r = requests.post(f"{gateway}/{name}/unload", params={"full": "true"}, timeout=60)
            print(f"  {name}: {r.status_code} {r.json() if r.ok else r.text}")
        except requests.RequestException as exc:
            print(f"  {name}: unload call failed ({exc})")


def kill_orphans():
    """Hard safety net -- catches worker subprocesses left behind by a gateway that itself
    already died uncleanly (a crash that took down the gateway doesn't necessarily take its
    already-spawned worker children with it, depending on how the crash happened)."""
    print("--- pkill safety net for any leftover run_all.py / worker subprocess ---")
    patterns = ["run_all.py", "workers.asr_worker", "workers.nmt_worker", "workers.tts_worker"]
    for pat in patterns:
        result = subprocess.run(["pkill", "-f", pat], capture_output=True)
        if result.returncode == 0:
            print(f"  killed process(es) matching '{pat}'")
    time.sleep(1)


def main():
    before_used, before_free = _free_mb()
    print(f"Before: {before_used}MB used, {before_free}MB free\n")

    unload_ollama()
    unload_workers_via_gateway()
    kill_orphans()

    time.sleep(1)
    after_used, after_free = _free_mb()
    print(f"\nAfter:  {after_used}MB used, {after_free}MB free "
          f"(freed {before_used - after_used}MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
