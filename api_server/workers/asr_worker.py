"""ASR worker process -- wraps QuantizedMultiLangASR (models/asr/quantized_multilang_loader.py,
per-language INT8 ONNX, torch-free) behind the generic worker state machine. Run standalone for
debugging:
    uvicorn api_server.workers.asr_worker:app --port 11411
(the gateway spawns it exactly this way, from dev/agents/ as the working directory).

**2026-08-07: switched from the multilingual model (models/asr/model_loader.py, kept in-tree
for reference/rollback) to per-language quantized exports.** See
`models/asr/indic_quantized_asr.py`'s module docstring for the full rationale and real measured
numbers -- load time and memory both dropped by roughly an order of magnitude. Coverage is now
hi/ta/ml only (config.WORKERS["asr"]["languages"]), not all 22 scheduled languages the old model
supported -- a deliberate scope decision, not an oversight (these are the only three with real
audio test fixtures in this repo).
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
from models.asr.quantized_multilang_loader import QuantizedMultiLangASR

_cfg = config.WORKERS["asr"]


def _engine_factory():
    return QuantizedMultiLangASR(base_dir=_cfg["checkpoint_dir"], languages=_cfg["languages"])


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
