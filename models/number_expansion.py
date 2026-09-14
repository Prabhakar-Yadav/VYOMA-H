"""expand_numbers_en() -- verbalize ASCII digits in the English agent answer BEFORE NMT.

Why this exists: MMS-TTS checkpoints ship per-language vocabularies that are missing
digit characters outright (measured directly against every checkpoint's vocab.json --
hi lacks 5/6/7/9, en lacks 7/8/9, gu lacks ALL digits, etc., and none has native-script
digits either). The VITS tokenizer silently DROPS those characters (confirmed via a
tokenize/decode round-trip: Hindi "25 kg 7 days" comes back as "2"), so any digit NMT
passes through is missing from the spoken audio -- a pesticide dose of "7 drops" is
heard as "drops". NMT itself is innocent (it preserves digits faithfully both ways).

Why expand in ENGLISH, pre-NMT, instead of per-language post-NMT tables: NMT was
probed live (EN number-words -> hi/ml/ta, 15 sentences) and translates English number
words into native words with ZERO digit leaks -- "twenty-five" -> "पँचिश"/"ഇരുപത്തിയഞ്ച്"/
"இருபத்தைந்து", "fifteen" -> "पंद्रह"/"പതിനഞ്ച്"/"பதினைந்து". So one English-only
expansion step covers all 15 TTS languages (present and future) with no language tables
to build or maintain, and units come along for free ("10 ml" -> "ten millilitres" ->
"दस मिलीलीटर" -- pure in-vocab native script, where the raw "ml" Latin letters would
also have been dropped by Indic vocabs).

Single call site: test_orchestrated_pipeline.run_full_pipeline() applies this to the
English answer right after clean_text() and before the EN->target NMT call -- both the
test script and GramSahayakUX (which calls run_full_pipeline) go through it.

Deliberate policies (all documented here so the next reader doesn't re-derive them):
- Whole words, not digit-by-digit (product decision): "25" -> "twenty-five".
- Digit runs of 7+ chars are phone numbers/IDs, not quantities ("nine billion ..." via
  num2words would be absurd) -- those go digit-by-digit ("nine eight ...").
- 2-part "A:B" is a clock time ONLY when it looks like one (hour 1-12 + exactly-two-digit
  minute, e.g. "6:30" -> "six thirty"); otherwise a ratio ("1:2" -> "one to two", and
  fertilizer grades like "19:19:19" -> "nineteen to nineteen to nineteen"). Ratios dominate
  clock times in farm answers, so ambiguity defaults to ratio.
- Dates are read as Indian-convention DD/MM/YYYY ("12/06/2026" -> "twelve June two
  thousand twenty-six"). Month names stay English words -- NMT translates them (probed).
- Numbers glued to Latin letters ("B12", "COVID-19") are left alone: splitting them
  ("Btwelve") would garble NMT worse than the current behavior. Residual risk, flagged
  by the NMT worker's digit-leak warning if such a digit survives to target text.
- URLs/emails are protected from expansion and restored verbatim afterwards.
- Bare "m" (metres) is NOT expanded -- too ambiguous ("5 M" could be million). The rest
  of the agro unit table (ml/l/kg/g/mg/cm/mm/km/ppm/percent/rupees) is unambiguous
  next to a number and is expanded, with singular/plural handled ("1 millilitre").

Stdlib + num2words only (torch-free, like text_clean.py) so this stays importable from
any venv -- including pocketinfer's, which runs run_full_pipeline in-process.
"""
from __future__ import annotations

import re

from num2words import num2words

_MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# number-adjacent unit -> (singular, plural); None plural = invariant (no plural form).
_UNITS = {
    "ml": ("millilitre", "millilitres"),
    "l": ("litre", "litres"),
    "kg": ("kilogram", "kilograms"),
    "g": ("gram", "grams"),
    "mg": ("milligram", "milligrams"),
    "cm": ("centimetre", "centimetres"),
    "mm": ("millimetre", "millimetres"),
    "km": ("kilometre", "kilometres"),
    "ppm": ("parts per million", None),
}

_DIGIT_WORDS = {
    "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
    "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine",
}

# Runs of 7+ digits are IDs/phones, not quantities -- verbalize digit by digit.
_LONG_RUN_RE = re.compile(r"\d{7,}")
_URL_RE = re.compile(r"https?://\S+|www\.\S+|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

_NUM = r"\d+(?:\.\d+)?"
# Left boundary: not glued to a letter (protects B12/COVID-19/model names).
_LB = r"(?<![A-Za-z0-9])"


def _say_cardinal(token: str) -> str:
    """Whole-words verbalization of one numeric token (commas pre-stripped by caller)."""
    token = token.replace(",", "")
    if "." in token:
        try:
            return num2words(float(token)).replace(",", "")
        except Exception:
            return token
    digits = token
    if len(digits) >= 7:
        return " ".join(_DIGIT_WORDS[d] for d in digits)
    try:
        return num2words(int(digits)).replace(",", "")
    except Exception:
        return token


def _say_unit(value: str, unit: str) -> str:
    singular, plural = _UNITS[unit.lower()]
    try:
        is_one = float(value.replace(",", "")) == 1.0
    except ValueError:
        is_one = False
    word = singular if (is_one or plural is None) else plural
    return f"{_say_cardinal(value)} {word}"


def expand_numbers_en(text: str) -> str:
    """Verbalize every speakable ASCII number in English `text`; URLs/emails untouched."""
    if not text or not re.search(r"\d", text):
        return text

    # URLs/emails are expanded NEVER -- split the text around them (rather than sentinel
    # tokens, which a later number pass could itself match and corrupt) and only expand
    # the plain-text segments.
    segments: list[tuple[str, bool]] = []
    last = 0
    for m in _URL_RE.finditer(text):
        if m.start() > last:
            segments.append((text[last:m.start()], True))
        segments.append((m.group(0), False))
        last = m.end()
    if last < len(text):
        segments.append((text[last:], True))
    return _join_segments(_expand_segment(seg) if expand else seg for seg, expand in segments)


def _join_segments(parts) -> str:
    text = "".join(parts)
    return re.sub(r"[ \t]+", " ", text).strip()


def _expand_segment(text: str) -> str:

    # 1. Thousand separators: "2,500" -> "2500" (num2words chokes on commas otherwise).
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)

    # 2. Dates DD/MM/YYYY (Indian convention) -> "twelve June two thousand twenty-six".
    def _date(m: re.Match) -> str:
        day, mon, year = int(m.group(1)), int(m.group(2)), m.group(3)
        if not (1 <= day <= 31 and 1 <= mon <= 12):
            return m.group(0)
        return f"{_say_cardinal(str(day))} {_MONTHS[mon - 1]} {_say_cardinal(year)}"

    text = re.sub(_LB + r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", _date, text)

    # 3. Ranges "10-15" / "10-15 ml" -> "ten to fifteen" (/ "... millilitres").
    # The optional trailing unit matters: without it, "10-15 ml" would expand the numbers
    # first and strand a bare Latin "ml" that Indic TTS vocabs drop silently.
    _unit_alt = "|".join(sorted(_UNITS, key=len, reverse=True))

    def _range(m: re.Match) -> str:
        words = f"{_say_cardinal(m.group(1))} to {_say_cardinal(m.group(2))}"
        if m.group(3):
            singular, plural = _UNITS[m.group(3).lower()]
            words += f" {plural or singular}"
        return words

    text = re.sub(
        _LB + rf"({_NUM})\s*[-–—]\s*({_NUM})(?:\s*({_unit_alt}))?\b",
        _range,
        text,
        flags=re.IGNORECASE,
    )

    # 4. Ratios "1:2(:19)" -> "one to two ..."; clock times "6:30" -> "six thirty".
    def _ratio_or_time(m: re.Match) -> str:
        parts = [p for p in re.split(r"\s*:\s*", m.group(0)) if p != ""]
        if (
            len(parts) == 2
            and re.fullmatch(r"\d{1,2}", parts[0])
            and re.fullmatch(r"\d{2}", parts[1])
            and 1 <= int(parts[0]) <= 12
        ):
            minute = int(parts[1])
            if minute == 0:
                return f"{_say_cardinal(parts[0])} o'clock"
            mm_word = (
                f"oh {_say_cardinal(str(minute))}" if minute < 10
                else _say_cardinal(str(minute))
            )
            return f"{_say_cardinal(parts[0])} {mm_word}"
        return " to ".join(_say_cardinal(p) for p in parts)

    text = re.sub(_LB + rf"{_NUM}(?:\s*:\s*{_NUM})+" + r"(?![A-Za-z0-9])", _ratio_or_time, text)

    # 5. Percent "2%" / "2 %" -> "two percent".
    text = re.sub(
        _LB + rf"({_NUM})\s*%",
        lambda m: f"{_say_cardinal(m.group(1))} percent",
        text,
    )

    # 6. Rupees "Rs. 2500" / "Rs 2500" / "₹2500" -> "rupees two thousand five hundred".
    text = re.sub(
        r"(?:Rs\.?|₹)\s*" + _LB + rf"({_NUM})",
        lambda m: f"rupees {_say_cardinal(m.group(1))}",
        text,
    )

    # 7. Units "10ml" / "10 ml" / "25 kg" -> "ten millilitres" / "twenty-five kilograms".
    text = re.sub(
        _LB + rf"({_NUM})\s*({_unit_alt})\b",
        lambda m: _say_unit(m.group(1), m.group(2)),
        text,
        flags=re.IGNORECASE,
    )

    # 8. Ordinals "1st" / "22nd" -> "first" / "twenty-second".
    def _ordinal(m: re.Match) -> str:
        try:
            return num2words(int(m.group(1)), to="ordinal")
        except Exception:
            return m.group(0)

    text = re.sub(_LB + r"(\d+)(st|nd|rd|th)\b", _ordinal, text, flags=re.IGNORECASE)

    # 9. Any remaining plain number -> whole words (or digit-by-digit for 7+ runs).
    # The extra (?<![A-Za-z]-) guard keeps letter-hyphenated codes intact ("COVID-19":
    # the "19" is preceded by "D-", so it is skipped -- splitting it would garble NMT
    # worse than leaving it; the NMT worker's digit-leak warning flags it if it survives).
    text = re.sub(
        _LB + r"(?<![A-Za-z]-)" + rf"({_NUM})(?![A-Za-z0-9])",
        lambda m: _say_cardinal(m.group(1)),
        text,
    )

    return text
