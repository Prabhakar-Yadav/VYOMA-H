"""NMT worker process -- wraps NMTEngine (dev/agents/models/nmt/model_loader.py) behind the
generic worker state machine. Run standalone for debugging:
    uvicorn api_server.workers.nmt_worker:app --port 11412
"""
import os
import re
import sys

_AGENTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _AGENTS_DIR not in sys.path:
    sys.path.insert(0, _AGENTS_DIR)

from api_server import config
from api_server.worker_base import make_worker_app
from models.nmt.model_loader import NMTEngine

_cfg = config.WORKERS["nmt"]

# ASCII digits surviving into an Indic-language answer are (mostly) unpronounceable
# downstream: MMS-TTS vocabs lack digit characters (hi: no 5/6/7/9, gu: none at all) and
# the VITS tokenizer silently drops them, so the farmer hears a gap where the number was.
# The pipeline verbalizes numbers pre-NMT (models/number_expansion.py), so a digit here
# means something escaped that net (letter-glued codes like B12, URLs, or a new answer
# shape) -- loud telemetry, not a silent gap. English targets are exempt: "en" output
# goes to the farmer verbatim for en sessions and digits there are the agent's own.
_DIGIT_LEAK_RE = re.compile(r"[0-9]")


def _engine_factory():
    return NMTEngine(checkpoint_root=_cfg["checkpoint_root"])


def _infer(engine, payload: dict) -> dict:
    text = payload.get("text")
    src_lang = payload.get("src_lang")
    tgt_lang = payload.get("tgt_lang")
    if not text or not src_lang or not tgt_lang:
        raise ValueError("payload must include 'text', 'src_lang', and 'tgt_lang'")

    if payload.get("long", False):
        result = engine.infer_long(text, src_lang, tgt_lang)
    else:
        result = engine.infer(text, src_lang, tgt_lang)

    if tgt_lang != "EN" and _DIGIT_LEAK_RE.search(result.get("translated_text", "")):
        print(
            f"[nmt] WARNING: translated {src_lang}->{tgt_lang} text still contains "
            f"ASCII digits -- these may be silent in TTS audio "
            f"(unexpanded: {result['translated_text'][:120]!r}...)",
            flush=True,
        )
    return result


app = make_worker_app("nmt", _engine_factory, _infer)
