"""TTS worker process -- wraps whichever engine `config.WORKERS["tts"]["engine"]` selects
(`mms_tts` by default, `parler` the previous engine) behind the generic worker state
machine. Run standalone for debugging:
    uvicorn api_server.workers.tts_worker:app --port 11413

**Engine selection is config-driven, not a build-time choice** -- flip `config.TTS_ENGINE`
("mms_tts" or "parler") and restart the worker; nothing else in the gateway/orchestrator
needs to change (see config.py's own comment for why: WORKERS["tts"] flattens the active
engine's settings to the same keys the rest of the codebase already reads). See
`dev/agents/MMS_TTS_EVALUATION.md` for the real, measured comparison that made `mms_tts`
the default.

**Why mms_tts's `/infer` path has no batching/chunking, unlike parler's**: MMS-TTS (VITS)
is a non-autoregressive, single-forward-pass model -- no `max_new_tokens` cap to chunk
against, no autoregressive decode loop for batching to speed up. Confirmed directly: one
plain `synthesize()` call handles a real 883-char multi-paragraph Hindi answer (the same
real answer `test_streaming_tts_only.py` uses) in 1.64s, producing 64.78s of audio (RTF
0.025), peak 1.24GB/1.66GB -- see MMS_TTS_EVALUATION.md section 7. `chunk_text()` /
`StreamingTTS` / `batch_size` all remain parler-only machinery.

**Per-language fallback to Parler-TTS, when engine="mms_tts"**: MMS-TTS does not have real
checkpoints for every one of India's 22 8th-Schedule languages -- confirmed directly against
MMS's own published language-coverage table, not assumed from a headline count. 8 of 22 are
missing entirely: Bodo, Kashmiri, Konkani, Manipuri, Nepali, Sanskrit, Santali, Sindhi (see
`config.MMS_TTS_UNSUPPORTED_INDIAN_LANGUAGES`). `_HybridMmsParlerEngine` below routes a
request for any of those to Parler-TTS instead, loaded lazily (only the first time one is
actually requested) so the common case -- a language MMS-TTS does support -- never pays
Parler's much larger footprint. This only applies when `engine="mms_tts"`; with
`engine="parler"`, every language already goes through Parler directly (no fallback logic
needed, that IS the primary path).
"""
import base64
import io
import os
import sys

_AGENTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _AGENTS_DIR not in sys.path:
    sys.path.insert(0, _AGENTS_DIR)

import numpy as np
import soundfile as sf

from api_server import config
from api_server.worker_base import make_worker_app

_cfg = config.WORKERS["tts"]
_ENGINE_NAME = _cfg["engine"]
_ENGINE_CFG = _cfg["engines"][_ENGINE_NAME]
_PARLER_CFG = _cfg["engines"]["parler"]  # always present regardless of active engine --
# needed by _HybridMmsParlerEngine for its lazy fallback load even when engine="mms_tts".

# TTSInferencer/StreamingTTS (parler) or MmsTtsInferencer (mms_tts) just wrap an engine
# instance -- rebuilt alongside it on every load, held here rather than reconstructed per
# request. `streaming` is parler-only (see _infer_parler's branch below); mms_tts never
# populates it.
_holder = {"streaming": None, "engine": None}


class _HybridMmsParlerEngine:
    """Routes each /infer request to MMS-TTS (fast path, the common case) or Parler-TTS
    (fallback, for the 8 India languages MMS-TTS has no checkpoint for). See this module's
    own docstring for the full rationale.

    Satisfies the same `.is_loaded` / `.load()` / `.unload()` / `.vram_allocated_gb()`
    interface `worker_base.py`'s generic state machine expects, by composing a
    `MultiLangMmsTtsEngine` (eager) with a `QuantizedParlerTTS` (lazy -- only constructed
    and loaded the first time a fallback-language request actually arrives).

    Known limitation, not solved here: `config.PREDICTED_LOAD_COST_BYTES`'s pre-flight
    budget math assumes TTS's footprint is whatever `WORKERS["tts"]["engine"]`'s steady/peak
    numbers say -- it has no awareness that a fallback-language request can silently add
    Parler's much larger footprint mid-turn. Rare in practice (8 low-traffic languages out
    of this pipeline's real target set), but a real gap if one of those languages sees
    regular use -- worth a follow-up to `load_balancer_plan.md` if that happens.
    """

    def __init__(self, mms_checkpoint_root, mms_preload_languages, parler_checkpoint_dir):
        from models.mms_tts import MultiLangMmsTtsEngine
        self.mms = MultiLangMmsTtsEngine(checkpoint_root=mms_checkpoint_root, languages=mms_preload_languages)
        self._parler_checkpoint_dir = parler_checkpoint_dir
        self.parler = None  # lazy -- see class docstring

    @property
    def is_loaded(self):
        return self.mms.is_loaded

    def load(self):
        self.mms.load()  # Parler stays unloaded until a fallback language is actually requested

    def unload(self):
        self.mms.unload()
        if self.parler is not None:
            self.parler.unload()
            self.parler = None

    def vram_allocated_gb(self):
        total = self.mms.vram_allocated_gb() or 0.0
        if self.parler is not None:
            total += self.parler.vram_allocated_gb() or 0.0
        return total

    def ensure_parler(self):
        """Lazily constructs + loads Parler-TTS on first use. Real cost when this fires:
        ~3.2s load time, ~1.27-1.94GB steady VRAM on top of whatever MMS-TTS already holds
        -- see MMS_TTS_EVALUATION.md's head-to-head table for the full Parler figures."""
        if self.parler is None:
            from models.tts_exports.model_loader import QuantizedParlerTTS
            engine = QuantizedParlerTTS(checkpoint_dir=self._parler_checkpoint_dir)
            engine.load()
            self.parler = engine
        return self.parler


def _resolve_mms_language(language):
    """Returns (short_code_or_None, is_mms_supported: bool).

    Accepts either a full display name -- what real /tts/infer callers actually send
    (test_orchestrated_pipeline.py sends `cfg["tts_name"]`, e.g. "Hindi", to match Parler's
    own speaker-lookup convention) -- or one of this project's short codes (e.g. "hi")
    directly. Any language not recognized by either path (including the 8 confirmed-missing
    India languages) is treated as MMS-unsupported -- callers of _HybridMmsParlerEngine
    should route those to Parler."""
    from models.mms_tts import LANGUAGE_TO_REPO

    if language in config.MMS_TTS_UNSUPPORTED_INDIAN_LANGUAGES:
        return None, False
    code = config.MMS_TTS_LANGUAGE_NAME_TO_CODE.get(language, language)
    if code in LANGUAGE_TO_REPO:
        return code, True
    return None, False


def _engine_factory():
    if _ENGINE_NAME == "mms_tts":
        engine = _HybridMmsParlerEngine(
            mms_checkpoint_root=_ENGINE_CFG["checkpoint_root"],
            mms_preload_languages=_ENGINE_CFG.get("preload_languages"),
            parler_checkpoint_dir=_PARLER_CFG["checkpoint_dir"],
        )
    elif _ENGINE_NAME == "parler":
        from models.tts_exports.model_loader import QuantizedParlerTTS
        engine = QuantizedParlerTTS(checkpoint_dir=_ENGINE_CFG["checkpoint_dir"])
    else:
        raise ValueError(f"Unknown TTS engine {_ENGINE_NAME!r} -- expected 'mms_tts' or 'parler'")

    _holder["engine"] = engine
    _holder["streaming"] = None  # built lazily in _infer_parler, once engine.load() has run
    return engine


def _infer_mms_tts(engine, payload: dict) -> dict:
    """`engine` is a _HybridMmsParlerEngine. Dispatches per-language to MMS-TTS (single
    forward pass, no chunking/batching) or, for the 8 confirmed-unsupported India languages,
    to a lazily-loaded Parler-TTS fallback (via synthesize_long() -- paragraph-chunked, no
    batching -- this is a rare fallback path, not the hot path StreamingTTS optimizes)."""
    from models.mms_tts import MmsTtsInferencer

    text = payload.get("text")
    language = payload.get("language")
    if not text or not language:
        raise ValueError("payload must include 'text' and 'language'")

    code, supported = _resolve_mms_language(language)

    if supported:
        lang_engine = engine.mms.get(code)
        tts = MmsTtsInferencer(lang_engine)
        audio, sample_rate = tts.synthesize(text)
        engine_used = "mms_tts"
    else:
        from models.tts_exports.inference import TTSInferencer
        parler_engine = engine.ensure_parler()
        parler_tts = TTSInferencer(parler_engine)
        audio, sample_rate = parler_tts.synthesize_long(text, language=language)
        engine_used = "parler_fallback"

    buf = io.BytesIO()
    sf.write(buf, audio, sample_rate, format="WAV")
    audio_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return {
        "audio_base64": audio_b64,
        "sample_rate": sample_rate,
        "language": language,
        "engine": engine_used,
        "num_chunks": 1,  # mms_tts is always one call; parler_fallback's internal paragraph
        # chunking (synthesize_long) isn't surfaced here -- kept for response-shape parity
    }


def _infer_parler(engine, payload: dict) -> dict:
    from models.tts_exports.inference import TTSInferencer
    from models.tts_exports.streaming import StreamingTTS

    text = payload.get("text")
    language = payload.get("language")
    if not text or not language:
        raise ValueError("payload must include 'text' and 'language'")

    # Real batched generation, not the plain sequential synthesize_long() path -- this is
    # what actually exercises TTS's documented peak-memory behavior (see streaming.py's own
    # docstring and load_balancer_plan.md's Module Footprints table: ~3.70GB peak *reserved*
    # at batch=6, not the ~1.27GB steady-state a sequential call would show).
    batch_size = payload.get("batch_size", _ENGINE_CFG.get("default_batch_size", 6))

    if _holder["streaming"] is None or _holder["engine"] is not engine:
        _holder["streaming"] = StreamingTTS(TTSInferencer(engine))
        _holder["engine"] = engine

    chunks_audio = []
    sample_rate = None
    num_chunks = 0
    for audio, sr, _chunk_text, _idx, total in _holder["streaming"].synthesize_stream_chunks(
        text,
        language=language,
        speaker=payload.get("speaker"),
        gender=payload.get("gender"),
        description=payload.get("description"),
        batch_size=batch_size,
        solo_first_chunk=False,  # batch chunk 0 in too, so batch_size actually engages throughout
    ):
        sample_rate = sr
        chunks_audio.append(audio)
        num_chunks = total

    if not chunks_audio:
        raise RuntimeError("TTS produced no audio chunks")

    audio_full = np.concatenate(chunks_audio)
    buf = io.BytesIO()
    sf.write(buf, audio_full, sample_rate, format="WAV")
    audio_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return {
        "audio_base64": audio_b64,
        "sample_rate": sample_rate,
        "language": language,
        "engine": "parler",
        "batch_size": batch_size,
        "num_chunks": num_chunks,
    }


def _infer(engine, payload: dict) -> dict:
    if _ENGINE_NAME == "mms_tts":
        return _infer_mms_tts(engine, payload)
    return _infer_parler(engine, payload)


def _b64_wav(audio, sample_rate):
    buf = io.BytesIO()
    sf.write(buf, audio, sample_rate, format="WAV")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _stream_parler(engine, payload, engine_label="parler"):
    """Generator version of _infer_parler -- used by `/infer_stream`. Yields one dict per
    chunk/batch the moment `StreamingTTS.synthesize_stream_chunks()` produces it, instead of
    collecting every batch into a list first the way `_infer_parler` does. This is the whole
    reason `/infer_stream` exists: a caller (`streaming.py`'s `play_http_stream()`) can start
    playing the first batch while later ones are still generating, instead of waiting for the
    complete answer -- `/infer`'s response shape structurally cannot do this (a plain `return`
    only happens once, after everything is done). See ARCHITECTURE.md's TTS section for the
    real measured difference this makes."""
    from models.tts_exports.inference import TTSInferencer
    from models.tts_exports.streaming import StreamingTTS, chunk_text, _TTS_NAME_TO_ISO

    text = payload.get("text")
    language = payload.get("language")
    if not text or not language:
        raise ValueError("payload must include 'text' and 'language'")

    batch_size = payload.get("batch_size", _PARLER_CFG.get("default_batch_size", 6))
    # Same total_chars precompute play_stream() does locally -- the client-side buffering
    # math (streaming.py's _smart_prebuffer_playback) needs the true total up front, before
    # any chunk exists, to estimate how much to buffer before starting playback.
    sentence_lang = _TTS_NAME_TO_ISO.get(language)
    total_chars = sum(len(c) for c in chunk_text(text, sentence_lang=sentence_lang)) or 1

    if _holder["streaming"] is None or _holder["engine"] is not engine:
        _holder["streaming"] = StreamingTTS(TTSInferencer(engine))
        _holder["engine"] = engine

    for audio, sr, chunk_txt, idx, total in _holder["streaming"].synthesize_stream_chunks(
        text,
        language=language,
        speaker=payload.get("speaker"),
        gender=payload.get("gender"),
        description=payload.get("description"),
        batch_size=batch_size,
        solo_first_chunk=False,  # matches _infer_parler -- batch_size actually engages throughout
    ):
        yield {
            "chunk_index": idx, "total_chunks": total, "total_chars": total_chars,
            "chunk_chars": len(chunk_txt), "sample_rate": sr,
            "audio_base64": _b64_wav(audio, sr),
            "language": language, "engine": engine_label, "batch_size": batch_size,
        }


def _stream_mms_tts(engine, payload):
    """Generator version of _infer_mms_tts -- used by `/infer_stream`. mms_tts itself has
    nothing to stream (VITS's single forward pass yields the complete answer or nothing --
    see MMS_TTS_EVALUATION.md), so this always yields exactly one item for a supported
    language. The fallback-to-Parler path for the 8 unsupported languages genuinely does
    have multiple chunks to stream though, so it delegates to `_stream_parler` rather than
    collecting everything the way `_infer_mms_tts`'s fallback branch does."""
    from models.mms_tts import MmsTtsInferencer

    text = payload.get("text")
    language = payload.get("language")
    if not text or not language:
        raise ValueError("payload must include 'text' and 'language'")

    code, supported = _resolve_mms_language(language)

    if supported:
        lang_engine = engine.mms.get(code)
        tts = MmsTtsInferencer(lang_engine)
        audio, sample_rate = tts.synthesize(text)
        yield {
            "chunk_index": 0, "total_chunks": 1, "total_chars": len(text),
            "chunk_chars": len(text), "sample_rate": sample_rate,
            "audio_base64": _b64_wav(audio, sample_rate),
            "language": language, "engine": "mms_tts",
        }
    else:
        parler_engine = engine.ensure_parler()
        yield from _stream_parler(parler_engine, payload, engine_label="parler_fallback")


def _stream_infer(engine, payload: dict):
    if _ENGINE_NAME == "mms_tts":
        yield from _stream_mms_tts(engine, payload)
    else:
        yield from _stream_parler(engine, payload)


app = make_worker_app("tts", _engine_factory, _infer, stream_infer_fn=_stream_infer)
