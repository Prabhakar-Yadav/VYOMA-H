#!/usr/bin/env python3
"""Convenience launcher: `python run_all.py` starts the gateway on :11400, which spawns
ASR/NMT/TTS worker subprocesses (lazily, on first /load -- see gateway.py) via its lifespan
hook. Ctrl-C (or SIGTERM) triggers uvicorn's own shutdown, which runs the lifespan's shutdown
half and stops any still-running worker subprocess.

Default log level is "warning", matching the workers -- the gateway's own per-request access
log (`GET /asr/status 200 OK` etc.) is pure noise once the orchestrator's own [ORCH] lines are
doing the real reporting; it doesn't accumulate or cost memory (each line is printed and
discarded, not retained), it's just visual clutter. Pass --verbose to get it back for
debugging the gateway/proxy layer itself.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # gramsahayak/

import uvicorn

from api_server import config

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true", help="restore per-request access logging")
    args = parser.parse_args()
    uvicorn.run(
        "api_server.gateway:app", host=config.GATEWAY_HOST, port=config.GATEWAY_PORT,
        log_level="info" if args.verbose else "warning",
    )
