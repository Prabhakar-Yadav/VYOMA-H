"""clean_text() -- strips markdown out of agent/NMT output for TTS, extracted out of
models/tts_exports/streaming.py into its own zero-heavy-dependency module (stdlib `re` only).

Why this exists as a separate file: streaming.py's own package (models/tts_exports/__init__.py)
eagerly imports QuantizedParlerTTS, which imports torch -- so anything doing
`from models.tts_exports.streaming import clean_text` drags in a multi-GB torch import as a
side effect of Python's package init, even though clean_text itself is pure regex and never
touches torch. Confirmed directly: this is exactly what broke test_orchestrated_pipeline.py on
Jetson (ImportError: libcudss.so.0, from torch's own CUDA init) purely from importing
clean_text for its one-line markdown-stripping job. The actual TTS engine in normal operation
(TTS_ENGINE="mms_tts", the common-case fast path -- see tts_worker.py's _HybridMmsParlerEngine)
doesn't need torch at all; only the Parler-TTS fallback (for the languages MMS-TTS lacks a
checkpoint for) does, and that's constructed lazily, on demand -- so a plain markdown-cleaning
utility forcing torch to load eagerly was never necessary anywhere it's used.

streaming.py re-exports this (`from ..text_clean import clean_text`) for any existing caller
that imports it from there -- no behavior change for those, just no longer duplicated.
"""
from __future__ import annotations

import re

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
    preserved -- `chunk_text()` (models/tts_exports/streaming.py) uses them as a chunk-boundary
    signal."""
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
