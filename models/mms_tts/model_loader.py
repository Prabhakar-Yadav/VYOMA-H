"""Loads/unloads a Meta MMS-TTS checkpoint (`facebook/mms-tts-<iso639-3>`), evaluated as a
possible replacement for the current AWQ+TorchAO int4 Indic Parler-TTS engine
(`dev/agents/models/tts_exports/model_loader.py`) -- see
`dev/agents/MMS_TTS_EVALUATION.md` for the full writeup this module was built for.

**License, confirmed directly against every repo touched here (not assumed from the model
card's headline framing)**: `facebook/mms-tts` and all four per-language repos below
(`-eng`, `-hin`, `-mal`, `-tam`) carry the SPDX tag `license:cc-by-nc-4.0`, and each model
card states in plain text "The model is licensed as CC-BY-NC 4.0" -- Non-Commercial only, no
sublicensing under different terms. This is a **hard blocker for any commercial GramSahayak
deployment**; the project's current phase is non-commercial/research, which is the only
reason this module exists. Re-confirm this license before this code (or a checkpoint
downloaded via it) goes anywhere near a commercial build. See `MMS_TTS_EVALUATION.md` section 1.

**Not one multilingual checkpoint.** Unlike Parler-TTS, MMS-TTS ships one small VITS
checkpoint *per language* (`facebook/mms-tts-<iso639-3>`) -- there is no single model that
covers multiple languages via a prompt/description. This engine class therefore holds at
most one loaded language at a time; switching languages means `unload()` + `load()` again
with a different `language=`, same as swapping any other single-language model. Confirmed
real per-language repo coverage for this project's 4 target languages, not just the
model card's "1107 languages supported" headline (which counts everything Meta's MMS
project covers, not specifically usable, non-degenerate TTS checkpoints):

| Language | ISO 639-3 | HF repo | Repo exists, real weights? |
|---|---|---|---|
| English | eng | facebook/mms-tts-eng | Yes -- `model.safetensors` + `pytorch_model.bin` present |
| Hindi | hin | facebook/mms-tts-hin | Yes -- same |
| Malayalam | mal | facebook/mms-tts-mal | Yes -- same |
| Tamil | tam | facebook/mms-tts-tam | Yes -- same |

**Architecture, confirmed directly against a real loaded checkpoint's config, not assumed
from the model name**: `config.json`'s `model_type` is `"vits"`, `architectures` is
`["VitsModel"]` -- VITS (Variational Inference with adversarial learning for end-to-end
Text-to-Speech). Loading `facebook/mms-tts-hin` and calling `model(**inputs)` directly
(no `.generate()` loop) produces the complete waveform in a single forward pass -- confirmed
by timing one real call (~3.9s wall on CPU for a 2.6s utterance, first-call overhead
included) and inspecting the returned `VitsModelOutput.waveform` tensor directly. This is
the whole reason MMS-TTS might beat Parler-TTS's codec-token autoregressive decoder on
memory/speed: no KV-cache growth with output length, no `max_new_tokens` cap to tune, no
risk of the runaway/near-silent decoding failure mode documented in the Parler engine's own
module docstring (that failure mode is specific to *autoregressive* codec-token decoding --
architecturally not possible here). Each checkpoint is also far smaller: ~36M parameters /
~139MB on disk per language (`model.safetensors`), versus Parler-TTS's much larger shared
backbone.

Checkpoints are downloaded once via `snapshot_download` into
`dev/agents/models/checkpoints/mms-tts-<lang>/` (this project's 2-letter codes: en/hi/ml/ta)
and loaded from there directly on subsequent runs -- `checkpoint_dir=` skips the Hub
entirely if you've pre-populated that directory some other way (e.g. copying it onto a
Jetson with no network access), same pattern as the Parler engine.
"""
import ctypes
import gc
import os
import platform

import torch
from transformers import VitsModel, AutoTokenizer
from huggingface_hub import snapshot_download

# Short codes mapped to the actual per-language HF repo -- there is no "mms-tts-multi" repo.
# "en"/"hi"/"ml"/"ta" are this project's current 4 active target languages
# (test_orchestrated_pipeline.py's LANGUAGES dict); the rest are India's 8th-Schedule
# languages MMS-TTS actually has real coverage for -- confirmed directly against MMS's own
# published language-coverage table (dl.fbaipublicfiles.com/mms/misc/
# language_coverage_mms.html), not assumed from a headline count. Of India's 22 8th-Schedule
# languages, only 14 (including Hindi) have real MMS-TTS checkpoints -- see
# `config.MMS_TTS_UNSUPPORTED_INDIAN_LANGUAGES` for the 8 that don't (Bodo, Kashmiri,
# Konkani, Manipuri, Nepali, Sanskrit, Santali, Sindhi) and `tts_worker.py`'s
# `_HybridMmsParlerEngine` for how those fall back to Parler-TTS instead.
#
# Urdu ships as script-specific variants only -- bare "facebook/mms-tts-urd" doesn't exist
# (confirmed directly, 404). Two real variants exist: "-script_arabic" (native Urdu script,
# Perso-Arabic/Nastaliq -- what ASR/NMT output would actually produce) and
# "-script_devanagari" (expects Urdu text already transliterated into Devanagari
# characters). "ur" below uses script_arabic as the correct default for this pipeline.
LANGUAGE_TO_REPO = {
    "en": "facebook/mms-tts-eng",
    "hi": "facebook/mms-tts-hin",
    "ml": "facebook/mms-tts-mal",
    "ta": "facebook/mms-tts-tam",
    "as": "facebook/mms-tts-asm",       # Assamese
    "bn": "facebook/mms-tts-ben",       # Bengali
    "dgo": "facebook/mms-tts-dgo",      # Dogri (no ISO 639-1 code)
    "gu": "facebook/mms-tts-guj",       # Gujarati
    "kn": "facebook/mms-tts-kan",       # Kannada
    "mai": "facebook/mms-tts-mai",      # Maithili (no ISO 639-1 code)
    "mr": "facebook/mms-tts-mar",       # Marathi
    "or": "facebook/mms-tts-ory",       # Odia
    "pa": "facebook/mms-tts-pan",       # Punjabi
    "te": "facebook/mms-tts-tel",       # Telugu
    "ur": "facebook/mms-tts-urd-script_arabic",  # Urdu, native script
}


class MmsTtsEngine:
    """Owns one loaded MMS-TTS (VITS) checkpoint for a single language + its GPU memory.

    Unlike QuantizedParlerTTS (one model, many languages via a description prompt), MMS-TTS
    is one checkpoint *per language* -- this engine holds exactly one language at a time.
    To switch languages, unload() then load() again with a different `language=` (or
    construct a fresh engine instance per language, e.g. for the head-to-head benchmark
    where all 4 languages' numbers are wanted separately).

    Usage:
        engine = MmsTtsEngine(language="hi")
        engine.load()
        ...
        engine.unload()

    Or as a context manager:
        with MmsTtsEngine(language="hi") as engine:
            ...
    """

    def __init__(self, language="en", checkpoint_repo_id=None, checkpoint_dir=None, device=None):
        if checkpoint_repo_id is None and checkpoint_dir is None:
            if language not in LANGUAGE_TO_REPO:
                raise ValueError(
                    f"No known MMS-TTS repo for language={language!r} -- "
                    f"supported: {sorted(LANGUAGE_TO_REPO)}. Pass checkpoint_repo_id= or "
                    f"checkpoint_dir= explicitly for anything else."
                )
            checkpoint_repo_id = LANGUAGE_TO_REPO[language]

        self.language = language
        self.checkpoint_repo_id = checkpoint_repo_id
        self.checkpoint_dir = checkpoint_dir  # local path override -- skips snapshot_download if set
        self.device = device or (f"cuda:{torch.cuda.current_device()}" if torch.cuda.is_available() else "cpu")

        self.model = None
        self.tokenizer = None

    @property
    def is_loaded(self):
        return self.model is not None

    def load(self):
        """Download (cached after first call) or use the local `checkpoint_dir`, then load
        the VITS model + tokenizer directly onto `self.device`. No-op if already loaded.
        No quantization, no meta-device skeleton trick, no separate generation_config
        handling -- none of the Parler engine's incident-driven complexity applies here:
        VITS's forward pass IS the whole model, `from_pretrained()` alone is sufficient and
        correct (re-verified: see MMS_TTS_EVALUATION.md's audio sanity-check section)."""
        if self.is_loaded:
            return

        checkpoint_dir = self.checkpoint_dir or snapshot_download(repo_id=self.checkpoint_repo_id)

        model = VitsModel.from_pretrained(checkpoint_dir)
        model = model.to(self.device)
        model.eval()

        self.model = model
        self.tokenizer = AutoTokenizer.from_pretrained(checkpoint_dir)
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def unload(self):
        """Free the model + tokenizer from memory. No-op if not loaded.

        Same caveat as the Parler engine's unload() (dev/agents/models/tts_exports/
        model_loader.py): torch.cuda.memory_allocated()/reserved() are verified to drop back
        to near-zero (see MMS_TTS_EVALUATION.md's measured numbers), but host RSS does NOT
        fully return to pre-load levels within the same process -- the CUDA driver context
        and cuDNN/cuBLAS workspace stay resident for the process's lifetime once touched.
        gc.collect() + malloc_trim(0) reclaim what's actually reclaimable Python/glibc heap
        slack; full host-RSS reclaim requires the process itself to exit."""
        if not self.is_loaded:
            return
        del self.model
        self.model = None
        self.tokenizer = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
        if platform.system() == "Linux":
            try:
                ctypes.CDLL("libc.so.6").malloc_trim(0)
            except OSError:
                pass

    def vram_allocated_gb(self):
        if not torch.cuda.is_available():
            return None
        return torch.cuda.memory_allocated(self.device) / 1e9

    def __enter__(self):
        self.load()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.unload()


class MultiLangMmsTtsEngine:
    """Holds multiple `MmsTtsEngine` instances (one per language) resident at once, behind
    the single-engine-object interface `dev/agents/api_server/worker_base.py`'s generic
    worker state machine expects (`.is_loaded`, `.load()`, `.unload()`,
    `.vram_allocated_gb()`) -- built specifically so `tts_worker.py` can slot MMS-TTS into
    the same `/load` + `/infer` shape Parler-TTS already uses there.

    **Why this exists, not just a plain `MmsTtsEngine`**: `tts_worker.py`'s `/load`
    endpoint has no per-request language argument -- `/infer`'s payload carries `"language"`
    per call (matching Parler-TTS's own request shape, since its one model handles every
    language via a prompt). MMS-TTS ships one checkpoint per language instead (see this
    module's docstring above). Reloading a single `MmsTtsEngine` on every language switch
    would work (~1.6-2s each time, real measured cost -- `MMS_TTS_EVALUATION.md` section 7)
    but there's no real memory reason to pay that: all 4 of this project's target languages
    loaded simultaneously measured **~0.59GB allocated / ~0.60GB reserved combined**
    (confirmed directly, same section) -- trivial next to the 7GB Jetson budget, unlike
    Parler-TTS's much larger single model where evicting to make room is actually load-bearing.
    So this class keeps every requested language resident once loaded, rather than treating
    a language switch as an evict-then-reload event.

    Usage:
        engine = MultiLangMmsTtsEngine(checkpoint_root="models/checkpoints",
                                        languages=["en", "hi", "ml", "ta"])
        engine.load()                 # lazy -- loads nothing yet, just marks ready
        engine.load(language="hi")    # eagerly loads just Hindi (Rule 5's golden-window
                                       # preload does this, once the pipeline's own target
                                       # output language is known -- see orchestrator.py)
        engine.get("hi").model        # the loaded VitsModel for Hindi (lazy-loads it too,
                                       # if not already resident)
        engine.unload()               # unloads every resident language
    """

    def __init__(self, checkpoint_root, languages=None, device=None):
        self.checkpoint_root = checkpoint_root
        # `languages=` is now only a validity/reference list (what this engine COULD serve),
        # not an eager-preload instruction -- see load()'s own docstring for why that changed
        # 2026-08-11. Real per-language cost, corrected: MMS_TTS_EVALUATION.md Sec.10 found
        # all 4 languages resident together cost ~1.47GB combined RSS+VRAM, not the ~0.59GB
        # VRAM-only figure this class's eager-preload design was originally justified against
        # -- and a real single-language session (the only kind this pipeline's ASR already
        # assumes, per models/asr/quantized_multilang_loader.py's own 2026-08-09 lazy fix)
        # never needed the other 3 resident at all.
        self.languages = list(languages) if languages else list(LANGUAGE_TO_REPO)
        self.device = device
        self._engines = {}  # lang -> MmsTtsEngine, only languages actually resident right now
        self._ready = False  # set by load() -- distinct from "at least one language loaded",
        # same reasoning as QuantizedMultiLangASR's own _ready flag: an idle-but-ready engine
        # legitimately has an empty self._engines now that loading is lazy.

    @property
    def is_loaded(self):
        return self._ready

    def load(self, language=None):
        """No-op (just marks ready) if `language` isn't given -- real per-language loading
        is deferred to the first `get(code)` call that actually needs it, exactly mirroring
        `QuantizedMultiLangASR.load()`'s 2026-08-09 fix and for the same real reason (a
        single-language session was eagerly paying for 3 languages it would never use).

        Pass `language=<code>` to eagerly load exactly that one -- this is what
        `orchestrator.py`'s Rule 5 golden-window preload does once the turn's actual output
        language is known, so the real per-language load cost (~1.6-2s,
        MMS_TTS_EVALUATION.md Sec.7) still gets hidden in the agent's own downtime instead
        of landing in the critical path at first synthesis -- going fully lazy here would
        have fixed the memory waste but reintroduced exactly the latency Rule 5 exists to
        avoid, which is not a trade worth making silently."""
        self._ready = True
        if language is not None:
            self._load_language(language)

    def _load_language(self, language):
        if language in self._engines:
            return self._engines[language]
        if language not in LANGUAGE_TO_REPO:
            raise ValueError(
                f"No known MMS-TTS repo for language={language!r} -- "
                f"supported: {sorted(LANGUAGE_TO_REPO)}."
            )
        checkpoint_dir = os.path.join(self.checkpoint_root, f"mms-tts-{language}")
        engine = MmsTtsEngine(language=language, checkpoint_dir=checkpoint_dir, device=self.device)
        engine.load()
        self._engines[language] = engine
        return engine

    def get(self, language):
        """Returns the loaded `MmsTtsEngine` for `language`, lazily loading it (real cost:
        ~1.6-2s, confirmed directly -- `MMS_TTS_EVALUATION.md` section 7) if it wasn't in
        the `languages=` list passed at construction time. Keeps this engine usable for any
        of this project's languages even if only a subset was eagerly preloaded at `load()`."""
        return self._load_language(language)

    def unload(self):
        for engine in self._engines.values():
            engine.unload()
        self._engines = {}
        self._ready = False

    def vram_allocated_gb(self):
        """Returns the real combined VRAM in use across every resident language.

        Deliberately does NOT sum each sub-engine's own `vram_allocated_gb()` -- caught
        directly during testing: `torch.cuda.memory_allocated(device)` is a *global*
        per-device counter, not a per-model one, so calling it once per resident language
        and adding the results double/triple-counts the same underlying allocation (2
        languages loaded read back as ~2x the real figure, 3 as ~3x, etc.). Reading the
        global counter exactly once, via any one resident engine, gives the real total."""
        if not self._engines:
            return None
        return next(iter(self._engines.values())).vram_allocated_gb()

    def __enter__(self):
        self.load()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.unload()
