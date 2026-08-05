"""Chunked, pipelined streaming TTS on top of TTSInferencer/QuantizedParlerTTS.

The single-call `TTSInferencer.synthesize()` doesn't produce any audio until the whole input
has finished generating -- for a real agent answer that's 28s-161s of silence before anything
plays (see vyoma_v4.ipynb's own stage timing log), and a long enough answer risks hitting
`DEFAULT_MAX_NEW_TOKENS`'s truncation cliff. This module fixes both by (1) cleaning markdown
out of NMT/agent output and splitting it into sentence-safe chunks, (2) generating chunk 0
alone as fast as possible and playing it back the instant it's ready, while (3) the remaining
chunks generate `batch_size` at a time in single batched `generate()` calls in the background.

**A real dead end, corrected after listening to it, not just measuring it**: an earlier version
of this module used `parler_tts.ParlerTTSStreamer` to decode chunk 0's audio in small windows
*during* generation (a real, library-supported mechanism -- not misused) and played each window
the instant it was decoded, chasing a sub-second time-to-first-audio number. It measured well
and sounded broken -- stuttering, "o-o-o" broken-syllable audio. The cause: generation here
runs measurably slower than real-time (2.2x-4.9x for solo calls across languages on the GB10
dev workstation, see below), so playing each window in real time as it arrived meant the
output device consistently ran out of audio before the next window was ready -- an unavoidable
buffer underrun at *every* window boundary, not an occasional glitch. Sub-chunk incremental
streaming only sounds clean when generation keeps pace with playback (this is exactly how
cloud TTS APIs like Deepgram/OpenAI's chunked-transfer streaming get away with playing audio
as it arrives -- their inference keeps up with real-time; a quantized local model running
several times slower than real-time at low batch sizes does not). If a chunk has to fully finish generating before it can play back without stuttering
anyway, decoding it in windows along the way buys nothing over one plain blocking call -- same
wall-clock to "chunk ready," with unusable audio in between. So: chunk 0 is now generated with
one plain blocking `TTSInferencer.synthesize()` call, exactly like every other chunk, and only
*complete* chunks are ever handed to a player. This matches how production TTS streaming
(Deepgram, OpenAI) actually chunks and plays audio -- at the chunk boundary, not the codec-frame
boundary -- and is also just simpler: no `ParlerTTSStreamer`, no per-window thread-error
plumbing, no window-vs-chunk distinction in the yielded results.

`synthesize_stream_chunks(solo_first_chunk=True)` (its default) generates chunk 0 *alone*, not
batched with the others -- keeping its own completion time as short as possible when a caller
wants the fastest possible single ready chunk. `play_stream()` passes `solo_first_chunk=False`
instead: its smart-prebuffer strategy (below) doesn't play anything until a computed buffer
threshold is met regardless, so chunk 0's faster *solo* readiness buys nothing there, while its
worse *solo* throughput (see the batch-size findings below -- solo is the slowest configuration
measured) only slows down reaching that threshold. Batch chunk 0 in with the rest whenever nothing
is waiting on it individually; keep it solo only for a caller that actually consumes the first
yielded item immediately.

Chunks generate `batch_size` at a time in single batched `generate()` calls, because generation
here runs slower than real-time at small batch sizes (measured 2.2x-4.9x for solo/batch=1 calls
across languages on the GB10 dev workstation below; independently reported/tested at ~1.7x-1.8x
elsewhere -- slower-than-real-time either way across every source at batch=1, exact factor
varies by hardware/language/content): a naive "generate chunk N+1 only after chunk N finishes"
producer falls further behind every chunk and starves the player. Autoregressive decoding at
batch=1 is memory-bandwidth-bound, not compute-bound, so batching several chunks into one
`generate()` call (the same reason LLM/TTS serving stacks batch requests at all) is the
principled way to push throughput back under that slower-than-real-time wall -- thread-level
concurrent `generate()` calls on one shared model instance were considered and rejected:
unverified thread-safety, and GIL-interleaved calls don't add real throughput the way batching
does (confirmed: wall-clock time per `generate()` call stayed nearly flat from batch_size=1
through 16 while the audio produced per call grew almost 17x -- see the batch-size sweep below).

Only one `generate()` call is ever in flight at a time -- matches this project's stated
sequential-stage, memory-conscious design for the 8GB Jetson Orin Nano deployment target.

**Measured on the GB10 dev workstation** (dev/agents venv, real checkpoint). Findings that
shaped the defaults below, including real bugs and one abandoned approach, caught by
testing/listening rather than assumed away:

1. **Time-to-first-audio is bounded by chunk 0's own generation time, not sub-second** -- see
   the dead-end section above. Still a large win over the old whole-utterance path (28-161s):
   measured 33.8s-46.3s time-to-playback across real en/hi/ml/ta answers (4-10 chunks each,
   `batch_size=6`) once the smart-prebuffer strategy below decides enough is buffered.
2. **`max_chunk_chars` and `batch_size` interact -- a chunk size that produces too few chunks
   defeats batching regardless of `batch_size`.** At `max_chunk_chars=400`, a real ~600-char
   answer produced only 2 chunks (chunk 0 solo + 1 lone remaining chunk, too few for any
   `batch_size>1` to ever engage), and total time came out **0.64x -- 56% *slower*** than the
   old single-call path, not faster. Lowering `max_chunk_chars` to 180 reliably produces enough
   chunks (4-10 for the real per-language answers tested) for batching to have something to
   work with.
3. **Batching itself had a real bug**: HF's batch `generate()` runs every item in a batch until
   the *longest* one finishes, so shorter items came back padded with extra frames -- confirmed
   via a per-item RMS envelope against solo ground truth that this padding decodes as genuine
   silence, not garbage, but it was not negligible (1.6x-2.25x length inflation observed), which
   would have played back as real dead air after every batched chunk shorter than its
   batch-mates. Fixed with `_trim_trailing_silence()` below.
4. **Batch-size sweep (English, 16 same-length sentences, one `_generate_batch()` call per
   size) found wall-clock time nearly flat and VRAM growth small, all the way to batch=16** --
   the opposite of what "more work per call" might suggest:

   | batch_size | wall_time | peak VRAM (delta over baseline) | audio produced | RTF |
   |---|---|---|---|---|
   | 1  | 11.3s | +0.34GB | 5.1s  | 2.23x |
   | 2  | 10.3s | +0.39GB | 10.0s | 1.03x |
   | 3  | 11.3s | +0.46GB | 15.7s | 0.72x |
   | 6  | 12.3s | +0.63GB | 32.2s | 0.38x |
   | 9  | 13.3s | +0.79GB | 47.7s | 0.28x |
   | 12 | 14.1s | +0.94GB | 62.3s | 0.23x |
   | 16 | 15.2s | +1.15GB | 84.2s | 0.18x |

   Wall-clock only grew ~34% (11.3s -> 15.2s) while audio produced grew ~17x (5.1s -> 84.2s) and
   peak VRAM stayed under 2.1GB even at batch=16 -- confirms the memory-bandwidth-bound theory
   directly: reading the weights once and applying them to more sequences is nearly free up to
   at least this range. `batch_size=6` was picked as the default (not the sweep's own ceiling)
   because real answers chunked at `max_chunk_chars=180` typically produce single-digit chunk
   counts -- diminishing returns past that for realistic inputs, not a hard technical ceiling.
   **Not yet re-measured on the actual Jetson Orin Nano target** -- this sweep is GB10 only.
5. **`solo_first_chunk=False` for `play_stream()` measurably shortened the wait**, confirmed on
   the real Hindi answer used throughout this testing (4 chunks): batching chunk 0 in with the
   rest (`batch_size=3`) got all 3 pre-playback chunks done by t=45.06s, vs. t=78.88s when chunk
   0 ran solo first -- a 43% faster start, because the earlier solo call ran at the slower
   solo-RTF instead of getting the batched-call throughput benefit.
6. **Smart-prebuffer strategy (see `play_stream()`'s own docstring for the full derivation)**
   measures live RTF and estimated total duration to compute the minimum buffer that should
   avoid starving playback, instead of either playing chunk 0 instantly (audible stalls after
   almost every chunk, confirmed by listening) or waiting for the entire answer (the original
   28-161s problem). **Verified zero detected stalls across all 4 languages tested** (en: 8
   chunks/128.4s total; hi: 4 chunks/125.1s; ml: 5 chunks/105.7s; ta: 10 chunks/129.1s,
   `batch_size=6`, `buffer_margin=1.15`) -- every chunk after the buffering phase arrived before
   playback caught up to needing it.
"""
import re
import time
import queue
import threading
from typing import List, Optional, Tuple

import numpy as np
import torch

from .inference import TTSInferencer, DEFAULT_MAX_NEW_TOKENS, resolve_description

try:
    from ..nmt.inference.engine import split_sentences as _nmt_split_sentences
    from ..nmt.inference.flores_codes_map_indic import iso_to_flores
    _NMT_SENTENCE_SPLITTER_AVAILABLE = True
except ImportError:
    _NMT_SENTENCE_SPLITTER_AVAILABLE = False
    iso_to_flores = {}

# Convenience default for the pipeline's current languages: lets callers pass just language=
# (the same full-name value TTSInferencer.synthesize() already takes) and still get proper
# Indic-aware sentence splitting without also having to pass sentence_lang= explicitly. Any
# language outside this set needs sentence_lang= passed explicitly (iso code or flores code) --
# falls back to the regex splitter below otherwise, not a hard error.
_TTS_NAME_TO_ISO = {"English": "en", "Hindi": "hi", "Malayalam": "ml", "Tamil": "ta", "Gujarati": "gu"}

# Devanagari/other Indic full stops (।, ॥) included alongside standard Latin/Arabic punctuation --
# only used when the proper per-language splitter above isn't available/resolvable.
_SENTENCE_FALLBACK_RE = re.compile(r"(?<=[.!?।॥؟])\s+")


# ---------------------------------------------------------------------------
# 1. Markdown/whitespace cleaning
# ---------------------------------------------------------------------------

_CODE_FENCE_RE = re.compile(r"^[ \t]*```[^\n]*\n?", re.MULTILINE)
_HR_RE = re.compile(r"^[ \t]*([-*_])(?:[ \t]*\1){2,}[ \t]*$", re.MULTILINE)
_HEADER_RE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+", re.MULTILINE)
_BLOCKQUOTE_RE = re.compile(r"^[ \t]*>[ \t]?", re.MULTILINE)
_BULLET_RE = re.compile(r"^[ \t]*[-*+][ \t]+", re.MULTILINE)
_NUMBERED_RE = re.compile(r"^[ \t]*\d+[.)][ \t]+", re.MULTILINE)
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.DOTALL)
_STRIKE_RE = re.compile(r"~~(.+?)~~", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)|(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", re.DOTALL)
_LEFTOVER_MD_RE = re.compile(r"[*_`#~]")
_INLINE_WHITESPACE_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    """Strips common markdown formatting (bold/italic/code/headers/bullets/links/etc.) out of
    agent/NMT output, leaving plain speakable prose. Paragraph breaks (blank lines) are
    preserved -- `chunk_text()` uses them as a chunk-boundary signal."""
    if not text:
        return ""
    text = _CODE_FENCE_RE.sub("", text)
    text = _HR_RE.sub("", text)
    text = _HEADER_RE.sub("", text)
    text = _BLOCKQUOTE_RE.sub("", text)
    text = _BULLET_RE.sub("", text)
    text = _NUMBERED_RE.sub("", text)
    text = _IMAGE_RE.sub(r"\1", text)
    text = _LINK_RE.sub(r"\1", text)
    text = _BOLD_RE.sub(lambda m: m.group(1) or m.group(2), text)
    text = _STRIKE_RE.sub(r"\1", text)
    text = _INLINE_CODE_RE.sub(r"\1", text)
    text = _ITALIC_RE.sub(lambda m: m.group(1) or m.group(2), text)
    text = _LEFTOVER_MD_RE.sub("", text)
    text = _INLINE_WHITESPACE_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# 2. Sentence-aware chunking
# ---------------------------------------------------------------------------

def _split_sentences(paragraph: str, sentence_lang: Optional[str]) -> List[str]:
    """Proper Indic-aware sentence splitting when possible (reuses the same
    `split_sentences()` the NMT engine already relies on -- indic_nlp_library/Moses/NLTK under
    the hood, handles Devanagari danda etc.), falling back to a regex split otherwise. Never
    raises -- worst case is the weaker regex fallback, not a crash."""
    if sentence_lang and _NMT_SENTENCE_SPLITTER_AVAILABLE:
        flores_lang = iso_to_flores.get(sentence_lang, sentence_lang)
        try:
            sentences = [s.strip() for s in _nmt_split_sentences(paragraph, flores_lang) if s.strip()]
            if sentences:
                return sentences
        except Exception:
            pass
    return [s.strip() for s in _SENTENCE_FALLBACK_RE.split(paragraph.strip()) if s.strip()]


def chunk_text(text: str, sentence_lang: Optional[str] = None, max_chunk_chars: int = 180) -> List[str]:
    """Cleans `text` and splits it into chunks bounded by `max_chunk_chars`, cut only at
    sentence or paragraph boundaries -- never mid-sentence. A paragraph break always forces a
    new chunk (even under budget); a single sentence longer than `max_chunk_chars` is kept
    whole rather than mutilated."""
    cleaned = clean_text(text)
    if not cleaned:
        return []

    chunks: List[str] = []
    for paragraph in (p.strip() for p in cleaned.split("\n\n")):
        if not paragraph:
            continue
        current = ""
        for sentence in _split_sentences(paragraph, sentence_lang):
            candidate = f"{current} {sentence}".strip() if current else sentence
            if current and len(candidate) > max_chunk_chars:
                chunks.append(current)
                current = sentence
            else:
                current = candidate
        if current:
            chunks.append(current)
    return chunks


# ---------------------------------------------------------------------------
# 3. Generation primitives (one per chunk-generation strategy)
# ---------------------------------------------------------------------------

def _encode_description(engine, description: str):
    input_ids = engine.description_tokenizer(description, return_tensors="pt").input_ids.to(engine.device)
    attention_mask = torch.ones_like(input_ids)
    return input_ids, attention_mask


def _trim_trailing_silence(audio: np.ndarray, sample_rate: int, threshold: float = 5e-3,
                            keep_tail_sec: float = 0.15) -> np.ndarray:
    """Batched generation runs every item in the batch until the *longest* item's sequence
    finishes, so shorter items come back padded with real, measured trailing silence (not
    garbage -- confirmed via a per-item RMS envelope check against solo-generated ground
    truth: batched items matched their solo duration almost exactly up to a clean drop to
    ~0 RMS, then flat silence for the rest). That padding is not negligible though -- observed
    1.6x-2.25x length inflation for a batch with mixed-length items -- so it's trimmed back
    down here (keeping a small tail so the cut isn't abrupt) rather than left in, since a
    concatenated multi-chunk answer would otherwise carry several real seconds of dead air
    after every batched chunk shorter than its batch-mates."""
    above = np.flatnonzero(np.abs(audio) > threshold)
    if above.size == 0:
        return audio
    end = min(len(audio), above[-1] + 1 + int(keep_tail_sec * sample_rate))
    return audio[:end]


def _generate_batch(engine, texts: List[str], description: str,
                     max_new_tokens: int) -> Tuple[List[np.ndarray], int]:
    """One batched `generate()` call for several chunk texts at once (padded prompt token ids +
    attention mask). Returns (list of per-chunk float32 waveforms in input order, sample_rate),
    each trimmed of the batch-padding trailing silence described in `_trim_trailing_silence()`.
    Note: because the batch's wall-clock time is set by its *longest* item regardless of the
    others' padding, batching mixed-length chunks together gives less of a throughput win than
    batching similar-length chunks -- see the module docstring's measured numbers."""
    model = engine.model
    batch_size = len(texts)

    desc_input_ids, desc_attention_mask = _encode_description(engine, description)
    input_ids = desc_input_ids.expand(batch_size, -1)
    attention_mask = desc_attention_mask.expand(batch_size, -1)

    prompt_enc = engine.tokenizer(texts, return_tensors="pt", padding=True)
    prompt_input_ids = prompt_enc.input_ids.to(engine.device)
    prompt_attention_mask = prompt_enc.attention_mask.to(engine.device)

    with torch.no_grad():
        generation = model.generate(
            input_ids=input_ids, attention_mask=attention_mask,
            prompt_input_ids=prompt_input_ids, prompt_attention_mask=prompt_attention_mask,
            max_new_tokens=max_new_tokens,
        )

    sample_rate = model.config.sampling_rate
    audio_batch = generation.to(torch.float32).cpu().numpy()
    results = []
    for row in audio_batch:
        audio = np.squeeze(row)
        if audio.ndim == 0 or audio.size == 0:
            audio = np.zeros(1, dtype=np.float32)
        else:
            audio = _trim_trailing_silence(audio, sample_rate)
        results.append(audio)
    return results, sample_rate


def _float32_to_int16_bytes(audio: np.ndarray) -> bytes:
    return (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()


def _release_cuda_cache(engine):
    """Returns the CUDA caching allocator's freed blocks to the driver after a chunk/batch
    finishes, instead of letting them sit reserved for reuse until the process unloads.

    Measured directly (dev/local_model_test/tts_memory_log.txt): without this, a long
    multi-chunk answer's peak reserved memory ratchets up to whatever the single largest
    chunk needed and never comes back down, even though every chunk after it is smaller and
    doesn't need that much -- e.g. solo/batch_size=1 chunking held at ~2.95GB reserved for
    the rest of an answer after one 13.6s chunk, when every individual chunk (including that
    one) only ever needed ~0.9GB. Calling this after each chunk/batch instead tracks the
    *current* chunk's actual need: confirmed the same answer's peak reserved drops to ~0.91GB
    at batch_size=1, and from 4.28GB to 3.70GB at batch_size=6 (batch_size>1 keeps some cost
    -- clearing can't shrink the peak of whichever single batched call is the largest, only
    stop a later, smaller call from inheriting an earlier, larger one's leftovers).
    Synchronizes first so the clear happens after this chunk's work is actually done, not
    while it's still in flight. Cost is negligible next to a multi-second generate() call."""
    if torch.cuda.is_available():
        torch.cuda.synchronize(engine.device)
        torch.cuda.empty_cache()


# ---------------------------------------------------------------------------
# 4. Orchestration
# ---------------------------------------------------------------------------

class StreamingTTS:
    """Wraps a `TTSInferencer` to add chunked, pipelined generation on top of it.

    Usage:
        engine = QuantizedParlerTTS(); engine.load()
        tts = TTSInferencer(engine)
        streaming = StreamingTTS(tts)
        for audio, sr, chunk, idx, total in streaming.synthesize_stream_chunks(
            long_answer, language="Hindi", sentence_lang="hi"
        ):
            ...  # feed a queue/socket/player -- each item is one COMPLETE chunk's audio

        streaming.play_stream(long_answer, language="Hindi", sentence_lang="hi")  # local speakers
    """

    def __init__(self, tts_inferencer: TTSInferencer):
        self.tts = tts_inferencer

    def synthesize_stream_chunks(self, text, description=None, speaker=None, language=None,
                                  gender=None, sentence_lang=None,
                                  max_new_tokens=DEFAULT_MAX_NEW_TOKENS, max_chunk_chars=180,
                                  batch_size=6, solo_first_chunk=True):
        """Cleans + chunks `text`, then generates and yields audio in order, one COMPLETE chunk
        at a time: `(audio: np.ndarray[float32], sample_rate: int, chunk_text: str,
        chunk_index: int, total_chunks: int)`.

        `solo_first_chunk=True` (default): chunk 0 generates alone (one plain
        `TTSInferencer.synthesize()` call) so it's ready as fast as possible -- see the module
        docstring for why this is a whole-chunk blocking call and not a sub-chunk incremental
        stream (that was tried and audibly didn't work: generation here is slower than
        real-time, so playing partial audio while more of the same chunk is still generating
        underruns). Remaining chunks generate `batch_size` at a time in a single batched
        `generate()` call each. Pass `solo_first_chunk=False` to batch chunk 0 in with the rest
        from the start instead -- worse for time-to-*a*-ready-chunk (chunk 0 now waits on
        whatever it's batched with, same as any other batch), but better throughput during that
        first call, which is the right tradeoff for a caller that isn't going to play anything
        until it's accumulated a buffer anyway (`play_stream()`'s smart-prebuffer strategy does
        exactly this -- solo chunk 0 was pure waste there, since nothing played until well after
        it was generated regardless, so its faster individual readiness bought nothing while its
        worse solo throughput cost time getting the buffer filled).

        See the module docstring for why batching, not thread concurrency, is used to keep
        generation throughput ahead of playback. Falls back to plain sequential
        `TTSInferencer.synthesize()` per chunk if batched generation raises for any reason.

        `sentence_lang` (iso-2-letter or flores code, e.g. "hi") drives sentence-boundary
        detection for chunking -- defaults from `language=` for this pipeline's known languages
        (English/Hindi/Malayalam/Tamil/Gujarati); pass it explicitly for anything else.

        `batch_size=1` disables batching (fully sequential solo chunks): each item becomes
        available as soon as it alone finishes, instead of waiting for `batch_size` chunks
        together (a batch only returns once its *slowest* member is done) -- the safer choice
        on a memory-constrained deployment target until batching is benchmarked there.
        """
        engine = self.tts.engine
        if not engine.is_loaded:
            raise RuntimeError("Model not loaded -- call engine.load() first")

        sentence_lang = sentence_lang or (_TTS_NAME_TO_ISO.get(language) if language else None)
        chunks = chunk_text(text, sentence_lang=sentence_lang, max_chunk_chars=max_chunk_chars)
        if not chunks:
            return

        resolved_description = resolve_description(description, speaker, language, gender)
        total_chunks = len(chunks)
        batch_size = max(1, batch_size)

        result_queue: "queue.Queue" = queue.Queue()
        _SENTINEL = object()

        def _emit_fallback(chunk_index):
            audio, sr = self.tts.synthesize(chunks[chunk_index], description=resolved_description,
                                             max_new_tokens=max_new_tokens)
            result_queue.put((audio, sr, chunks[chunk_index], chunk_index, total_chunks))

        def producer():
            try:
                idx = 0
                if solo_first_chunk:
                    _emit_fallback(0)  # chunk 0: solo, plain blocking call -- fastest to be ready
                    _release_cuda_cache(engine)
                    idx = 1

                while idx < total_chunks:
                    batch = chunks[idx: idx + batch_size]
                    try:
                        if len(batch) > 1:
                            audios, sr = _generate_batch(engine, batch, resolved_description, max_new_tokens)
                            for offset, audio in enumerate(audios):
                                result_queue.put((audio, sr, batch[offset], idx + offset, total_chunks))
                        else:
                            _emit_fallback(idx)
                    except Exception:
                        for offset in range(len(batch)):
                            _emit_fallback(idx + offset)
                    _release_cuda_cache(engine)
                    idx += len(batch)
            finally:
                result_queue.put(_SENTINEL)

        producer_thread = threading.Thread(target=producer, daemon=True)
        producer_thread.start()
        while True:
            item = result_queue.get()
            if item is _SENTINEL:
                break
            yield item
        producer_thread.join()

    def play_stream(self, text, description=None, speaker=None, language=None, gender=None,
                     sentence_lang=None, max_new_tokens=DEFAULT_MAX_NEW_TOKENS, max_chunk_chars=180,
                     batch_size=6, backend="sounddevice", device=None, gap_seconds=0.5,
                     buffer_margin=1.15, blocking=True, debug=False):
        """Plays `text` chunk-by-chunk, via one of two backends, using a **smart prebuffer**
        so that -- as long as the measured generation rate holds roughly steady -- playback
        never runs dry once it starts, instead of starting instantly and then stalling.

        Why: generation here runs slower than real-time by some factor `r` (measured
        1.8x-3.9x depending on hardware/language/batching, see the module docstring). Two
        naive strategies were tried and both have a real problem, confirmed by listening, not
        just reasoned about:
        - Start playing the instant chunk 0 is ready: lowest possible time-to-first-audio, but
          every chunk after that stalls, because generation can't keep up with playback once
          both are running -- audible dead air after almost every chunk.
        - Wait for the *entire* answer before playing anything (the old `synthesize_long()`
          path): zero gaps, but time-to-first-audio is `r` times the whole answer's duration --
          the original 28-161s problem this module exists to fix.

        This is the standard fix from adaptive-bitrate streaming: buffer enough *before*
        starting that generation -- continuing in the background the whole time -- finishes
        the remainder before playback catches up. The minimum buffer that guarantees this
        (derived from: buffer drains at rate `1 - 1/r` once both are running) is
        `total_duration * (r-1)/r` -- at `r=1.77` that's ~43.5% of the answer's total duration
        buffered before playback starts. Worse time-to-first-audio than "play chunk 0
        instantly," but still much better than "wait for everything" (`(r-1)/r` of the wait,
        vs. all of it), and -- unlike either naive strategy -- shouldn't stall partway through.

        `r` isn't hardcoded: it's measured live from the chunks generated so far (audio
        duration produced / wall-clock spent), and total duration is estimated by extrapolating
        that same chunks' char-to-seconds ratio across the full text's character count (chunk
        boundaries are computed upfront, before any generation, so the total character count is
        known immediately). The buffer threshold is recomputed after every chunk as both
        estimates improve. `buffer_margin` (default 1.15) inflates the computed threshold by
        15% as a safety margin against per-chunk variance around the average rate -- this is an
        expected-case guarantee from an averaged rate estimate, not a hard one.

        `batch_size` (default 3) still controls how many chunks generate together per
        `generate()` call during the buffering phase and after -- see
        `synthesize_stream_chunks()`'s docstring for the throughput-vs-latency-distribution
        tradeoff; it matters less here than it did before this prebuffer existed, since the
        buffer is what's actually responsible for hiding batch-sized gaps now. Passes
        `solo_first_chunk=False` to `synthesize_stream_chunks()` -- chunk 0 gets batched in with
        the rest from the start rather than generated alone, since nothing plays until the
        buffer threshold is met regardless, so chunk 0's faster *solo* readiness buys nothing
        here while its worse solo throughput would only slow down reaching that threshold.

        backend="sounddevice" (default) -- local speaker output for dev-machine/notebook use.
            Needs the optional `sounddevice` package (pip install sounddevice), same as
            inference.py's play(). This is the GB10/dev-workstation path.
        backend="pocketinfer" -- the production on-device path, via
            suno-sutra-sw/python/pocketinfer/audio.py's `AudioPlayer` (ffplay piped to ALSA) --
            the same sink pocketinfer/models/piper.py's `Piper` class already uses. Needs
            `suno-sutra-sw/python` importable (installed, or that directory on PYTHONPATH) in
            whatever environment runs this -- true on the real device deployment, **not**
            installed in this repo's own dev venv today (confirmed) -- plus `ffplay`/ALSA
            available. Pass `device=` as the ALSA device name that project's `AudioPlayer`
            expects (defaults to `"default"`).

        `gap_seconds` (default 0.5) is a pause inserted between chunks during playback.

        `blocking=False` runs the whole consume-and-play loop on a background thread and
        returns immediately with a handle exposing `.stop()`/`.join()` -- mirrors
        `pocketinfer/models/piper.py`'s `Piper.start_playback()`/`stop_playback()` shape, so
        `play_stream(..., backend="pocketinfer", blocking=False)` is a structural drop-in for
        how `Piper` is called from pocketinfer's applications today, whenever that swap is
        wanted (rewiring the application code itself is out of scope here).
        """
        sentence_lang_resolved = sentence_lang or (_TTS_NAME_TO_ISO.get(language) if language else None)
        total_chars = sum(len(c) for c in chunk_text(text, sentence_lang=sentence_lang_resolved,
                                                       max_chunk_chars=max_chunk_chars)) or 1

        chunk_stream_raw = self.synthesize_stream_chunks(
            text, description=description, speaker=speaker, language=language, gender=gender,
            sentence_lang=sentence_lang, max_new_tokens=max_new_tokens, max_chunk_chars=max_chunk_chars,
            batch_size=batch_size, solo_first_chunk=False,
        )
        # The shared playback core (_smart_prebuffer_playback, below) is source-agnostic --
        # it only needs (audio, sample_rate, chunk_chars, chunk_index, total_chunks) tuples,
        # not the actual chunk text, so this is the one adapter line needed to feed it from
        # a local generate() call. play_http_stream() (below) feeds it from decoded HTTP
        # NDJSON lines instead -- identical buffering/playback math either way, only the
        # chunk source differs. See that function's docstring for why this refactor exists.
        chunk_stream = ((audio, sr, len(chunk_txt), idx, total)
                         for audio, sr, chunk_txt, idx, total in chunk_stream_raw)

        return _launch_playback(chunk_stream, total_chars, backend, device, gap_seconds,
                                 buffer_margin, blocking, debug)


class _PlaybackHandle:
    """Returned by `play_stream(..., blocking=False)` -- mirrors Piper's start/stop shape.

    `.chunks` accumulates every (audio, sample_rate) pair as it arrives from the producer,
    regardless of playback state -- lets a caller that wants to *both* play live *and* save
    the complete audio to disk (e.g. test_orchestrated_pipeline.py) get both from one
    generation pass instead of a second, wasteful round-trip. `.full_audio()` concatenates
    them. Populated whether or not playback actually consumed a given chunk (e.g. if
    `.stop()` was called mid-stream, `.chunks` still has everything generated up to that
    point, even if some of it was never played)."""

    def __init__(self):
        self.stopped = False
        self._thread = None
        self._done = threading.Event()
        self.chunks: List[Tuple[np.ndarray, int]] = []

    def stop(self):
        self.stopped = True

    def join(self, timeout=None):
        if self._thread is not None:
            self._thread.join(timeout)
        else:
            self._done.wait(timeout)

    def _mark_done(self):
        self._done.set()

    def full_audio(self):
        """Concatenates every chunk received so far into one (audio, sample_rate) pair.
        Raises if nothing was ever received, or if sample rate changed mid-stream (would
        indicate a real bug upstream -- every sink already enforces this same invariant)."""
        if not self.chunks:
            raise RuntimeError("no audio chunks were received")
        sample_rate = self.chunks[0][1]
        for _, sr in self.chunks[1:]:
            if sr != sample_rate:
                raise RuntimeError(f"sample rate changed mid-stream ({sample_rate} -> {sr})")
        return np.concatenate([a for a, _ in self.chunks]), sample_rate


class _SounddeviceSink:
    """Plays through one persistent `sd.OutputStream`, not a `sd.play()`/`sd.wait()` call per
    chunk -- `sd.play()` opens a *new* playback stream each call, and that startup/stop
    overhead between consecutive calls is audible as a click. Every item handed to this sink is
    now always one complete, already-fully-generated chunk (see the module docstring for why
    this module stopped handing it partial/incremental audio), so there's no risk of the
    stream running dry mid-write; this class is purely about avoiding the inter-call click, not
    about pacing a producer that's still generating. `gap_seconds` between chunks (in
    `play_stream()`) still comes through as a real pause since no new samples are written to
    the stream during that sleep -- that's intentional, not a bug."""

    def __enter__(self):
        try:
            import sounddevice as sd
        except (ImportError, OSError) as e:
            raise RuntimeError(
                "backend='sounddevice' needs the optional `sounddevice` package (and a working "
                "audio device/PortAudio install) -- pip install sounddevice. Use backend="
                "'pocketinfer' instead on a device with no local sound card."
            ) from e
        self._sd = sd
        self._stream = None
        self._sample_rate = None
        return self

    def __exit__(self, *exc_info):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def play(self, audio: np.ndarray, sample_rate: int):
        if self._stream is None:
            self._sample_rate = sample_rate
            self._stream = self._sd.OutputStream(samplerate=sample_rate, channels=1, dtype="float32")
            self._stream.start()
        elif sample_rate != self._sample_rate:
            raise RuntimeError(f"Sample rate changed mid-stream ({self._sample_rate} -> {sample_rate})")
        self._stream.write(np.ascontiguousarray(audio, dtype=np.float32))


class _PocketinferSink:
    def __init__(self, device=None):
        self.device = device or "default"
        self._AudioPlayer = None
        self._player = None
        self._sample_rate = None

    def __enter__(self):
        try:
            from pocketinfer.audio import AudioPlayer
        except ImportError as e:
            raise RuntimeError(
                "backend='pocketinfer' needs suno-sutra-sw/python's `pocketinfer` package "
                "importable (installed, or that directory on PYTHONPATH) -- true on the real "
                "device deployment, not installed in this repo's own dev venv today. See "
                "suno-sutra-sw/python/pocketinfer/audio.py."
            ) from e
        self._AudioPlayer = AudioPlayer
        return self

    def __exit__(self, *exc_info):
        if self._player is not None:
            self._player.__exit__(*exc_info)
            self._player = None

    def play(self, audio: np.ndarray, sample_rate: int):
        if self._player is None:
            self._sample_rate = sample_rate
            self._player = self._AudioPlayer(sample_rate, device=self.device).__enter__()
        elif sample_rate != self._sample_rate:
            raise RuntimeError(f"Sample rate changed mid-stream ({self._sample_rate} -> {sample_rate})")
        self._player.play(_float32_to_int16_bytes(audio))


# ---------------------------------------------------------------------------------------
# Shared smart-prebuffer playback core -- extracted from play_stream()'s own logic so
# play_http_stream() (below) can reuse the identical buffering/playback math against chunks
# arriving over HTTP instead of a local generate() call. Neither function knows or cares
# where its chunks come from; both just need a `chunk_stream` iterable yielding
# (audio, sample_rate, chunk_chars, chunk_index, total_chunks) tuples.
# ---------------------------------------------------------------------------------------

def _smart_prebuffer_playback(chunk_stream, total_chars, sink, handle, gap_seconds, buffer_margin,
                               debug, gen_t0=None):
    """The exact buffering/playback algorithm play_stream()'s own docstring derives --
    moved here verbatim, only `chunk_txt` (a string, used solely for its `len()`) became
    `chunk_chars` (an int already) so a caller decoding an HTTP stream doesn't need to
    reconstruct or transmit the actual chunk text, just its length.

    `gen_t0`: defaults to "right now" if not given (play_stream()'s local case -- correct
    there, since nothing meaningful happens before this function's own for-loop starts
    pulling from the local generator). play_http_stream() passes its own true start time
    explicitly instead -- **this matters for correctness, not just precision**. Caught for
    real during testing: play_http_stream() has to peek the first chunk before this function
    even runs (it needs total_chars, embedded in that first chunk's JSON, before the
    buffering math can start) -- if gen_t0 defaulted to "now" the way it does for the local
    case, that peek's very real network+generation time would be invisible to the RTF
    estimate, making chunk 1 look like it arrived instantly (elapsed_gen=0s) and skipping
    the buffer entirely -- then every following chunk stalled for real, audible dead air,
    because the true generation rate was never actually fast. Threading the real start time
    through explicitly fixes this at the root instead of working around the symptom."""
    pending: List[Tuple[np.ndarray, int]] = []
    buffered_duration = 0.0
    buffered_chars = 0
    gen_t0 = gen_t0 if gen_t0 is not None else time.perf_counter()
    started_playing = False
    is_first_play = True

    def _flush():
        nonlocal pending, is_first_play
        for a, sr in pending:
            if handle.stopped:
                break
            if not is_first_play:
                time.sleep(gap_seconds)
            sink.play(a, sr)
            is_first_play = False
        pending = []

    ready_since = None  # wall-clock time this chunk became available from the producer

    for audio, sample_rate, chunk_chars, chunk_index, total in chunk_stream:
        now = time.perf_counter()
        elapsed_gen = now - gen_t0
        handle.chunks.append((audio, sample_rate))  # always recorded, played or not -- see
        # _PlaybackHandle.full_audio()'s docstring
        if handle.stopped:
            break
        pending.append((audio, sample_rate))
        buffered_duration += len(audio) / sample_rate
        buffered_chars += chunk_chars

        if not started_playing:
            running_rtf = elapsed_gen / max(buffered_duration, 1e-6)
            est_total_duration = total_chars * (buffered_duration / max(buffered_chars, 1))
            needed_buffer = (
                est_total_duration * (running_rtf - 1) / running_rtf * buffer_margin
                if running_rtf > 1 else 0.0
            )
            if debug:
                print(f"    [buffer] chunk {chunk_index + 1}/{total}  "
                      f"elapsed_gen={elapsed_gen:.2f}s  buffered={buffered_duration:.2f}s  "
                      f"running_rtf={running_rtf:.2f}x  est_total={est_total_duration:.2f}s  "
                      f"needed={needed_buffer:.2f}s  "
                      f"{'STARTING PLAYBACK NOW' if buffered_duration >= needed_buffer or chunk_index == total - 1 else 'still buffering'}")
            if buffered_duration >= needed_buffer or chunk_index == total - 1:
                started_playing = True
                _flush()
                ready_since = time.perf_counter()  # playback caught up to here
        else:
            # If this chunk arrived *after* playback would have already consumed everything
            # queued so far, that gap is a real, audible stall -- not just a number derived
            # from RTF math. wait_before_this_chunk is that gap (0 or negative means it was
            # ready in time, no stall).
            wait_before_this_chunk = now - ready_since if ready_since is not None else 0.0
            if debug:
                status = (f"STALL: waited {wait_before_this_chunk:.2f}s for this chunk"
                          if wait_before_this_chunk > 0.05 else "ready in time, no stall")
                print(f"    [play] chunk {chunk_index + 1}/{total}  "
                      f"elapsed_gen={elapsed_gen:.2f}s  {status}")
            _flush()
            ready_since = time.perf_counter()  # playback caught up to here


def _launch_playback(chunk_stream, total_chars, backend, device, gap_seconds, buffer_margin,
                      blocking, debug, gen_t0=None):
    """Builds the sink + handle, then runs `_smart_prebuffer_playback` either inline
    (blocking=True) or on a background thread (blocking=False) -- the launch/threading
    boilerplate `play_stream()` and `play_http_stream()` both need, identically. `gen_t0`
    just passes through -- see `_smart_prebuffer_playback`'s own docstring for why it isn't
    always "now"."""
    if backend == "sounddevice":
        sink = _SounddeviceSink()
    elif backend == "pocketinfer":
        sink = _PocketinferSink(device=device)
    else:
        raise ValueError(f"Unknown backend={backend!r}, expected 'sounddevice' or 'pocketinfer'")

    handle = _PlaybackHandle()

    def _run():
        try:
            with sink:
                _smart_prebuffer_playback(chunk_stream, total_chars, sink, handle, gap_seconds,
                                           buffer_margin, debug, gen_t0=gen_t0)
        finally:
            handle._mark_done()

    if blocking:
        _run()
        return handle
    thread = threading.Thread(target=_run, daemon=True)
    handle._thread = thread
    thread.start()
    return handle


def play_http_stream(gateway_url, text, language, batch_size=None, speaker=None, gender=None,
                      description=None, backend="sounddevice", device=None, gap_seconds=0.5,
                      buffer_margin=1.35, blocking=True, debug=False, timeout=300):
    """Same smart-prebuffer playback as `StreamingTTS.play_stream()`, but consumes chunks
    from the TTS worker's `/infer_stream` HTTP endpoint (proxied through the gateway) instead
    of calling a local engine directly -- this is what actually gets the real
    time-to-first-audio benefit through to a caller like test_orchestrated_pipeline.py.
    `/tts/infer` (the original, non-streaming endpoint) cannot provide this: it collects
    every chunk into one response before returning anything at all -- confirmed directly by
    reading `worker_base.py`'s plain `return infer_fn(...)` and `tts_worker.py`'s blocking
    `for ... : chunks_audio.append(...)` loop, no `yield`/`StreamingResponse` anywhere in
    that path. `/infer_stream` (`tts_worker.py`'s `_stream_infer`, exposed through
    `gateway.py`'s dedicated streaming passthrough -- the generic proxy buffers everything
    the same way `/infer` does, so a real fix needed both the worker AND the gateway) is
    the endpoint built specifically to fix that, streaming newline-delimited JSON
    (`{"chunk_index", "total_chunks", "total_chars", "chunk_chars", "sample_rate",
    "audio_base64"}` per line) as each chunk/batch becomes ready server-side.

    Works for both TTS engines transparently -- mms_tts always sends exactly one line
    (`chunk_index == total - 1 == 0`), which the same buffering algorithm above already
    treats as "play immediately, nothing to buffer for" without any special-casing needed.

    `buffer_margin` defaults to **1.35 here, not 1.15** (`play_stream()`'s proven-safe local
    value) -- real HTTP round-trip latency per chunk (base64 encode/decode, JSON
    (de)serialization, the network hop itself) is genuine added time local generation never
    pays, on top of the same underlying generation time, so a slightly larger margin is kept
    as real headroom against that. This is NOT the fix for the big bug this function used to
    have, though -- see the reader-thread note below for that; the margin alone never fixed
    it (stalls were observed at both 1.15 and 1.35 before the reader thread existed -- no
    margin can compensate for a socket that briefly stops being read at all). 1.35 combined
    with the reader thread measured zero stalls on a real test
    (`test_streaming_tts_http.py`, debug=True); 1.15 combined with the reader thread hasn't
    been separately re-tested, so don't read this as proof 1.35 specifically is the minimum
    needed -- only that it works.

    **The reader thread below is what actually made this path stall-free, not the margin.**
    Root-caused via matched server-side and client-side timestamps, not guessed: the
    original version of this function read the HTTP response and played audio on the SAME
    thread. `_smart_prebuffer_playback`'s `sink.play()` blocks for real, wall-clock seconds
    while flushing a buffered batch (by design -- that's how it paces itself against
    real-time audio) -- and while that thread was blocked playing ~37s of audio, it wasn't
    reading the HTTP response either, so nothing drained the socket for that whole window.
    The worker had already finished generating and sending the next chunk during that time,
    but it just sat unread in a TCP buffer until playback caught up -- looking exactly like a
    generation stall that never actually happened. `synthesize_stream_chunks()` (the local
    case `play_stream()` uses) never hits this because its own producer already runs on an
    independent thread, decoupled from whatever the consumer does; the reader thread below
    gives this HTTP path that same decoupling, and is the real fix -- confirmed by comparing
    a run with it against a run without: identical margin, stalls present without the thread,
    zero stalls with it.

    `handle.full_audio()` returns the complete generated audio after playback finishes --
    lets a caller both play live *and* save the full answer to disk from one generation
    pass, no second network round-trip needed.
    """
    import base64
    import io
    import itertools
    import json

    import requests
    import soundfile as sf

    payload = {"text": text, "language": language}
    if batch_size is not None:
        payload["batch_size"] = batch_size
    if speaker:
        payload["speaker"] = speaker
    if gender:
        payload["gender"] = gender
    if description:
        payload["description"] = description

    # Captured BEFORE the request goes out, not after -- see _smart_prebuffer_playback's
    # docstring for exactly why this matters (a bug caught during real testing, not a
    # precision nicety): the first chunk has to be peeked below before playback's own
    # buffering math can even start, and that peek is real, non-trivial network+generation
    # time that the RTF estimate needs to see, or it concludes generation was instant and
    # skips buffering entirely -- then every following chunk stalls for real.
    gen_t0 = time.perf_counter()
    response = requests.post(f"{gateway_url}/tts/infer_stream", json=payload, stream=True, timeout=timeout)
    response.raise_for_status()

    total_chars_box = [1]

    def _decode_lines():
        for line in response.iter_lines():
            if not line:
                continue
            item = json.loads(line)
            # A failure mid-generation can't become an HTTP error status once streaming has
            # already started (the 200 OK header is long since sent) -- worker_base.py's
            # /infer_stream signals it in-band instead, one final line carrying "error"
            # instead of a real chunk. Never treat this as audio.
            if "error" in item:
                raise RuntimeError(f"TTS worker failed mid-stream: {item['error']}")
            total_chars_box[0] = item["total_chars"]
            raw = base64.b64decode(item["audio_base64"])
            audio, sr = sf.read(io.BytesIO(raw), dtype="float32")
            yield audio, sr, item["chunk_chars"], item["chunk_index"], item["total_chunks"]

    # Network reading + decoding runs on its OWN thread, decoupled from whatever the playback
    # consumer does with each chunk once it has it -- root-caused as a REAL bug during
    # testing, not a theoretical concern. _smart_prebuffer_playback's consumer blocks for
    # real, wall-clock seconds inside sink.play() while flushing a buffered batch (by design
    # -- that's how it paces itself against real-time audio). If that SAME thread were also
    # the one reading the HTTP response (the original version of this function), nothing
    # drains the socket during that block -- confirmed via matched server+client diagnostic
    # timestamps: the worker had already finished generating the next chunk and sent it, but
    # it just sat unread in a TCP buffer until playback caught up, looking exactly like a
    # generation stall it never actually was. `synthesize_stream_chunks()` (the local,
    # non-HTTP case `play_stream()` uses) never hits this because its own producer already
    # runs on an independent thread; this gives the HTTP case that same decoupling.
    result_queue: "queue.Queue" = queue.Queue()
    _SENTINEL = object()

    def _reader():
        try:
            for item in _decode_lines():
                result_queue.put(item)
        except Exception as exc:
            result_queue.put(exc)
        finally:
            result_queue.put(_SENTINEL)

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()

    def _queued_chunk_stream():
        while True:
            item = result_queue.get()
            if item is _SENTINEL:
                break
            if isinstance(item, Exception):
                raise item
            yield item
        reader_thread.join()

    chunk_iter = _queued_chunk_stream()
    # total_chars needs to be known *before* the buffering math can run, but it only arrives
    # embedded in the first streamed line -- peek it (the reader thread keeps draining the
    # socket in the background regardless of this peek, so it doesn't reintroduce the same
    # problem the direct-iteration version had), then splice it back onto the front of the
    # stream so no chunk is lost.
    try:
        first = next(chunk_iter)
    except StopIteration:
        raise RuntimeError("TTS stream produced no audio chunks (empty response from /infer_stream)")
    chunk_stream = itertools.chain([first], chunk_iter)
    total_chars = total_chars_box[0]

    return _launch_playback(chunk_stream, total_chars, backend, device, gap_seconds,
                             buffer_margin, blocking, debug, gen_t0=gen_t0)
