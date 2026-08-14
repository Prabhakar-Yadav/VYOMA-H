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

**mms_tts's `/infer` path DOES chunk now, on the input-text side -- this reverses an earlier
design decision.** The original reasoning (VITS is non-autoregressive, no `max_new_tokens`
cap to chunk *generation* against) is true but was conflated with a different question: does
*peak memory* stay bounded regardless of how long the input text is? It doesn't -- confirmed
by a real device crash on a genuinely long (1200+ char) Hindi answer: the one-call-does-
everything design meant peak memory scaled with total text length (config.py's mms_tts block
documents two real single-call data points, 430 chars -> 2.53GB vs. 800 chars -> 3.67GB, a
real, meaningful scaling relationship, not the near-flat one originally assumed from a single
883-char measurement). Fix: reuse `chunk_text()` (the same sentence-boundary chunker
parler's path already used) to split input text into ~180-char pieces and call `synthesize()`
once per chunk, concatenating the results -- peak memory per call is now bounded by one
chunk's size, not the whole answer, regardless of how long the answer gets. Also makes
`/infer_stream` for mms_tts genuinely incremental (previously always exactly one chunk,
i.e. fake streaming) -- generation is much faster than playback (RTF ~0.025 measured on the
883-char case), so a caller using `/infer_stream` can now play chunk N while chunk N+1 is
still generating, the same real benefit parler's streaming path already had.

**Chunk size retuned 2026-08-08 for duration, not just memory.** `chunk_text()`'s own
default (180 chars) was sized purely as a memory-bounding heuristic and happened to produce
~14s chunks for Hindi -- fine for the crash it was fixing, not tuned for how a streaming
caller actually wants to pace generation-ahead-of-playback. `_mms_chunk_max_chars()` below
uses real measured chars/sec per language (`config.py`'s `chunk_max_chars_by_language`) to
target ~30s chunks instead. Parler's own `chunk_text()` calls elsewhere are untouched --
this only affects the mms_tts call sites here.

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


def _release_chunk_memory():
    """Called after every mms_tts chunk (2026-08-08) -- see `_infer_mms_tts`'s docstring for
    the real isolated measurement (isolate_tts_memory_test.py) that motivated this: a single
    long multi-chunk call was found growing system memory monotonically, never releasing it
    between chunks, because nothing ever called this between `synthesize()` calls before --
    only `model_loader.py`'s own `unload()` did, at the very end of the process's life.

    Deliberately `torch.cuda.empty_cache()` ONLY, not the fuller `gc.collect()` +
    `torch.cuda.synchronize()` + `malloc_trim(0)` combination `unload()` uses (which would
    reach a bit further into the real ~1GB-above-baseline floor this alone doesn't fully
    reclaim -- consistent with cuDNN's own algorithm/workspace cache, untouched by
    empty_cache(), plus glibc heap fragmentation from the chunk loop's churn). That fuller
    combination was tried here first and caused a real, severe Jetson hang (20+ minutes
    completely unreachable, not even answering ICMP -- see the incident notes around
    2026-08-08's qwen3.5:2b retest) while the *exact same code* ran clean on GX10 (real
    NVIDIA GB10, standard driver) in isolate_tts_gx10_v2.log -- strong evidence this is a
    Tegra/unified-memory-specific interaction (`malloc_trim(0)`'s raw glibc heap-trim
    conflicting with Jetson's own CUDA unified-memory manager), not a general torch problem.
    `empty_cache()` alone is proven safe on both platforms and still cuts real measured
    growth by ~30% (see the docstring history in git) -- not worth the risk of the extra
    ~1GB for a technique that has already caused one real device hang."""
    import torch
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


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

    def load(self, language=None):
        # `language=` (display name, e.g. "Hindi", or short code) is resolved to MMS-TTS's
        # own short code and forwarded -- lazy by default (2026-08-11 fix, see
        # MultiLangMmsTtsEngine.load()'s own docstring), eager for one language when the
        # caller (Rule 5's golden-window preload) already knows the turn's real target.
        # A language MMS-TTS doesn't support (the 8 fallback-to-Parler ones) is silently
        # not preloaded here -- Parler's own lazy `ensure_parler()` still covers it at
        # first real request, just without the golden-window head start those 8 never had
        # anyway (this class's own docstring already documents that as a known gap).
        code = None
        if language is not None:
            code, supported = _resolve_mms_language(language)
        self.mms.load(language=code if code else None)  # Parler stays unloaded until a
        # fallback language is actually requested

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


def _mms_chunk_max_chars(code):
    """Duration-aware chunk size for mms_tts specifically -- see config.py's
    chunk_max_chars_by_language comment for the real measured chars/sec calibration behind
    this (targets ~30s/chunk, not chunk_text()'s untuned 180-char/~14s default)."""
    by_lang = _ENGINE_CFG.get("chunk_max_chars_by_language", {})
    return by_lang.get(code, _ENGINE_CFG.get("chunk_max_chars_default", 180))


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
    """`engine` is a _HybridMmsParlerEngine. Dispatches per-language to MMS-TTS -- chunked
    into ~180-char sentence-boundary pieces (chunk_text(), same chunker parler's path uses),
    one synthesize() call per chunk, concatenated -- or, for the 8 confirmed-unsupported
    India languages, to a lazily-loaded Parler-TTS fallback (via synthesize_long() --
    paragraph-chunked, no batching -- this is a rare fallback path, not the hot path
    StreamingTTS optimizes). See this module's own docstring for why mms_tts chunks its
    input text now, despite VITS having no autoregressive generation to chunk against.

    Releases memory after every chunk (2026-08-08, see `_release_chunk_memory()`'s own
    docstring for the real isolated measurement -- isolate_tts_memory_test.py -- that
    motivated this and exactly what it does and doesn't reclaim) -- real isolated testing
    found a single long multi-chunk call growing system memory monotonically and
    substantially (+1.45GB over 27 chunks, never dropping) with NO corresponding growth from
    repeated *same-shaped* short calls (+11MB over 10 calls) -- textbook PyTorch CUDA
    caching-allocator behavior: each new, differently-shaped chunk (natural sentence-boundary
    chunks vary in length) can force the allocator to reserve additional memory it never
    voluntarily returns. On Jetson's unified memory that reserved pool *is* real system RAM,
    not a separate VRAM pool walled off from everything else -- confirmed this is exactly what
    pushed two real qwen3.5:2b multi-turn tests into severe swap-thrashing (see
    pipeline_hi_qwen2b_CRASHED_2026-08-08.log and its 15s-chunking retest, which made it
    *worse*, not better, since halving chunk duration roughly doubles the number of distinct
    varying-length shapes seen per call)."""
    from models.mms_tts import MmsTtsInferencer
    from models.tts_exports.streaming import chunk_text

    text = payload.get("text")
    language = payload.get("language")
    if not text or not language:
        raise ValueError("payload must include 'text' and 'language'")

    code, supported = _resolve_mms_language(language)

    if supported:
        lang_engine = engine.mms.get(code)
        tts = MmsTtsInferencer(lang_engine)
        chunks = chunk_text(text, sentence_lang=code, max_chunk_chars=_mms_chunk_max_chars(code)) or [text]
        audio_parts = []
        sample_rate = None
        for chunk in chunks:
            chunk_audio, sample_rate = tts.synthesize(chunk)
            audio_parts.append(chunk_audio)
            _release_chunk_memory()
        audio = audio_parts[0] if len(audio_parts) == 1 else np.concatenate(audio_parts)
        engine_used = "mms_tts"
        num_chunks_used = len(chunks)
    else:
        from models.tts_exports.inference import TTSInferencer
        parler_engine = engine.ensure_parler()
        parler_tts = TTSInferencer(parler_engine)
        audio, sample_rate = parler_tts.synthesize_long(text, language=language)
        engine_used = "parler_fallback"
        num_chunks_used = 1  # parler_fallback's internal paragraph chunking (synthesize_long)
        # isn't surfaced here -- kept for response-shape parity, unchanged from before

    buf = io.BytesIO()
    sf.write(buf, audio, sample_rate, format="WAV")
    audio_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return {
        "audio_base64": audio_b64,
        "sample_rate": sample_rate,
        "language": language,
        "engine": engine_used,
        "num_chunks": num_chunks_used,
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
    """Generator version of _infer_mms_tts -- used by `/infer_stream`. Now genuinely
    incremental for a supported language (previously always exactly one chunk -- see this
    module's own docstring for why that changed): chunks the input text the same way
    `_infer_mms_tts` does and yields one item per chunk as it's synthesized, instead of one
    call over the whole answer. Generation is much faster than playback (RTF ~0.025 measured
    on an 883-char case), so a real caller (streaming.py's play_http_stream()) can be playing
    chunk N while chunk N+1 is still generating. The fallback-to-Parler path for the 8
    unsupported languages already had multiple real chunks to stream, so it still delegates
    to `_stream_parler` rather than duplicating that logic. Same per-chunk
    `_release_chunk_memory()` as `_infer_mms_tts` (2026-08-08) -- see that function's
    docstring and `_release_chunk_memory()`'s own for the real measured cause and fix."""
    from models.mms_tts import MmsTtsInferencer
    from models.tts_exports.streaming import chunk_text

    text = payload.get("text")
    language = payload.get("language")
    if not text or not language:
        raise ValueError("payload must include 'text' and 'language'")

    code, supported = _resolve_mms_language(language)

    if supported:
        lang_engine = engine.mms.get(code)
        tts = MmsTtsInferencer(lang_engine)
        chunks = chunk_text(text, sentence_lang=code, max_chunk_chars=_mms_chunk_max_chars(code)) or [text]
        total = len(chunks)
        total_chars = sum(len(c) for c in chunks) or 1
        for idx, chunk in enumerate(chunks):
            audio, sample_rate = tts.synthesize(chunk)
            _release_chunk_memory()
            yield {
                "chunk_index": idx, "total_chunks": total, "total_chars": total_chars,
                "chunk_chars": len(chunk), "sample_rate": sample_rate,
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
