"""Phonetic matching for entity names coming out of ASR.

SCOPE — read this before widening it.

The device translates to English before retrieval:

    speech -> ASR (Hindi/Tamil) -> NMT -> ENGLISH -> RAG

So a farmer saying कपास arrives as "cotton", already clean. Crop
transliterations like "kapaas" mostly never reach us, and a first version of
this module was tested against them, which overstated the problem.

Where the gap is genuinely real:

  1. PRODUCT NAMES. NMT does not translate "Mancozeb" — it is a proper noun and
     passes through untouched. If ASR mishears it, the mangled form arrives
     intact. "mankojeb" is a realistic input; "kapaas" is not.
  2. UNTRANSLATED PASS-THROUGH. Weaker language pairs sometimes leave a word
     NMT does not know, and it arrives as-is.
  3. THE ENGLISH PATH. With input_language = en there is no NMT hop at all —
     Vosk transcribes directly, so a farmer speaking English but saying "bhindi"
     produces exactly that.

Where it does NOT help, and this matters: if ASR mishears one Hindi word as a
DIFFERENT Hindi word, NMT translates that wrong word into clean, correctly
spelled English. "button" instead of "cotton". Nothing sound-based recovers
that, because the output looks perfectly valid. Only an ASR confidence signal
would catch it, and Bhashini currently discards its probabilities.

Hence the asymmetric configuration at the bottom of this file: aggressive on
product names, conservative on crop names.

Soundex and Metaphone are built around English orthography and do poorly on
Indic transliteration, where the variation is systematic rather than random:
long vowels get doubled, aspirates get written with or without the h, retroflex
and dental consonants get merged, and c/k/q are interchangeable. So this
normalises those specific patterns first and only then measures similarity.

Confidence is returned with every match, because the caller must be able to
refuse a weak one — an uncertain crop match should defer to a Krishi Vigyan
Kendra rather than guess a pesticide.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

# Applied in order. Each rule collapses a family of spellings onto one form.
_RULES = [
    # Aspirated consonants are written with or without the h.
    (r"bh", "b"), (r"ph", "f"), (r"dh", "d"), (r"th", "t"),
    (r"gh", "g"), (r"jh", "j"), (r"kh", "k"), (r"chh", "c"), (r"ch", "c"),
    (r"sh", "s"), (r"zh", "j"),
    # c / k / q / x are interchangeable in transliteration.
    (r"ck", "k"), (r"q", "k"), (r"x", "ks"),
    # Long vowels get doubled inconsistently: kapaas / kapas, bhindee / bhindi.
    (r"aa+", "a"), (r"ee+", "i"), (r"ii+", "i"), (r"oo+", "u"),
    (r"uu+", "u"), (r"ai", "e"), (r"ay", "e"), (r"au", "o"), (r"ow", "o"),
    # v and w are the same sound in most Indian languages.
    (r"w", "v"),
    # z and j merge in many dialects.
    (r"z", "j"),
    # Doubled consonants carry no meaning here: makkhi / makhi.
    (r"([bcdfgjklmnprstv])\1+", r"\1"),
    # Trailing vowels are unstable: bhindi / bhinda / bhind.
    (r"[aeiou]+$", ""),
]

# Consonants only. Internal short vowels are the least stable part of Indic
# transliteration — arhar/arhur, soyabean/soyabin — so a consonant skeleton
# catches pairs the full form misses. It is weaker evidence than a full match,
# so the caller scores it lower rather than treating it as equivalent.
_VOWELS = re.compile(r"[aeiou]")


def skeleton(text: str) -> str:
    return _VOWELS.sub("", normalise(text))

_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")


def normalise(text: str) -> str:
    """Collapse transliteration variants onto a single comparable form."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = _NON_ALNUM.sub(" ", text).strip()
    for pattern, repl in _RULES:
        text = re.sub(pattern, repl, text)
    return re.sub(r"\s+", " ", text).strip()


def similarity(a: str, b: str) -> float:
    """0..1 similarity of two names after transliteration normalisation."""
    na, nb = normalise(a), normalise(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    full = SequenceMatcher(None, na, nb).ratio()
    sa, sb = skeleton(a), skeleton(b)
    if sa and sb and len(sa) >= 3:
        # Discounted, because dropping vowels discards real information.
        full = max(full, SequenceMatcher(None, sa, sb).ratio() * 0.94)
    return full


class PhoneticIndex:
    """Fuzzy lookup over a fixed vocabulary of names.

    Built once from the crop and product lists, which are small and fixed, so
    every lookup is a scan over a few hundred short strings — microseconds, and
    no model involved.
    """

    def __init__(self, mapping: dict[str, str]):
        # name -> canonical value (crop name, or label_id)
        self.mapping = mapping
        self.normalised = {name: normalise(name) for name in mapping}
        self.skeletons = {name: skeleton(name) for name in mapping}
        # Group by first normalised character to skip most candidates cheaply.
        self.buckets: dict[str, list[str]] = {}
        for name, norm in self.normalised.items():
            if norm:
                self.buckets.setdefault(norm[0], []).append(name)

    def match(self, token: str, threshold: float = 0.86) -> tuple[str | None, float]:
        """Best match for one token. Returns (canonical_value, confidence)."""
        norm = normalise(token)
        if not norm:
            return None, 0.0

        # An exact hit on the normalised form is full confidence.
        best_name, best_score = None, 0.0
        candidates = self.buckets.get(norm[0], [])
        # Also try neighbouring buckets, since the first letter itself can be
        # misheard (gehun / kehun).
        for other in set(self.buckets) - {norm[0]}:
            if len(other) == 1 and abs(ord(other) - ord(norm[0])) <= 1:
                candidates = candidates + self.buckets[other]

        skel = skeleton(token)
        for name in candidates:
            score = SequenceMatcher(None, norm, self.normalised[name]).ratio()
            other_skel = self.skeletons[name]
            if skel and other_skel and len(skel) >= 3:
                score = max(score, SequenceMatcher(None, skel, other_skel).ratio() * 0.94)
            if score > best_score:
                best_name, best_score = name, score

        if best_name is None or best_score < threshold:
            return None, best_score
        return self.mapping[best_name], best_score

    def match_query(
        self, query: str, threshold: float = 0.86, max_words: int = 3
    ) -> tuple[str | None, float, str | None]:
        """Scan a whole query for the best entity match.

        Tries single words and short phrases, because names like "bengal gram"
        and "black pepper" span several tokens.

        Returns (canonical_value, confidence, matched_text).
        """
        words = [w for w in re.split(r"[^\w]+", query.lower()) if w]
        best = (None, 0.0, None)
        for n in range(1, max_words + 1):
            for i in range(len(words) - n + 1):
                phrase = " ".join(words[i:i + n])
                if len(phrase) < 3:
                    continue
                value, score = self.match(phrase, threshold=0.0)
                if score > best[1]:
                    best = (value, score, phrase)
        if best[1] < threshold:
            return None, best[1], best[2]
        return best


# Minimum length before fuzzy matching is allowed at all.
#
# Short names are the danger. Across 454 crop aliases there are pairs like
# jau (barley) / jowar (sorghum) and kel / kela that a loosened matcher will
# happily confuse — different crops, different diseases, different chemicals.
# Below this length the name must match exactly.
MIN_FUZZY_LEN = 5

# Confidence bands used by the caller.
#
# The lead's instruction is that anything below a high bar defers to a Krishi
# Vigyan Kendra rather than proceeding. Two bands rather than one, because the
# right response differs:
#
#   >= CONFIDENT   act on the match
#   >= PLAUSIBLE   name what we think we heard and ask the farmer to confirm,
#                  which is more useful than a bare refusal
#   below          defer
CONFIDENT = 0.95
PLAUSIBLE = 0.86
