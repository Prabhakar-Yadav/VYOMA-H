"""Loads/unloads AI4Bharat's indic-conformer-600m-multilingual ASR model (hybrid CTC+RNNT
Conformer, 22 scheduled Indian languages -- NOT English, see SUPPORTED_LANGUAGES below).

Model card: https://huggingface.co/ai4bharat/indic-conformer-600m-multilingual
Loaded via `AutoModel.from_pretrained(..., trust_remote_code=True)` -- this pulls custom
modeling code (`model_onnx.py`) from the repo, cached under
`HF_HOME/modules/transformers_modules/`. `config.json`'s own `auto_map` field points
`AutoModel`/`AutoConfig` at that custom code, so no manual `AutoConfig.register(...)` call
is needed (unlike the `if __name__ == "__main__":` block at the bottom of the cached
`model_onnx.py`, which only runs when that file is executed directly, never on import).

**No English support.** The model's own `vocab.json`/`language_masks.json` cover the 22
scheduled Indian languages (as, bn, brx, doi, gu, hi, kn, kok, ks, mai, ml, mni, mr, ne, or,
pa, sa, sat, sd, ta, te, ur) -- there is no "en" key, confirmed directly against the
checkpoint's own asset files, not assumed from the model card. `transcribe()` raises a clear
error for "en" rather than silently mistranscribing -- English audio needs a different ASR
engine entirely, out of scope for this wrapper.

**CTC vs RNNT decoding**: this wrapper defaults to CTC (`decoding="ctc"`) -- one forward pass
through `ctc_decoder.onnx`, versus RNNT's per-timestep autoregressive loop through
`rnnt_decoder.onnx` plus a *separate* `joint_post_net_<lang>.onnx` file per language. Both
are exposed via the `decoding=` argument if you want to compare them directly.

**`ctc_only=True` (the default) skips the RNNT-side load entirely.** The real
`trust_remote_code` class (`model_onnx.py`, cached under `HF_HOME/modules/`) builds 29
separate model artifacts at `__init__` time no matter which `decoding=` is ever used --
`rnnt_decoder` + `joint_enc`/`joint_pred`/`joint_pre_net` + one `joint_post_net_<lang>` ONNX
session per each of the 22 languages, on top of `preprocessor`/`encoder`/`ctc_decoder`.
`asr_worker.py` always calls `decoding="ctc"` in production -- RNNT is only ever exercised
by the standalone comparison test (`dev/local_model_test/test_asr_memory.py`) -- so those 26
extra sessions are pure `ort.InferenceSession` CUDA-EP session-creation overhead (graph
parse, provider registration, CUDA context setup) for a path that's never taken. This isn't
a checkpoint-size fix (the RNNT-side files total 57MB against the shared encoder's ~2.4GB,
confirmed directly) -- it's a session-*count* fix: `ctc_only=True` loads 3 artifacts
(preprocessor, encoder, ctc_decoder) instead of 29, via `models/asr/ctc_only.py`'s trimmed
clone of the same cached class. Same on-disk checkpoint, same weights, same CTC output --
see `ASR_CTC_ONLY_TIMING.md` for the measured before/after. Pass `ctc_only=False` to get the
full model (needed if you ever want `decoding="rnnt"`).

**Local checkpoint layout is an HF cache directory, not a flat folder.** Unlike the TTS/NMT
checkpoints in this project (a flat directory of named files), `models/checkpoints/
indic-conformer-600m-fp32/` is a full `HF_HOME`-shaped cache (`hub/`, `modules/`, `xet/`) --
that's what `trust_remote_code=True` produces, since it needs to cache the custom Python
module alongside the usual model snapshot. The model's own custom `from_pretrained()`
classmethod (in the cached `model_onnx.py`) accepts a `cache_dir=` argument but never
actually passes it to its internal `snapshot_download()` call -- silently ignored. The only
thing that actually redirects that call is the `HF_HOME` environment variable, which is why
this class sets that directly (matching the same pattern `QuantizedParlerTTS`'s
`hf_cache_dir=` uses) instead of trying to pass `cache_dir=` through.
"""
import gc
import os

import torch

DEFAULT_MODEL_ID = "ai4bharat/indic-conformer-600m-multilingual"
TARGET_SAMPLE_RATE = 16000

# ISO code -> language name, matches this checkpoint's own vocab.json/language_masks.json
# keys exactly (verified directly against the downloaded assets) -- no "en".
SUPPORTED_LANGUAGES = {
    "as": "Assamese", "bn": "Bengali", "brx": "Bodo", "doi": "Dogri", "gu": "Gujarati",
    "hi": "Hindi", "kn": "Kannada", "kok": "Konkani", "ks": "Kashmiri", "mai": "Maithili",
    "ml": "Malayalam", "mni": "Manipuri", "mr": "Marathi", "ne": "Nepali", "or": "Odia",
    "pa": "Punjabi", "sa": "Sanskrit", "sat": "Santali", "sd": "Sindhi", "ta": "Tamil",
    "te": "Telugu", "ur": "Urdu",
}


class IndicConformerASR:
    """Owns the loaded model and its GPU/CPU memory.

    Usage:
        engine = IndicConformerASR(hf_cache_dir="models/checkpoints/indic-conformer-600m-fp32")
        engine.load()
        engine.transcribe("audio.wav", "hi")   # -> str
        engine.unload()
    """

    def __init__(self, model_id=DEFAULT_MODEL_ID, hf_cache_dir=None, device=None, ctc_only=True):
        self.model_id = model_id
        if hf_cache_dir:
            os.environ["HF_HOME"] = str(hf_cache_dir)
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.ctc_only = ctc_only
        self.model = None

    @property
    def is_loaded(self):
        return self.model is not None

    def load(self):
        """No-op if already loaded. Reads from the local HF_HOME cache set in __init__ --
        no network call once that cache is populated. `ctc_only` (default True) skips the
        RNNT-side sessions entirely -- see module docstring."""
        if self.is_loaded:
            return
        if self.ctc_only:
            from .ctc_only import IndicASRModelCTCOnly
            self.model = IndicASRModelCTCOnly.from_pretrained(self.model_id)
        else:
            from transformers import AutoModel
            self.model = AutoModel.from_pretrained(self.model_id, trust_remote_code=True)

    def unload(self):
        """Free the model from memory. No-op if not loaded."""
        if not self.is_loaded:
            return
        del self.model
        self.model = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def vram_allocated_gb(self):
        if not torch.cuda.is_available():
            return None
        return torch.cuda.memory_allocated() / 1e9

    def transcribe(self, audio_path, lang, decoding="ctc"):
        """Transcribes a wav/flac file. `lang` must be one of SUPPORTED_LANGUAGES's keys --
        there is no English support, see module docstring. Resamples to 16kHz mono
        internally (the preprocessor's expected input rate), matching the model card's own
        usage example.

        Uses `soundfile` + `librosa.resample`, not `torchaudio.load()` -- the installed
        torchaudio version's default audio backend requires the separate `torchcodec`
        package (confirmed directly: raises ImportError without it), and this project
        already depends on soundfile/librosa elsewhere, so this avoids a new dependency."""
        import soundfile as sf
        import librosa
        import numpy as np

        if lang not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"Unsupported language {lang!r} for indic-conformer -- it covers "
                f"{sorted(SUPPORTED_LANGUAGES)} only, no English. Skip ASR for English "
                f"input and use the known text directly instead."
            )
        if not self.is_loaded:
            raise RuntimeError("Model not loaded -- call load() first")

        audio, sr = sf.read(audio_path, always_2d=True)  # (num_samples, num_channels)
        audio = audio.mean(axis=1).astype(np.float32)  # stereo -> mono
        if sr != TARGET_SAMPLE_RATE:
            audio = librosa.resample(audio, orig_sr=sr, target_sr=TARGET_SAMPLE_RATE)

        wav = torch.from_numpy(audio).unsqueeze(0)  # (1, num_samples)
        return self.model(wav, lang, decoding)

    def __enter__(self):
        self.load()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.unload()
