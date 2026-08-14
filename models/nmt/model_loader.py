"""Loads/unloads the IndicTrans2 (ct2 int8) NMT models and runs translation.

Vendored from this project's own dev/local_model_test/bhashini_extracted/bhashini_models/nmt/
(the "Bhashini" NMT service used by suno-sutra-sw/python/pocketinfer's Nmt client and by
hear_the_world.py) -- same `inference/` package (engine.py + its ctranslate2/indic-nlp
pre/post-processing), reworked here into a load()/unload() engine so it can run in-process
in a notebook kernel instead of behind a separate Flask service.

Three directions, three separate ct2 models (en->indic, indic->en, indic<->indic) -- IndicTrans2
doesn't have one shared model for all directions. `checkpoint_root` must contain
`{en-indic,indic-en,indic-indic}/ct2_int8_model/` (that's exactly the layout downloaded from
this project's own vendored checkpoints -- see models/checkpoints/indic-trans2-nmt/).

**Language codes are NOT symmetric** -- this mirrors a real, confirmed bug in the underlying
routing (see dev/local_model_test/test_bhashini_wrappers.py): indic source/target codes are
lowercase ISO (e.g. "hi", "ta", "ml", "te"), but English must be passed as **uppercase "EN"**,
not lowercase "en" -- lowercase "en" is not recognized as English by `_route_translate` and
raises `Unsupported translation direction`.

**device auto-detection (2026-08-13, was hardcoded "cpu")**: the original "GX10 patch" finding
(see the vendored engine.py's call site) was real -- the *standard* aarch64 ctranslate2 PyPI
wheel has no CUDA support even when `torch.cuda.is_available()` is True, so `device="cpu"` was
a correct workaround for that specific wheel. But it silently stopped being correct the moment
this project built its own CUDA-enabled ctranslate2 from source on Jetson (done this same
session, for ASR/other GPU work) -- the hardcoded "cpu" default meant NMT kept running on CPU
even after a real GPU-capable build existed, completely unused for this component. Confirmed
directly (isolated, real timing + memory test against the actual production checkpoint and a
real 1934-char/7-paragraph agent answer): CPU sequential (the exact prior production behavior)
32.34s / 2.32GB for both directions loaded, vs CUDA sequential 4.97s / CUDA batched (see
infer_long() below) 1.24s -- CUDA is both ~26x faster AND uses LESS real memory (~0.86GB vs
~2.3GB), not a speed/memory tradeoff. `_default_device()` below asks ctranslate2 itself
(`get_cuda_device_count()`) whether *this* install genuinely has CUDA support, which is the
real, install-specific question -- not `torch.cuda.is_available()` (a different library that
can be True while ctranslate2 itself is still the CPU-only wheel, which is exactly how this
regression happened) and not a hardcoded per-device assumption (this file is shared with GX10,
whose ctranslate2 install may or may not have the same custom CUDA build). Explicit
`device=...` still overrides for a real deliberate CPU test.

**nltk `punkt` data**: `engine.py`'s sentence splitter for English source text needs nltk's
`punkt` tokenizer data, which isn't bundled with the `nltk` package -- `load()` below checks
for it and downloads it (a few hundred KB, one-time, cached in `~/nltk_data`) if missing.

**Multi-paragraph English text silently drops everything after the first sentence** --
confirmed directly, a real bug in the vendored `inference/engine.py`'s `split_sentences()`
(inherited from the original AI4Bharat/Bhashini toolkit, not code this project wrote).
For English source text it runs both `MosesSentenceSplitter` and nltk's `sent_tokenize`,
then picks whichever found *fewer* sentences on the assumption Moses is the one prone to
over-splitting (e.g. on abbreviations). But `MosesSentenceSplitter` chokes on embedded
blank-line paragraph breaks and collapses a real 3-paragraph, 3-sentence agent answer down
to a count of 1 -- so the "fewer is safer" heuristic picks Moses's broken 1-sentence result
over nltk's correct 3, and every sentence after the first is silently discarded before
translation ever runs. `infer_long()` below works around it by paragraph-splitting the text
*before* it ever reaches `split_sentences`, so each individual call only ever sees text
short enough (no embedded paragraph breaks) for Moses to handle correctly.
"""
import gc
import os
import re
import sys
from typing import List

_NMT_DIR = os.path.dirname(os.path.abspath(__file__))
if _NMT_DIR not in sys.path:
    sys.path.insert(0, _NMT_DIR)

from inference.engine import Model, iso_to_flores  # noqa: E402 -- needs the sys.path insert above

DEFAULT_CHECKPOINT_ROOT = os.path.join(
    os.path.dirname(_NMT_DIR), "checkpoints", "indic-trans2-nmt"
)
# IndicTrans2 ships three separate ct2 models (en->indic, indic->en, indic<->indic) --
# no shared model covers all directions. This project's actual pipeline only ever calls
# NMT as <lang>->EN or EN-><lang> (confirmed directly: every real call site in
# orchestrator.py/test_orchestrated_pipeline.py passes "EN" as one side, never two Indic
# languages against each other) -- so indic-indic is real, unused weight, both on disk
# (~310MB, the largest of the three ct2_int8_model directories) and in loaded RAM at
# runtime, on the one device (Jetson, 7GB budget) where that actually matters. REQUIRED
# is a hard load() precondition; OPTIONAL is loaded only if present, silently skipped
# otherwise -- _route_translate() raises a clear error if an indic<->indic call is ever
# actually attempted without it loaded, rather than a confusing KeyError.
REQUIRED_MODELS = {"en-indic", "indic-en"}
OPTIONAL_MODELS = {"indic-indic"}
INDIC_LANGUAGES = set(iso_to_flores.keys())


def _ensure_nltk_punkt():
    import nltk
    for resource in ("tokenizers/punkt", "tokenizers/punkt_tab"):
        try:
            nltk.data.find(resource)
        except LookupError:
            nltk.download(resource.split("/")[-1], quiet=True)


def _default_device():
    """Real, install-specific CUDA-availability check for ctranslate2 -- see the module
    docstring's "device auto-detection" note for why this can't just be
    `torch.cuda.is_available()`. Falls back to "cpu" on any error (e.g. a ctranslate2 build
    old enough not to have `get_cuda_device_count()` at all) rather than raising -- this is a
    perf auto-detect, not a hard requirement, and CPU mode still works correctly."""
    import ctranslate2
    try:
        return "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
    except Exception:
        return "cpu"


class NMTEngine:
    """Owns the three loaded IndicTrans2 ct2 models.

    Usage:
        engine = NMTEngine()
        engine.load()
        engine.infer("Hello", "EN", "hi")["translated_text"]
        engine.unload()
    """

    def __init__(self, checkpoint_root=DEFAULT_CHECKPOINT_ROOT, device=None):
        self.checkpoint_root = checkpoint_root
        self.device = device if device is not None else _default_device()
        self.models = None

    @property
    def is_loaded(self):
        return self.models is not None

    def load(self):
        """No-op if already loaded."""
        if self.is_loaded:
            return

        _ensure_nltk_punkt()

        if not os.path.exists(self.checkpoint_root):
            raise RuntimeError(f"NMT checkpoint root not found: {self.checkpoint_root}")

        models = {}
        for folder in REQUIRED_MODELS:
            model_path = os.path.join(self.checkpoint_root, folder, "ct2_int8_model")
            if not os.path.exists(model_path):
                raise RuntimeError(f"Missing NMT model path: {model_path}")
            models[folder] = Model(
                model_path,
                device=self.device,
                input_lang_code_format="iso",
                model_type="ctranslate2",
            )
        for folder in OPTIONAL_MODELS:
            model_path = os.path.join(self.checkpoint_root, folder, "ct2_int8_model")
            if os.path.exists(model_path):
                models[folder] = Model(
                    model_path,
                    device=self.device,
                    input_lang_code_format="iso",
                    model_type="ctranslate2",
                )
        self.models = models

    def unload(self):
        if not self.is_loaded:
            return
        self.models = None
        gc.collect()

    def _route_model(self, src: str, tgt: str):
        """Picks which of the three loaded ct2 models handles src->tgt, and the lowercase
        codes to actually pass it (mirrors the old inline branches in _route_translate,
        factored out so both the single-text and real-batched paths share one routing
        decision instead of duplicating it)."""
        if src in INDIC_LANGUAGES and tgt in INDIC_LANGUAGES:
            if "indic-indic" not in self.models:
                raise RuntimeError(
                    f"indic-indic translation ({src} -> {tgt}) requested, but that model "
                    "wasn't loaded -- it's optional and this project's real pipeline never "
                    "calls it (every real translation goes through EN as the pivot "
                    "language). If you genuinely need direct Indic<->Indic translation, "
                    "copy the indic-indic/ct2_int8_model/ directory into this checkpoint's "
                    "root and reload."
                )
            return self.models["indic-indic"], src, tgt
        elif src in INDIC_LANGUAGES and tgt == "EN":
            return self.models["indic-en"], src, "en"
        elif src == "EN" and tgt in INDIC_LANGUAGES:
            return self.models["en-indic"], "en", tgt
        else:
            raise ValueError(f"Unsupported translation direction {src} -> {tgt}")

    def _route_translate(self, text: str, src: str, tgt: str) -> str:
        return self._route_translate_batch([text], src, tgt)[0]

    def _route_translate_batch(self, texts: List[str], src: str, tgt: str) -> List[str]:
        """Same routing/model choice as _route_translate, but real-batches every text in
        `texts` (all assumed the same src->tgt direction, e.g. infer_long()'s paragraphs)
        through ONE ctranslate2 call instead of one call per text.

        This matters a lot, not just a little (2026-08-13, real measurement): infer_long()
        used to call _route_translate() once per paragraph in a Python loop -- each call its
        own separate translate_batch(), so a real 7-paragraph agent answer paid 7 separate
        model-call overheads even after the earlier max_batch_size fix (engine.py's
        ctranslate2_translate_lines) started batching *within* a paragraph's own sentences.
        Most real paragraphs in an agent answer are a single sentence (see the module
        docstring's structure), so that earlier fix was frequently a no-op in practice --
        cross-paragraph batching is where the real win is. Routing through
        paragraphs_batch_translate__multilingual (which already natively supports a list of
        (text, src, tgt) tuples and collects every sentence across ALL of them into one
        translate_lines() call) fixes this at the real bottleneck instead of only the one
        layer below it."""
        model, mapped_src, mapped_tgt = self._route_model(src, tgt)
        batch_payloads = [(text, mapped_src, mapped_tgt) for text in texts]
        return model.paragraphs_batch_translate__multilingual(batch_payloads)

    def infer(self, text: str, src_lang: str, tgt_lang: str):
        """Same shape as the Bhashini /nmt HTTP response: {"translated_text": ..., ...}.
        src_lang/tgt_lang: indic codes are lowercase ISO ("hi"/"ta"/"ml"/"te"/...), English
        is uppercase "EN" -- see module docstring."""
        if not self.is_loaded:
            raise RuntimeError("NMT engine not loaded -- call engine.load() first")
        if not text.strip():
            raise ValueError("Input text cannot be empty")

        translated = self._route_translate(text, src_lang, tgt_lang)
        return {"translated_text": translated, "src_lang": src_lang, "tgt_lang": tgt_lang}

    def infer_long(self, text: str, src_lang: str, tgt_lang: str):
        """Same shape/args as infer(), but splits `text` on paragraph breaks (blank lines)
        and translates all paragraphs in ONE real batched call (see _route_translate_batch's
        docstring, 2026-08-13 -- was one _route_translate() call per paragraph in a loop,
        which silently defeated cross-paragraph batching for exactly the multi-paragraph
        structured answers this method exists for), then rejoins with blank lines -- works
        around the split_sentences() bug documented in the module docstring above. Use this
        instead of infer() for any text that isn't known to be a single short sentence, e.g.
        a full agent answer."""
        if not self.is_loaded:
            raise RuntimeError("NMT engine not loaded -- call engine.load() first")

        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        if not paragraphs:
            paragraphs = [text]

        translated_paragraphs = self._route_translate_batch(paragraphs, src_lang, tgt_lang)
        translated = "\n\n".join(translated_paragraphs)
        return {"translated_text": translated, "src_lang": src_lang, "tgt_lang": tgt_lang}

    def __enter__(self):
        self.load()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.unload()
