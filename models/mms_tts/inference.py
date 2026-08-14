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

    def synthesize(self, text):
        """Returns (audio: np.ndarray[float32], sample_rate: int)."""
        if not self.engine.is_loaded:
            raise RuntimeError("Model not loaded -- call engine.load() first")

        model = self.engine.model
        device = self.engine.device

        inputs = self.engine.tokenizer(text, return_tensors="pt")
        inputs = {k: v.to(device) for k, v in inputs.items()}

        with torch.no_grad():
            output = model(**inputs)

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
