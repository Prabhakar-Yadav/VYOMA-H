"""Wraps `indic_quantized_asr.IndicConformerASR` (one instance per language) behind the same
engine interface `worker_base.py`/`asr_worker.py` already expect (`.is_loaded`, `.load()`,
`.unload()`, `.vram_allocated_gb()`, `.transcribe(path, lang, decoding=...)`) -- so swapping
this in for the old `model_loader.IndicConformerASR` (multilingual, torch+onnxruntime-CUDA)
needed a one-line change in `asr_worker.py` and nothing else in the gateway/orchestrator stack.

**Lazy per-language loading in `transcribe()`, not eager in `load()`** (changed 2026-08-09,
reverting the original eager design) -- `load()` now just marks the engine ready; each
language's ONNX session is only actually created the first time that language is transcribed,
and stays resident for the rest of the session after that (same "load once, reuse" semantics,
just deferred to first real use per language instead of assumed up front for all of them).

Why the reversal: the original eager design ("affordable to load hi+ta+ml together since each
is only ~300MB") was true on its own terms but ignored that most real sessions -- including
every test in this repo, which always passes a single `--language` -- only ever need ONE of
the three. Confirmed directly: a Malayalam-only session was eagerly loading hi+ta+ml anyway
(+308.5MB, +243.6MB, +235.6MB -- ~780MB total for one language actually used), a real, visible
waste with nothing gained since each language's own load is already fast (~0.6-0.7s) even
loaded cold on first use. A genuinely multi-language-serving deployment (unlike this repo's
single-language-per-session tests) would now pay that ~0.6-0.7s once per language on its first
request instead of all up front -- a real, deliberate tradeoff, favoring the common case over
the multi-language one now that per-language load is cheap enough not to need eager preloading.

Only CTC exists in these exports -- `decoding="rnnt"` isn't a smaller/slower fallback here, it's
simply not implemented; `transcribe()` raises a clear error rather than silently ignoring the
argument.

**`load(language=...)` (2026-08-11)** -- real regression found and fixed: orchestrator.py's
Rule 10 golden-window preload (`preload_asr()`) calls the worker's `/load` with no language at
all, which after the 2026-08-09 lazy-load change above just marks the engine "ready" and
touches nothing -- so Rule 10's whole point (hide ASR's real ~35-55s load time, dominated by
onnxruntime graph compilation, in the gap before the next turn) had silently become a no-op,
confirmed directly on real Jetson hardware. `load()` now accepts an optional `language=` to
eagerly warm exactly that one session -- mirrors `MultiLangMmsTtsEngine.load(language=None)`'s
identical fix for the same underlying mistake (a lazy-by-default change that forgot preloading
still needs a way to ask for one specific thing eagerly). A real production session's language
is fixed for its duration (pocketinfer's own `self.settings["input_language"]`, gramsahayak_app.py)
-- Rule 10 now threads that through instead of preloading nothing.
"""
import os

from .indic_quantized_asr import IndicConformerASR

# 2026-08-14: expanded to match config.py's WORKERS["asr"]["languages"] -- see that key's own
# comment for why (all 12 quantized checkpoints already exist on disk, the 3-language scope
# was deliberate-but-narrow, not a technical limit). This default is only ever used if a
# caller constructs QuantizedMultiLangASR without passing languages= explicitly -- the real
# worker (asr_worker.py) always passes config.py's own tuple, so keeping this in sync is
# belt-and-suspenders, not the actual source of truth.
DEFAULT_LANGUAGES = ("hi", "ta", "ml", "as", "bn", "gu", "kn", "mai", "mr", "pa", "te", "ur")


class QuantizedMultiLangASR:
    """
    Usage:
        engine = QuantizedMultiLangASR(base_dir="models/checkpoints/indic-conformer-quantized")
        engine.load()
        engine.transcribe("audio.wav", "hi")   # -> str, lazily loads hi's session on first call
        engine.unload()
    """

    def __init__(self, base_dir, languages=DEFAULT_LANGUAGES):
        self.base_dir = base_dir
        self.languages = tuple(languages)
        self._engines = {}  # lang -> loaded IndicConformerASR, populated lazily by transcribe()
        self._ready = False  # set by load() -- distinct from "at least one language loaded"
        # now that loading is lazy (an idle-but-ready worker legitimately has an empty
        # self._engines, unlike before this change when emptiness meant "not loaded yet")

    @property
    def is_loaded(self):
        return self._ready

    def load(self, language=None):
        """Marks the engine ready -- no-op beyond that if `language` isn't given (see module
        docstring for why loading is lazy-by-default, deferred to transcribe() otherwise).
        Pass `language=<code>` to also eagerly warm exactly that one session now, e.g. Rule
        10's golden-window preload with the session's known, fixed language."""
        self._ready = True
        if language is not None:
            self._load_language(language)

    def _load_language(self, lang):
        """Eagerly load one language's ONNX session if not already resident. Shared by
        load(language=...) and transcribe()'s own lazy-first-use path -- same "load once,
        reuse" semantics either way, just two different triggers for the first load."""
        if lang not in self.languages:
            raise ValueError(
                f"Unsupported language {lang!r} -- this deployment only configured "
                f"{sorted(self.languages)} (see config.py's WORKERS['asr'] entry)."
            )
        if lang not in self._engines:
            onnx_filename = f"indicconformer_{lang}_ctc.int8.onnx"
            engine = IndicConformerASR(base_dir=self.base_dir, lang=lang, onnx_filename=onnx_filename)
            engine.load()
            self._engines[lang] = engine

    def unload(self):
        """Free every loaded language's session. No-op if nothing is loaded."""
        for engine in self._engines.values():
            engine.unload()
        self._engines = {}
        self._ready = False

    def vram_allocated_gb(self):
        """Always 0.0 -- these run CPUExecutionProvider only, no CUDA context at all (see
        indic_quantized_asr.py's module docstring for why that's a deliberate choice, not a
        limitation, at this model size)."""
        return 0.0

    def transcribe(self, audio_path, lang, decoding="ctc"):
        if decoding != "ctc":
            raise ValueError(
                f"QuantizedMultiLangASR only supports decoding='ctc' (got {decoding!r}) -- "
                "these per-language exports have no RNNT path at all, unlike the old "
                "multilingual model's ctc_only.py which chose not to build RNNT sessions from "
                "a hybrid model that still had them."
            )
        if not self.is_loaded:
            raise RuntimeError("Model not loaded -- call load() first")
        # First request for this language this session lazily loads it here (see module
        # docstring); a no-op if load(language=lang) already warmed it. Stays resident
        # afterward either way, until unload() tears the whole engine down.
        self._load_language(lang)
        return self._engines[lang].transcribe(audio_path)

    def __enter__(self):
        self.load()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.unload()
