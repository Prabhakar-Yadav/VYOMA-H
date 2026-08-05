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

**device="cpu"**: matches this project's own "GX10 patch" finding (see the vendored
engine.py's call site) -- the aarch64 ctranslate2 PyPI wheel has no CUDA support even when
`torch.cuda.is_available()` is True, so GPU device is not actually usable here. NMT is fast
enough on CPU regardless (~0.3-1.5s per call, measured in this project's own bhashini_server.log).

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

_NMT_DIR = os.path.dirname(os.path.abspath(__file__))
if _NMT_DIR not in sys.path:
    sys.path.insert(0, _NMT_DIR)

from inference.engine import Model, iso_to_flores  # noqa: E402 -- needs the sys.path insert above

DEFAULT_CHECKPOINT_ROOT = os.path.join(
    os.path.dirname(_NMT_DIR), "checkpoints", "indic-trans2-nmt"
)
REQUIRED_MODELS = {"en-indic", "indic-en", "indic-indic"}
INDIC_LANGUAGES = set(iso_to_flores.keys())


def _ensure_nltk_punkt():
    import nltk
    for resource in ("tokenizers/punkt", "tokenizers/punkt_tab"):
        try:
            nltk.data.find(resource)
        except LookupError:
            nltk.download(resource.split("/")[-1], quiet=True)


class NMTEngine:
    """Owns the three loaded IndicTrans2 ct2 models.

    Usage:
        engine = NMTEngine()
        engine.load()
        engine.infer("Hello", "EN", "hi")["translated_text"]
        engine.unload()
    """

    def __init__(self, checkpoint_root=DEFAULT_CHECKPOINT_ROOT, device="cpu"):
        self.checkpoint_root = checkpoint_root
        self.device = device
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
        self.models = models

    def unload(self):
        if not self.is_loaded:
            return
        self.models = None
        gc.collect()

    def _route_translate(self, text: str, src: str, tgt: str) -> str:
        if src in INDIC_LANGUAGES and tgt in INDIC_LANGUAGES:
            return self.models["indic-indic"].paragraphs_batch_translate__multilingual(
                [[text, src, tgt]]
            )[0]
        elif src in INDIC_LANGUAGES and tgt == "EN":
            return self.models["indic-en"].paragraphs_batch_translate__multilingual(
                [[text, src, "en"]]
            )[0]
        elif src == "EN" and tgt in INDIC_LANGUAGES:
            return self.models["en-indic"].paragraphs_batch_translate__multilingual(
                [[text, "en", tgt]]
            )[0]
        else:
            raise ValueError(f"Unsupported translation direction {src} -> {tgt}")

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
        and translates each paragraph separately, then rejoins with blank lines -- works
        around the split_sentences() bug documented in the module docstring above. Use this
        instead of infer() for any text that isn't known to be a single short sentence, e.g.
        a full agent answer."""
        if not self.is_loaded:
            raise RuntimeError("NMT engine not loaded -- call engine.load() first")

        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        if not paragraphs:
            paragraphs = [text]

        translated_paragraphs = [self._route_translate(p, src_lang, tgt_lang) for p in paragraphs]
        translated = "\n\n".join(translated_paragraphs)
        return {"translated_text": translated, "src_lang": src_lang, "tgt_lang": tgt_lang}

    def __enter__(self):
        self.load()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.unload()
