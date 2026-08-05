"""ASR worker process -- wraps IndicConformerASR (dev/agents/models/asr/model_loader.py)
behind the generic worker state machine. Run standalone for debugging:
    uvicorn api_server.workers.asr_worker:app --port 11411
(the gateway spawns it exactly this way, from dev/agents/ as the working directory).
"""
import base64
import os
import sys
import tempfile

_AGENTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _AGENTS_DIR not in sys.path:
    sys.path.insert(0, _AGENTS_DIR)

from api_server import config
from api_server.worker_base import make_worker_app
from models.asr.model_loader import IndicConformerASR

_cfg = config.WORKERS["asr"]


def _engine_factory():
    return IndicConformerASR(hf_cache_dir=_cfg["checkpoint_dir"])


def _infer(engine, payload: dict) -> dict:
    audio_b64 = payload.get("audio_base64")
    language = payload.get("language")
    if not audio_b64 or not language:
        raise ValueError("payload must include 'audio_base64' and 'language'")

    audio_bytes = base64.b64decode(audio_b64)
    with tempfile.NamedTemporaryFile(suffix=".wav") as f:
        f.write(audio_bytes)
        f.flush()
        text = engine.transcribe(f.name, language, decoding=payload.get("decoding", "ctc"))
    return {"text": text, "language": language}


app = make_worker_app("asr", _engine_factory, _infer)
