"""Runs text-to-speech generation against a loaded QuantizedParlerTTS engine.

Vendored from https://github.com/hazardscarn/vyoma_hackathon (tts_exports/).

Voice is controlled by a natural-language description, matching how Parler-TTS was trained.
Ways to specify one, in priority order: an explicit `description` string (full control), a
`speaker` name (wrapped in the template the model responds best to), or a `language` (looks up
that language's empirically-best speaker from best_speakers.json, found by testing every
officially-documented recommended speaker per language against real held-out text -- see
TECHNICAL_REPORT.md in the source repo for the methodology and the n=8/speaker search results).

Pass `gender="female"` alongside `language=` to prefer a named female speaker instead
(`feminine_speakers.json`). Read the caveat on that file before trusting it for every
language: the model card does not publish a formal per-speaker gender table -- gender is
confirmed via an explicit pronoun ("Her voice...") or label ("Tapan - Male") for only a
handful of speakers in the model's own example descriptions, and inferred from standard
Indian-language naming convention for the rest of the *tested* (n=8 WER search) speaker set,
not fabricated for names never tested. `null` in that file means no such speaker could be
identified with reasonable confidence, for one of three distinct reasons -- consult the source
repo's TECHNICAL_REPORT.md if this matters for your use case:
  - **Dogri, Sanskrit**: genuinely only one speaker is documented for the whole language, and
    it's male -- no female alternative exists in the model's own speaker list at all.
  - **Manipuri, Punjabi**: both documented speakers were tested, but neither's gender could be
    confirmed with confidence (Punjabi's "Divjot"/"Gurpreet" and Manipuri's "Laishram"/"Ranjit"
    aren't reliably single-gender names/conventions).
  - **Kashmiri, Konkani, Maithili, Santali, Sindhi, Urdu**: no named speaker of any kind is
    documented for these six languages (matching best_speakers.json's own gap) -- there is
    nothing to pick from, named or otherwise.
For all `null` cases, this falls back to a generic description with explicit "female" wording
instead of a named speaker -- a real, if untested, fallback: the model card states gender
"can be controlled directly through the prompt", so this is a documented mechanism, just not
one verified via WER the way the named-speaker picks were.
"""
import re
import json
from pathlib import Path

import torch
import numpy as np

BEST_SPEAKERS_PATH = Path(__file__).parent / "best_speakers.json"
FEMININE_SPEAKERS_PATH = Path(__file__).parent / "feminine_speakers.json"
DEFAULT_MAX_NEW_TOKENS = 3000  # ~35s at DAC's 86Hz frame rate; see source repo's TECHNICAL_REPORT.md
# for why this isn't 400 (the library default) -- that truncates most real utterances.

with open(BEST_SPEAKERS_PATH) as f:
    BEST_SPEAKERS = json.load(f)
with open(FEMININE_SPEAKERS_PATH) as f:
    FEMININE_SPEAKERS = json.load(f)


def _speaker_description(speaker):
    return f"{speaker}'s voice is clear and natural, speaking at a normal pace in a close-sounding, quiet recording. Very clear audio."


def _generic_description(language, gender=None):
    voice = f"{gender} {language}" if gender else language
    return f"A clear, natural {voice} voice, speaking at a normal pace in a quiet room."


def resolve_description(description=None, speaker=None, language=None, gender=None):
    if description is not None:
        return description
    if speaker is not None:
        return _speaker_description(speaker)
    if language is not None:
        if gender == "female":
            speaker = FEMININE_SPEAKERS.get(language)
            return _speaker_description(speaker) if speaker else _generic_description(language, gender="female")
        best = BEST_SPEAKERS.get(language)
        return _speaker_description(best) if best else _generic_description(language)
    raise ValueError("Pass one of: description=, speaker=, or language=")


class TTSInferencer:
    """Generates audio from text using a loaded QuantizedParlerTTS engine.

    Usage:
        engine = QuantizedParlerTTS()
        engine.load()
        tts = TTSInferencer(engine)
        tts.speak("Hello world", language="English")                   # plays it (default)
        tts.speak("नमस्ते दुनिया", language="Hindi", output="file", out_path="out.wav")
        audio, sample_rate = tts.synthesize("Hello world", language="English")
        for chunk, sr in tts.synthesize_stream("Hello world", language="English"):
            ...                                                        # feed a queue/socket
    """

    def __init__(self, engine):
        self.engine = engine

    def speak(self, text, description=None, speaker=None, language=None, gender=None,
              max_new_tokens=DEFAULT_MAX_NEW_TOKENS, output="play", out_path=None, blocking=True):
        """One call, pick where the audio goes: output="play" (default) plays it directly
        through the system's audio output (needs the optional `sounddevice` package);
        output="file" writes it to out_path= instead. synthesize()/synthesize_to_file()/
        play()/synthesize_stream() remain available directly if you want a specific one
        without the output= indirection."""
        if output == "play":
            return self.play(text, description, speaker, language, gender, max_new_tokens, blocking)
        if output == "file":
            if not out_path:
                raise ValueError('output="file" requires out_path=...')
            return self.synthesize_to_file(text, out_path, description, speaker, language, gender, max_new_tokens)
        raise ValueError(f"Unknown output={output!r}, expected 'play' or 'file'")

    def synthesize(self, text, description=None, speaker=None, language=None, gender=None,
                    max_new_tokens=DEFAULT_MAX_NEW_TOKENS):
        """Returns (audio: np.ndarray[float32], sample_rate: int).
        Pass gender="female" with language= to prefer a named female speaker -- see the
        module docstring for which languages have one confirmed vs. fall back to a
        gender-worded generic description."""
        if not self.engine.is_loaded:
            raise RuntimeError("Model not loaded -- call engine.load() first")

        description = resolve_description(description, speaker, language, gender)
        model = self.engine.model
        device = self.engine.device

        input_ids = self.engine.description_tokenizer(description, return_tensors="pt").input_ids.to(device)
        attention_mask = torch.ones_like(input_ids)
        prompt_input_ids = self.engine.tokenizer(text, return_tensors="pt").input_ids.to(device)
        prompt_attention_mask = torch.ones_like(prompt_input_ids)

        with torch.no_grad():
            generation = model.generate(
                input_ids=input_ids, attention_mask=attention_mask,
                prompt_input_ids=prompt_input_ids, prompt_attention_mask=prompt_attention_mask,
                max_new_tokens=max_new_tokens,
            )

        audio = generation.to(torch.float32).cpu().numpy().squeeze()
        if audio.ndim == 0:
            audio = np.zeros(1, dtype=np.float32)
        sample_rate = model.config.sampling_rate
        return audio, sample_rate

    def synthesize_to_file(self, text, out_path, description=None, speaker=None, language=None,
                            gender=None, max_new_tokens=DEFAULT_MAX_NEW_TOKENS):
        """Same as synthesize(), but writes a .wav file and returns its path."""
        import soundfile as sf
        audio, sample_rate = self.synthesize(text, description, speaker, language, gender, max_new_tokens)
        sf.write(out_path, audio, sample_rate)
        return out_path

    def synthesize_stream(self, text, description=None, speaker=None, language=None, gender=None,
                           max_new_tokens=DEFAULT_MAX_NEW_TOKENS, chunk_seconds=0.5):
        """Generates audio, then yields it as (chunk: np.ndarray[float32], sample_rate: int)
        pieces of ~chunk_seconds each, for feeding to a websocket/audio queue/player without
        writing a file first.

        Important: this does NOT reduce time-to-first-audio. `model.generate()` produces the
        complete waveform in one internal pass (the DAC codec needs the full predicted
        codebook sequence to decode cleanly) -- there is no partial output until generation
        finishes. This just reshapes the complete result into a streaming-shaped interface
        for the caller; true incremental (token-level) streaming would need decoding the DAC
        codec in chunks during generation, which hasn't been verified to produce artifact-free
        audio at chunk boundaries and is a bigger undertaking than this.
        """
        audio, sample_rate = self.synthesize(text, description, speaker, language, gender, max_new_tokens)
        chunk_size = max(1, int(chunk_seconds * sample_rate))
        for start in range(0, len(audio), chunk_size):
            yield audio[start:start + chunk_size], sample_rate

    def play(self, text, description=None, speaker=None, language=None, gender=None,
             max_new_tokens=DEFAULT_MAX_NEW_TOKENS, blocking=True):
        """Generates audio and plays it directly through the system's audio output --
        no file involved. Requires `sounddevice` (and a working PortAudio/sound device),
        which is NOT a hard dependency of this package since headless/embedded deployments
        (e.g. a Jetson with no sound card attached) typically won't have one -- install with
        `pip install sounddevice` if you want this on a machine that can actually play audio."""
        try:
            import sounddevice as sd
        except (ImportError, OSError) as e:
            raise RuntimeError(
                "play() needs the optional `sounddevice` package (and a working audio "
                "device/PortAudio install) -- pip install sounddevice. Use synthesize() or "
                "synthesize_to_file() instead if this machine has no audio output."
            ) from e

        audio, sample_rate = self.synthesize(text, description, speaker, language, gender, max_new_tokens)
        sd.play(audio, sample_rate)
        if blocking:
            sd.wait()

    def synthesize_long(self, text, description=None, speaker=None, language=None, gender=None,
                         max_new_tokens=DEFAULT_MAX_NEW_TOKENS, silence_gap_seconds=0.3):
        """Same as synthesize(), but splits `text` on paragraph breaks (blank lines) and
        synthesizes + concatenates each paragraph separately, instead of one single
        generate() call over the whole text. Returns (audio, sample_rate), same as synthesize().

        Not part of the upstream source repo -- an addition from this project's own testing.
        `max_new_tokens` (3000, ~35s) is a hard cap per generate() call: confirmed directly
        that a genuinely long combined answer (a real 3-paragraph agent response, ~620 chars)
        runs the single generate() call all the way to that cap -- the audio itself is real,
        not silent/degenerate (this is NOT the model_loader.py reload defect documented
        there), but a call that long is at real risk of being cut off mid-sentence rather
        than stopping naturally. Chunking per paragraph keeps each individual generate() call
        well inside a length that's confirmed to finish on its own. Use this instead of
        synthesize() for text that isn't known to be short and single-paragraph, e.g. a full
        agent answer.
        """
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        if not paragraphs:
            paragraphs = [text]

        chunks = []
        sample_rate = None
        for paragraph in paragraphs:
            audio, sample_rate = self.synthesize(paragraph, description, speaker, language, gender, max_new_tokens)
            chunks.append(audio)
            if silence_gap_seconds:
                chunks.append(np.zeros(int(silence_gap_seconds * sample_rate), dtype=audio.dtype))

        if silence_gap_seconds and chunks:
            chunks.pop()  # no trailing gap after the last paragraph

        return np.concatenate(chunks), sample_rate
