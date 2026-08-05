"""NMT worker process -- wraps NMTEngine (dev/agents/models/nmt/model_loader.py) behind the
generic worker state machine. Run standalone for debugging:
    uvicorn api_server.workers.nmt_worker:app --port 11412
"""
import os
import sys

_AGENTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _AGENTS_DIR not in sys.path:
    sys.path.insert(0, _AGENTS_DIR)

from api_server import config
from api_server.worker_base import make_worker_app
from models.nmt.model_loader import NMTEngine

_cfg = config.WORKERS["nmt"]


def _engine_factory():
    return NMTEngine(checkpoint_root=_cfg["checkpoint_root"])


def _infer(engine, payload: dict) -> dict:
    text = payload.get("text")
    src_lang = payload.get("src_lang")
    tgt_lang = payload.get("tgt_lang")
    if not text or not src_lang or not tgt_lang:
        raise ValueError("payload must include 'text', 'src_lang', and 'tgt_lang'")

    if payload.get("long", False):
        return engine.infer_long(text, src_lang, tgt_lang)
    return engine.infer(text, src_lang, tgt_lang)


app = make_worker_app("nmt", _engine_factory, _infer)
