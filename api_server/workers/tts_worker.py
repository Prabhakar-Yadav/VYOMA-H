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
import time

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


def _split_to_cap(piece, cap, min_piece):
    """Split one over-long text piece into pieces each <= `cap` chars. Cut order: deepest
    secondary punctuation inside the window (`,`, `;`, `:` -- sentence-final marks can't
    occur here, chunk_text() already split on those), then a word boundary, then a hard cut
    as a last resort. Never emits a piece below `min_piece`: a too-short tail is merged
    back into the previous piece instead of sounding clipped (VITS needs some utterance
    length for natural prosody). Used only by the /infer_stream path -- see
    `_stream_chunk_plan()`."""
    piece = piece.strip()
    if cap <= 0 or len(piece) <= cap:
        return [piece] if piece else []
    pieces = []
    rest = piece
    while len(rest) > cap:
        window = rest[:cap]
        cut = max(window.rfind(sep) for sep in (",", ";", ":"))
        if cut < min_piece:
            cut = window.rfind(" ")
        if cut < min_piece:
            cut = cap - 1
        head, rest = rest[:cut + 1].strip(), rest[cut + 1:].strip()
        if head:
            pieces.append(head)
    if rest:
        if pieces and len(rest) < min_piece:
            pieces[-1] += " " + rest
        else:
            pieces.append(rest)
    return pieces


def _stream_chunk_plan(text, code, payload):
    """Chunk plan for `/infer_stream` on an MMS-supported language -- NOT used by blocking
    /infer, which keeps its 30s chunks (fewer VITS passes = better cross-sentence prosody;
    see config's stream_* comment for why streaming deliberately trades that away).

    Layers, in order:
      1. chunk_text() -- existing sentence-boundary packer at `max_chunk_chars`
         (payload override, else config's stream_target_chunk_chars ~= 12s of speech).
      2. Oversize guard (`_split_to_cap` at stream_hard_max_chars): one NMT run-on
         sentence longer than this would reintroduce exactly the whole-answer latency
         streaming exists to fix.
      3. Fast start: chunk 0 re-split to stream_first_chunk_chars (~6-7s of Hindi speech)
         -- time-to-first-audio is proportional to chunk 0's generation time alone.

    `payload` may carry `max_chunk_chars` / `first_chunk_chars` to tune a call from the
    client side; absent keys fall back to config. Returns the final list of chunk strings."""
    target = int(payload.get("max_chunk_chars")
                 or _ENGINE_CFG.get("stream_target_chunk_chars", 140))
    first = int(payload.get("first_chunk_chars")
                or _ENGINE_CFG.get("stream_first_chunk_chars", 80))
    hard_max = int(_ENGINE_CFG.get("stream_hard_max_chars", 280))
    min_piece = int(_ENGINE_CFG.get("stream_min_piece_chars", 45))

    from models.tts_exports.streaming import chunk_text
    packed = chunk_text(text, sentence_lang=code, max_chunk_chars=target) or [text]
    guarded = []
    for piece in packed:
        guarded.extend(_split_to_cap(piece, hard_max, min_piece))
    if not guarded:
        return [text]
    # Cap chunk 0 even when it came back under `target` but over `first` -- a short answer
    # still deserves a fast first sound; _split_to_cap leaves short pieces untouched.
    return _split_to_cap(guarded[0], first, min_piece) + guarded[1:]


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


def _mms_voice_cfg(payload=None):
    """Voice-consistency settings for the mms_tts paths -- noise_scale/noise_scale_s/
    speaking_rate/seed go straight to VitsModel.forward(), the voice_match_* pair drives
    `_synthesize_voice_matched()`. Defaults live in config.py's mms_tts engine block
    (added 2026-08-23 for the measured cross-chunk voice-drift incident: a real streamed
    Hindi answer came back 122-155 Hz median F0 on chunks 0-2 and 195 Hz on chunk 3 --
    audibly a different speaker -- because each chunk is an independent unseeded VITS draw).
    Payload keys of the same name override config per call, same pattern as
    max_chunk_chars/first_chunk_chars in `_stream_chunk_plan()`."""
    cfg = {
        "noise_scale": _ENGINE_CFG.get("noise_scale"),
        "noise_scale_s": _ENGINE_CFG.get("noise_scale_s"),
        "speaking_rate": _ENGINE_CFG.get("speaking_rate"),
        "seed": _ENGINE_CFG.get("seed"),
        "voice_match_tolerance": _ENGINE_CFG.get("voice_match_tolerance", 0.15),
        "voice_match_max_retries": _ENGINE_CFG.get("voice_match_max_retries", 2),
    }
    if payload:
        for key in ("noise_scale", "noise_scale_s", "speaking_rate", "seed"):
            if payload.get(key) is not None:
                cfg[key] = payload[key]
    return cfg


def _chunk_f0_median(audio, sample_rate, fmin=60.0, fmax=400.0):
    """Median F0 over voiced frames of one synthesized chunk, plain numpy autocorrelation --
    no extra dependency (the worker venv has numpy; librosa/crepe are not installed here).

    Analyzes at most a central 8s window regardless of chunk length so the cost is bounded
    (~1500 frames worst case, well under the 0.4-0.6s a retry would spend re-synthesizing);
    within a single VITS pass the voice doesn't wander mid-chunk the way it does BETWEEN
    passes, so a central window is representative. Returns None when there isn't enough
    voiced material to trust (silence, <5 voiced frames) -- callers must treat that as
    "no opinion", never as a match failure."""
    x = np.asarray(audio, dtype=np.float64).flatten()
    if x.size < sample_rate // 2:
        return None
    window = 8 * sample_rate
    if x.size > window:
        start = (x.size - window) // 2
        x = x[start:start + window]
    peak = np.max(np.abs(x))
    if peak < 1e-6:
        return None
    x = x / peak

    frame = int(0.04 * sample_rate)
    hop = int(0.02 * sample_rate)
    lo = int(sample_rate / fmax)
    hi = min(int(sample_rate / fmin), frame - 1)
    f0s = []
    for i in range(0, x.size - frame, hop):
        fr = x[i:i + frame]
        if np.sqrt(np.mean(fr * fr)) < 0.02:
            continue
        fr = fr - fr.mean()
        ac = np.correlate(fr, fr, "full")[frame - 1:]
        ac = ac / (ac[0] + 1e-12)
        seg = ac[lo:hi]
        k = int(np.argmax(seg))
        if seg[k] < 0.35:
            continue
        f0s.append(sample_rate / (lo + k))
    if len(f0s) < 5:
        return None
    return float(np.median(f0s))


def _synthesize_voice_matched(tts, chunk, ref_f0, voice_cfg):
    """Synthesize one mms_tts chunk, re-drawing it up to `voice_match_max_retries` times
    when its median F0 drifts beyond `voice_match_tolerance` (relative) from `ref_f0`,
    keeping whichever attempt landed closest.

    This bounds exactly the 2026-08-23 incident (chunks 0-2 at 122-155 Hz, chunk 3 at
    195 Hz): with default sampling each chunk is an independent draw, so any per-answer
    guarantee needs a check-and-redraw loop, not just luck. `ref_f0=None` (chunk 0 of an
    answer, or every prior chunk unvoiced) means there is nothing to match against yet --
    exactly one synthesis, no retries; chunk 0 IS the reference the rest of the answer
    matches. Each attempt goes through `_release_chunk_memory()` like the plain loops did,
    since retries add differently-shaped allocations to the CUDA caching allocator (the
    real growth mechanism documented on `_infer_mms_tts`).

    Returns (audio, sample_rate, f0_median_or_None, tries)."""
    synth_kwargs = {
        "noise_scale": voice_cfg.get("noise_scale"),
        "noise_scale_s": voice_cfg.get("noise_scale_s"),
        "speaking_rate": voice_cfg.get("speaking_rate"),
        "seed": voice_cfg.get("seed"),
    }
    tolerance = voice_cfg.get("voice_match_tolerance", 0.15)
    attempts = 1 + (int(voice_cfg.get("voice_match_max_retries", 2)) if ref_f0 is not None else 0)

    first_audio = first_sr = None
    best_audio = best_sr = None
    best_f0 = None
    best_dev = float("inf")
    tries = 0
    for attempt in range(attempts):
        tries = attempt + 1
        audio, sr = tts.synthesize(chunk, **synth_kwargs)
        _release_chunk_memory()
        if first_audio is None:
            first_audio, first_sr = audio, sr
        f0 = _chunk_f0_median(audio, sr)
        dev = abs(f0 - ref_f0) / ref_f0 if (ref_f0 and f0 is not None) else float("inf")
        # `best_audio is None or` matters: with no reference yet (chunk 0) dev is inf and
        # would never beat itself -- without that guard the first draw's measured F0 got
        # thrown away, leaving chunk 0 unreported AND the rest of the answer matching
        # against chunk 1's voice instead of the one the farmer heard first.
        if best_audio is None or dev < best_dev:
            best_audio, best_sr, best_f0, best_dev = audio, sr, f0, dev
        if dev <= tolerance:
            break

    if best_audio is None:  # every read came back unvoiced -- keep the first draw
        best_audio, best_sr, best_f0, best_dev = first_audio, first_sr, None, float("inf")
    return best_audio, best_sr, best_f0, tries


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
        voice_cfg = _mms_voice_cfg(payload)
        accepted_f0s = []  # running reference: each chunk matches the median of the ones before it
        audio_parts = []
        sample_rate = None
        voice_tries_total = 0
        for chunk in chunks:
            ref_f0 = float(np.median(accepted_f0s)) if accepted_f0s else None
            chunk_audio, sample_rate, f0, tries = _synthesize_voice_matched(tts, chunk, ref_f0, voice_cfg)
            voice_tries_total += tries
            if f0 is not None:
                accepted_f0s.append(f0)
            audio_parts.append(chunk_audio)
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
    result = {
        "audio_base64": audio_b64,
        "sample_rate": sample_rate,
        "language": language,
        "engine": engine_used,
        "num_chunks": num_chunks_used,
    }
    if engine_used == "mms_tts":
        # Voice-consistency telemetry (2026-08-23): median F0 of every accepted chunk and
        # how many synthesis attempts the matcher spent -- lets a caller (or a log reader)
        # see drift and retries without decoding the audio. Additive keys; parler_fallback
        # has no VITS draws to report on.
        result["chunk_f0_medians"] = [round(f, 1) for f in accepted_f0s]
        result["voice_match_tries"] = voice_tries_total
    return result


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
    """Generator version of _infer_mms_tts -- used by `/infer_stream`. Genuinely
    incremental: yields one item per synthesized chunk as it finishes, so a caller can play
    chunk N while chunk N+1 generates.

    Chunks come from `_stream_chunk_plan()` -- NOT the same sizes blocking /infer uses:
    a small chunk 0 minimizes time-to-first-audio, later chunks stay moderate (~12s of
    speech), oversize-guarded against run-on sentences. Blocking /infer deliberately keeps
    its larger, prosody-friendlier chunks; see both functions' config comments for the
    tradeoff.

    Per-chunk `synth_s` (2026-08-22): server-side wall clock of that chunk's synthesize()
    call, so a client can separate generation time from its own queue/playback waits when
    accounting for stalls. Same per-chunk `_release_chunk_memory()` as `_infer_mms_tts`
    (2026-08-08) -- see that function's docstring and `_release_chunk_memory()`'s own for
    the real measured cause and fix.

    Per-chunk F0 voice-matching (2026-08-23): streaming's ~12s chunks mean MORE independent
    VITS draws per answer than blocking /infer's 30s chunks, which is exactly where the
    measured voice-drift incident came from (chunks 0-2 at 122-155 Hz median F0, chunk 3 at
    195 Hz). Each chunk now redraws until it matches the running median of its predecessors --
    `_synthesize_voice_matched()`; a retrying chunk's `synth_s` includes those extra draws,
    which is fine: at RTF ~0.1 even 3 attempts stay well inside one chunk's playback time."""
    from models.mms_tts import MmsTtsInferencer

    text = payload.get("text")
    language = payload.get("language")
    if not text or not language:
        raise ValueError("payload must include 'text' and 'language'")

    code, supported = _resolve_mms_language(language)

    if supported:
        lang_engine = engine.mms.get(code)
        tts = MmsTtsInferencer(lang_engine)
        chunks = _stream_chunk_plan(text, code, payload)
        voice_cfg = _mms_voice_cfg(payload)
        accepted_f0s = []  # running reference: each chunk matches the median of the ones before it
        total = len(chunks)
        total_chars = sum(len(c) for c in chunks) or 1
        for idx, chunk in enumerate(chunks):
            ref_f0 = float(np.median(accepted_f0s)) if accepted_f0s else None
            synth_t0 = time.monotonic()
            audio, sample_rate, f0, tries = _synthesize_voice_matched(tts, chunk, ref_f0, voice_cfg)
            synth_s = time.monotonic() - synth_t0
            if f0 is not None:
                accepted_f0s.append(f0)
            yield {
                "chunk_index": idx, "total_chunks": total, "total_chars": total_chars,
                "chunk_chars": len(chunk), "sample_rate": sample_rate,
                "synth_s": round(synth_s, 3),
                # Voice-consistency telemetry (2026-08-23): this chunk's median F0 and how
                # many draws the matcher spent on it -- the client's end-of-stream report
                # surfaces both so drift/retries are visible per turn without decoding audio.
                "f0_median": round(f0, 1) if f0 is not None else None,
                "voice_tries": tries,
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
