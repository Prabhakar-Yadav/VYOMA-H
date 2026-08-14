"""Lazy re-exports (2026-08-13). `chunk_text`/`clean_text` (models/tts_exports/streaming.py)
are engine-agnostic text-chunking utilities used by BOTH the mms_tts engine (the only one
actually used in real production, per this date's finding) and the rare 8-language Parler
fallback -- but eagerly importing this whole package at their use site
(api_server/workers/tts_worker.py's `_infer_mms_tts`, hit on every real MMS-only request) used
to unconditionally drag in Parler's entire dependency chain too: `model_loader.py`'s own
`from parler_tts import ...` -> `parler_tts` -> `dac` -> `audiotools` -> `torchaudio`, and
`torchaudio` runs an eager, unconditional CUDA-version check at import time that raises
`RuntimeError` (not a gracefully-catchable `ImportError`) if its own build doesn't match
torch's -- confirmed as a REAL crash on this Jetson recovery (torch built for CUDA 13.2,
`pip install torchaudio` with no explicit version pin grabbed a CUDA-13.0 build instead).
Real, confirmed via a direct traceback: a plain Hindi `/tts/infer` call (pure MMS-TTS, zero
functional need for Parler) failed with that exact torchaudio error, purely because
`chunk_text`'s import chain forced this package's `__init__.py` to run first (Python always
initializes a package before any of its submodules, so even `from models.tts_exports.streaming
import chunk_text` -- which looks like it bypasses this file -- does not).

PEP 562 module `__getattr__` below keeps every existing `from models.tts_exports import X`
import working unchanged, but defers each submodule's actual import until one of its names is
genuinely accessed -- so `chunk_text`/`clean_text` (needed by every real MMS-TTS call) stay
fully decoupled from `QuantizedParlerTTS`/parler-flavored `TTSInferencer`/`StreamingTTS` (only
needed by the rare Parler fallback path), and a broken Parler dependency chain can no longer
break MMS-TTS at all."""
import importlib

_LAZY_ATTRS = {
    "QuantizedParlerTTS": ".model_loader",
    "TTSInferencer": ".inference",
    "BEST_SPEAKERS": ".inference",
    "FEMININE_SPEAKERS": ".inference",
    "StreamingTTS": ".streaming",
    "clean_text": ".streaming",
    "chunk_text": ".streaming",
}

__all__ = list(_LAZY_ATTRS)


def __getattr__(name):
    if name in _LAZY_ATTRS:
        module = importlib.import_module(_LAZY_ATTRS[name], __name__)
        value = getattr(module, name)
        globals()[name] = value  # cache on this package module so repeat access is instant
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
