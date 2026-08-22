"""Runs text-to-speech generation against a loaded MmsTtsEngine.

Mirrors the shape of `dev/agents/models/tts_exports/inference.py`'s `TTSInferencer`, but
much simpler: VITS has no voice-description prompt (a checkpoint is one language, one
speaker -- MMS-TTS's mono-speaker checkpoints have no `speaker`/`gender`/`description`
controls at all, confirmed directly from each of this project's 4 checkpoints' `config.json`:
`num_speakers: 1`, `speaker_embedding_size: 0` on every one), and no `max_new_tokens` cap to
reason about, since there's no autoregressive decoding loop -- `model(**inputs)` produces the
complete waveform in one forward pass.
"""
import numpy as np
import torch


class MmsTtsInferencer:
    """Generates audio from text using a loaded MmsTtsEngine.

    Usage:
        engine = MmsTtsEngine(language="hi")
        engine.load()
        tts = MmsTtsInferencer(engine)
        audio, sample_rate = tts.synthesize("नमस्ते दुनिया")
    """

    def __init__(self, engine):
        self.engine = engine

    def synthesize(self, text, noise_scale=None, noise_scale_s=None, speaking_rate=None,
                   seed=None):
        """Returns (audio: np.ndarray[float32], sample_rate: int).

        The optional kwargs tune VITS's own sampling knobs (None = the checkpoint/HF
        default, i.e. exactly the old behavior). MECHANISM, learned the hard way 2026-08-23:
        this transformers build's `VitsModel.forward()` REJECTS these as kwargs -- passing
        them crashed every /tts/infer and /tts/infer_stream call at once. They are model
        ATTRIBUTES consumed inside forward(): `model.noise_scale`, `model.noise_scale_duration`
        (this kwarg maps to it -- note the different name), `model.speaking_rate`. synthesize()
        therefore saves the loaded checkpoint's attribute values, sets the requested ones,
        and restores the originals in a `finally:` so callers that pass nothing (play(),
        synthesize_to_file()) keep pure checkpoint-default behavior.

        The knobs exist because of the 2026-08-23 voice-drift incident: VITS samples
        a fresh latent z ~ N(0, noise_scale^2) plus duration noise on EVERY forward pass
        with no seed and no speaker embedding to anchor "the voice" (these checkpoints are
        mono-speaker, speaker_embedding_size: 0), so separately-synthesized chunks of one
        answer are independent draws -- a real streamed Hindi answer measured 122-155 Hz
        median F0 on its first three chunks and 195 Hz on the fourth (audibly a different
        person; tts_worker.py now F0-matches chunks against each other). Lowering
        noise_scale/noise_scale_s clusters the draws around the model's mean voice so
        chunks agree more, at some cost to prosody liveliness -- values come from
        config.py's mms_tts engine block, not hardcoded here.

        `seed`, when set, is applied via torch.manual_seed() before the forward pass --
        the SAME seed on every call makes all chunks draw from the same random sequence
        (shared latent prefix), the strongest consistency lever here, at the cost of
        identical output for identical input (fine for TTS, wrong for anything wanting
        sample diversity).
        """
        if not self.engine.is_loaded:
            raise RuntimeError("Model not loaded -- call engine.load() first")

        model = self.engine.model
        device = self.engine.device

        inputs = self.engine.tokenizer(text, return_tensors="pt")
        inputs = {k: v.to(device) for k, v in inputs.items()}

        if seed is not None:
            torch.manual_seed(seed)

        # VitsModel.forward() does not accept these as kwargs.
        # They are model attributes consumed internally by forward().
        old_noise_scale = model.noise_scale
        old_noise_scale_duration = model.noise_scale_duration
        old_speaking_rate = model.speaking_rate
        
        try:
            if noise_scale is not None:
                model.noise_scale = noise_scale
        
            if noise_scale_s is not None:
                model.noise_scale_duration = noise_scale_s
        
            if speaking_rate is not None:
                model.speaking_rate = speaking_rate
        
            with torch.no_grad():
                output = model(**inputs)
        
        finally:
            # Don't permanently modify the loaded checkpoint configuration.
            model.noise_scale = old_noise_scale
            model.noise_scale_duration = old_noise_scale_duration
            model.speaking_rate = old_speaking_rate
        
#        fwd_kwargs = {}
#        if noise_scale is not None:
#            fwd_kwargs["noise_scale"] = noise_scale
#        if noise_scale_s is not None:
#            fwd_kwargs["noise_scale_s"] = noise_scale_s
#        if speaking_rate is not None:
#            fwd_kwargs["speaking_rate"] = speaking_rate
#
#        with torch.no_grad():
#            output = model(**inputs, **fwd_kwargs)
#
        audio = output.waveform.to(torch.float32).cpu().numpy().squeeze()
        if audio.ndim == 0:
            audio = np.zeros(1, dtype=np.float32)
        sample_rate = model.config.sampling_rate
        return audio, sample_rate

    def synthesize_to_file(self, text, out_path):
        """Same as synthesize(), but writes a .wav file and returns its path."""
        import soundfile as sf
        audio, sample_rate = self.synthesize(text)
        sf.write(out_path, audio, sample_rate)
        return out_path

    def play(self, text, blocking=True):
        """Generates audio and plays it directly through the system's audio output -- no
        file involved. Same optional `sounddevice` dependency/tradeoff as tts_exports/
        inference.py's TTSInferencer.play().

        Unlike Parler-TTS's play_stream(), there is no chunking/prebuffering strategy to
        reason about here: MMS-TTS's synthesis is fast enough (RTF 0.01-0.06, confirmed
        directly on real multi-paragraph answers up to 883 chars / 64.78s of audio in
        1.64s -- MMS_TTS_EVALUATION.md section 7) that the whole answer is ready well
        before a human would notice a wait. "Generate the whole thing, then play" is simply
        the right strategy here -- no streaming complexity needed."""
        try:
            import sounddevice as sd
        except (ImportError, OSError) as e:
            raise RuntimeError(
                "play() needs the optional `sounddevice` package (and a working audio "
                "device/PortAudio install) -- pip install sounddevice. Use synthesize() or "
                "synthesize_to_file() instead if this machine has no audio output."
            ) from e

        audio, sample_rate = self.synthesize(text)
        sd.play(audio, sample_rate)
        if blocking:
            sd.wait()
        return audio, sample_rate
