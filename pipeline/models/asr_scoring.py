"""Shared, corrected scoring for the ASR comparison.

Written after an adversarial review found two scoring faults that inflated every
reported error rate, unevenly across languages.

FAULT 1 - THE DANDA WAS NEVER STRIPPED

The old normaliser was `re.sub(r"[^\\w\\sऀ-ൿ]", " ", s)`: replace anything that
is not a word character, whitespace, or inside U+0900-U+0D7F. The Devanagari
danda U+0964 and double danda U+0965 are the full stop of most Indic scripts,
and they sit INSIDE that range, so they survived as if they were letters. No ASR
emits them, so every danda in a reference counted as an error. It hit Punjabi
hardest (48 of 1047 reference words), then Odia and Bengali, and never touched
the Dravidian languages. Comparing languages under that rule was comparing
punctuation conventions as much as accuracy.

FAULT 2 - DIGITS IN THE REFERENCE

FLEURS references keep Arabic numerals ("7", "1300"). Both ASR systems correctly
speak them as words. Every such reference word is scored wrong for being right.

Converting digits to words across ten languages would need ten number grammars
and would introduce its own errors, so this is handled by exclusion instead: the
score is reported twice, over all utterances and over only those whose reference
contains no digits. The gap between the two is the size of the artefact, stated
rather than silently absorbed.

Both systems are scored through this one module so no difference between them
can come from the scoring.
"""

from __future__ import annotations

import re

# Punctuation that lives inside the Indic Unicode blocks and so escapes a
# naive "keep everything in the Indic range" rule.
INDIC_PUNCT = "।॥॰ॱ"          # danda, double danda, abbrev
ZERO_WIDTH = "​‌‍⁠﻿"     # ZWJ/ZWNJ etc.

_STRIP = re.compile(f"[{INDIC_PUNCT}{ZERO_WIDTH}]")
_PUNCT = re.compile(r"[^\w\sऀ-ൿ]")
_DIGIT = re.compile(r"[0-9٠-٩۰-۹०-९]")


def normalise(s: str) -> str:
    """Lowercase, drop punctuation including Indic punctuation, collapse space."""
    s = _STRIP.sub(" ", s or "")
    s = _PUNCT.sub(" ", s)
    return " ".join(s.lower().split())


def has_digits(s: str) -> bool:
    return bool(_DIGIT.search(s or ""))


def score(refs: list[str], hyps: list[str]) -> dict:
    """WER and CER over all pairs, and over the digit-free subset."""
    import jiwer

    n_ref = [normalise(r) for r in refs]
    n_hyp = [normalise(h) for h in hyps]

    keep = [i for i, r in enumerate(refs) if not has_digits(r)]
    out = {
        "n": len(refs),
        "wer": round(100 * jiwer.wer(n_ref, n_hyp), 1),
        "cer": round(100 * jiwer.cer(n_ref, n_hyp), 1),
        "n_digit_free": len(keep),
    }
    if keep:
        dr = [n_ref[i] for i in keep]
        dh = [n_hyp[i] for i in keep]
        out["wer_digit_free"] = round(100 * jiwer.wer(dr, dh), 1)
        out["cer_digit_free"] = round(100 * jiwer.cer(dr, dh), 1)
    return out


def error_shape(refs: list[str], hyps: list[str]) -> dict:
    """Split character errors into deletions, insertions, substitutions.

    This is the diagnostic that separates the two failure modes. A decoder that
    physically cannot write certain tokens produces DELETIONS. An acoustic model
    that mishears produces SUBSTITUTIONS. The ratio says which one is happening.
    """
    import jiwer

    o = jiwer.process_characters([normalise(r) for r in refs],
                                 [normalise(h) for h in hyps])
    total = o.deletions + o.insertions + o.substitutions
    if not total:
        return {"deletions_pct": 0.0, "insertions_pct": 0.0,
                "substitutions_pct": 0.0, "total_errors": 0}
    return {
        "deletions_pct": round(100 * o.deletions / total, 1),
        "insertions_pct": round(100 * o.insertions / total, 1),
        "substitutions_pct": round(100 * o.substitutions / total, 1),
        "total_errors": total,
    }
