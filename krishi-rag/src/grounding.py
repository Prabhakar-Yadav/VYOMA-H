"""Grounded answer assembly and the abstention gate.

This module is the safety boundary of the whole system. Everything upstream is a
*claim*; nothing downstream may speak a dose that did not come from a Treatment
concept in the bundle.

The contract, in one sentence: **no label_id, no prescription.**

`build_response` cannot fabricate a dose because it never generates text — it
copies fields out of a retrieved concept's frontmatter. A language model is used
only to translate the assembled text into the farmer's dialect, downstream of
this module, where it has no opportunity to invent a number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from okf import Concept
from retrieval import Hit, HybridRetriever


class Outcome(str, Enum):
    GROUNDED = "grounded"           # confident diagnosis + retrieved label record
    ABSTAINED_LOW_CONF = "abstained_low_confidence"
    ABSTAINED_NO_LABEL = "abstained_no_treatment_record"
    ABSTAINED_AMBIGUOUS = "abstained_ambiguous"
    ABSTAINED_OUT_OF_COVERAGE = "abstained_crop_not_covered"
    ABSTAINED_TOO_VAGUE = "abstained_insufficient_detail"
    ABSTAINED_NO_CROP = "abstained_crop_not_identified"
    OUT_OF_SCOPE = "out_of_scope_topic"
    GUIDELINE = "guideline_answer"
    EMERGENCY = "emergency_first_response"
    HEALTHY = "healthy_no_disease"


# Information-sufficiency gate.
#
# A two-word query like "white spots" carries no crop, no plant part, and no
# distinguishing detail — yet it still scores 0.634 against the corpus, only
# 0.01 below the weakest genuine query. That gap is far too narrow to separate
# by threshold without overfitting, and the score is not the real problem: the
# query simply does not contain enough information to diagnose anything.
#
# So we check for sufficient detail before ranking, the same way the coverage
# gate checks the crop. Asking the farmer one clarifying question is strictly
# better than guessing a pesticide from two words.
MIN_CONTENT_WORDS = 3

# Thresholds operate on the ABSOLUTE relevance signal from retrieval
# (0.65 * cosine + 0.35 * normalised BM25), never on the fused RRF score. RRF is
# purely ordinal: its top hit scores the same for a leaf photo and for the sky,
# so it cannot express "nothing in the corpus matches this".
#
# Set by inspecting score distributions on the seed corpus. MUST be re-tuned as
# the corpus grows — a threshold fitted to 6 conditions will not hold at 60.
# Derived on ENGLISH queries only, because English is the only thing retrieval
# ever receives — the reference app runs NMT to English before the reasoning
# step (see NOT_ON_INPUT_PATH in evalset.py).
#
# After the sufficiency, coverage and healthy gates absorb what similarity
# cannot separate:
#   highest remaining distractor  0.500  ("dry brown soil with small stones")
#   lowest true positive          0.644  ("black sooty powder on cotton leaves")
#
# An earlier version scored Devanagari queries too. Those ran as low as 0.216
# and held this threshold down to accommodate input that cannot occur, which is
# precisely the slack that let "white spots" (0.634) through as a confident
# diagnosis. Scoring an impossible input path made the real path less safe.
#
# Still fitted to a small sample. Re-derive as the corpus grows, and again once
# real VLM descriptions replace hand-written queries.
# Re-derived at 64 concepts / 329 chunks (was 0.58 at 16 concepts).
#
# What changed: the crop-identification gate above now removes every non-crop
# photograph and every out-of-coverage crop *before* ranking. Measured on the
# 93-case suite, **no distractor reaches this threshold at all** — soil, sky,
# tractor and wall are all caught structurally. The threshold's job is therefore
# no longer to separate crops from non-crops; it only has to admit genuine
# diagnoses on a corpus where 54 conditions compete for every query.
#
# Correct diagnoses now bottom out around 0.581, because more competing
# conditions split the similarity mass. 0.52 sits below that with margin, and
# after UNVERIFIED_PENALTY the effective bar is 0.52 x 1.08 = 0.562.
#
# Re-derived again at 132 concepts / 824 chunks after the entomology, pathology,
# guideline and CIB&RC corpora landed (was 0.52 at 339 chunks, 0.58 at 104).
#
# The pattern is now clear and worth stating: **every time the corpus grows, this
# number must come down.** More concepts compete for the same query, so the
# similarity mass splits further and even a perfectly correct match scores lower.
# Measured lowest true positive at 824 chunks: 0.483.
#
# This is only safe because the structural gates — sufficiency, coverage, crop
# identification, scope — remove every distractor *before* ranking. Measured on
# the 93-case suite, no distractor reaches this threshold at all. If those gates
# were ever weakened, this number would have to rise again.
#
# Re-derive whenever the corpus grows substantially. `evalset100.py` prints the
# separation it was fitted to.
MIN_RELEVANCE = 0.44
AMBIGUITY_MARGIN = 0.035    # top-2 closer than this => genuinely confusable

# Asymmetric margin for the disease-vs-deficiency case only. See the gate in
# build_response for why it is wider than AMBIGUITY_MARGIN and one-directional.
DEFICIENCY_CONFUSION_MARGIN = 0.11

# --- symptom evidence, derived from the corpus rather than written by hand ---
#
# Two of the 40 real recordings still ended in a prescription after the
# deficiency gate went in, and both failed the same way: a fertiliser question
# lost the one word that made it a fertiliser question. "आलू में जिंक देना
# चाहिए या नहीं" (should zinc be given to potato) reached the RAG as "whether
# or not jam should be added to potatoes"; "कौन-कौन खाद देना चाहिए" (which
# fertilisers should I give) arrived as "what food is a potato peel". What was
# left was a crop name and noise, and a crop name alone is enough to rank that
# crop's commonest disease first and hand over a dose.
#
# So a chemical is not handed over unless the farmer actually described
# something. The test is whether the query uses words the corpus itself uses to
# describe symptoms.
#
# A hand-written list was tried first and thrown away: it broke 12 correct
# cases, because no list written by hand contains "winding galleries", "bushy
# broom" or "crackle when pressed". Building the vocabulary from the bundle's
# own symptom sections fixes that - it already contains every word the corpus
# uses, and it grows whenever a concept is added.
MIN_SYMPTOM_EVIDENCE = 2

_SYMPTOM_SECTION_KEYS = ("what you see", "symptom", "signs", "how it looks",
                         "what it looks like", "damage", "appearance")


# Advice that needs no pesticide label.
#
# 31 of the 36 conditions that carry no verified treatment record already have
# a "Non-chemical measures" section written - named resistant varieties,
# roguing infected plants, sticky traps, weed hosts to clear, and in places a
# warning that a particular spray makes things worse. All of it is safe to say
# and none of it is a dose.
#
# The device was throwing every word of it away and saying "ask your Krishi
# Vigyan Kendra" instead. Measured over 40 real recordings, 16 of 40 answers
# were that bare referral, and it was the single commonest thing the device
# said. A farmer who is told to pull out infected plants and hang yellow traps
# can act today; a farmer told to travel to a KVK usually cannot.
#
# The safety contract is untouched. This path still returns
# ABSTAINED_NO_LABEL, still carries no label_id, and still names no chemical -
# it only speaks guidance the corpus already holds.
_ADVICE_HEADINGS = ("non-chemical", "cultural", "without a chemical")

# Bullets are trimmed to keep the spoken reply short. Three is about 20 seconds
# of speech, which is already long for audio with no screen to refer back to.
MAX_ADVICE_POINTS = 3


def non_chemical_advice(concept: Concept) -> list[str]:
    """Actionable points from a concept's non-chemical section, if it has one."""
    for sec in concept.sections:
        if not any(k in (sec.heading or "").lower() for k in _ADVICE_HEADINGS):
            continue
        points = []
        for line in (sec.text or "").splitlines():
            line = line.strip()
            if not line.startswith(("-", "*")):
                continue
            line = line.lstrip("-* ").strip()
            # Markdown emphasis and italics are for a screen, not a speaker.
            line = re.sub(r"[*_`]+", "", line)
            line = re.sub(r"\s+", " ", line).strip(" .")
            if line:
                points.append(line)
        if points:
            return points[:MAX_ADVICE_POINTS]
    return []


def build_symptom_vocab(concepts) -> frozenset[str]:
    """Words the corpus uses to describe what a sick plant looks like.

    Terms confined to a single concept are dropped - those are usually names
    rather than descriptions. Crop names are dropped too, since naming the crop
    is exactly what these queries already do.
    """
    counts: dict[str, int] = {}
    crops: set[str] = set()
    for c in concepts:
        for cr in (c.frontmatter.get("crops") or []):
            crops.update(re.findall(r"[a-z]+", str(cr).lower()))
        for sec in c.sections:
            head = (sec.heading or "").lower()
            if not any(k in head for k in _SYMPTOM_SECTION_KEYS):
                continue
            for w in re.findall(r"[a-z]+", sec.text.lower()):
                if len(w) > 2 and w not in _STOPWORDS:
                    counts[w] = counts.get(w, 0) + 1
    return frozenset({w for w, n in counts.items() if n >= 2} - crops)


def symptom_evidence(query: str, vocab: frozenset[str]) -> int:
    return len(set(re.findall(r"[a-z]+", query.lower())) & vocab)


_VOCAB_CACHE: dict[int, frozenset[str]] = {}


def _vocab_for(concepts_by_id: dict) -> frozenset[str]:
    """Built once per corpus size. Rebuilding per query costs ~40ms."""
    key = len(concepts_by_id)
    v = _VOCAB_CACHE.get(key)
    if v is None:
        v = build_symptom_vocab(concepts_by_id.values())
        _VOCAB_CACHE[key] = v
    return v


def looks_english(query: str) -> bool:
    """Only English queries are gated on the English symptom vocabulary.

    On the device the RAG only ever sees English - speech is translated before
    retrieval. But the eval suites deliberately include Devanagari and
    Latin-script Hindi ("peela ratua gehun mein") to test robustness, and those
    would score zero against an English vocabulary for reasons that have
    nothing to do with whether a symptom was described.
    """
    letters = re.findall(r"[A-Za-zऀ-ॿ]", query)
    if not letters:
        return False
    ascii_n = sum(1 for ch in letters if ch.isascii())
    return ascii_n / len(letters) > 0.9
UNVERIFIED_PENALTY = 1.08   # unverified concepts must clear a higher bar


@dataclass
class Response:
    outcome: Outcome
    condition: str | None = None
    condition_id: str | None = None
    confidence: float = 0.0
    trust_tier: str | None = None
    label_ids: list[str] = field(default_factory=list)
    treatments: list[dict] = field(default_factory=list)
    spoken_text: str = ""
    runner_up: str | None = None
    debug: dict = field(default_factory=dict)

    @property
    def is_safe_to_speak(self) -> bool:
        """A prescription may be spoken only if it carries at least one label_id."""
        return self.outcome == Outcome.GROUNDED and bool(self.label_ids)


_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "am",
    "my", "me", "i", "we", "our", "your", "it", "its", "this", "that",
    "these", "those", "there", "here", "some", "any", "and", "or", "but",
    "in", "on", "at", "of", "to", "for", "with", "from", "by", "as",
    "has", "have", "had", "do", "does", "did", "can", "will", "would",
    "should", "not", "no", "very", "so", "if", "what", "which", "how",
    "photo", "photograph", "picture", "image", "close", "up",
}


def content_words(query: str) -> list[str]:
    """Tokens that actually carry diagnostic information."""
    tokens = [t.strip(".,!?;:'\"()").lower() for t in query.split()]
    return [t for t in tokens if len(t) > 2 and t not in _STOPWORDS]


def _fmt_treatment(concept: Concept) -> dict:
    """Copy the prescription fields verbatim out of frontmatter. No generation."""
    fm = concept.frontmatter
    return {
        "label_id": fm.get("label_id"),
        "title": concept.title,
        "molecule": fm.get("molecule"),
        "formulation": fm.get("formulation"),
        "trade_names": fm.get("common_trade_names", []),
        "dose_per_acre": fm.get("dose_per_acre"),
        "dilution_per_litre": fm.get("dilution_per_litre"),
        "spray_volume_per_acre": fm.get("spray_volume_per_acre"),
        "phi_days": fm.get("phi_days"),
        # Not every use is a foliar spray. A seed dressing and a soil drench
        # carry different numbers and different instructions, and reading a
        # seed rate as a spray rate is a real-world dosing error.
        "registered_crop": fm.get("registered_crop"),
        "application_method": fm.get("application_method"),
        "dose_per_kg_seed": fm.get("dose_per_kg_seed"),
        "slurry_water_per_kg_seed": fm.get("slurry_water_per_kg_seed"),
        "reentry_hours": fm.get("reentry_hours"),
        "toxicity_triangle": fm.get("toxicity_triangle"),
        "max_applications": fm.get("max_applications_per_season"),
        "trust_tier": concept.trust_tier,
    }


def _speak(condition: str, treatments: list[dict]) -> str:
    """Assemble the spoken answer purely by template substitution.

    Written in short declarative sentences because this text is about to be
    machine-translated into a dialect and then synthesised as speech. Long
    subordinate clauses survive neither hop well.
    """
    lines = [f"Your crop has {condition}."]

    for t in treatments:
        name = t["title"]
        trade = t.get("trade_names") or []
        if trade:
            name += f" (sold as {trade[0]})"
        lines.append(f"Use {name}.")

        # Not every registered use is a foliar spray, and the difference is not
        # cosmetic. Wheat loose smut lives inside the seed embryo and CANNOT be
        # sprayed at all - it is stopped by dressing the seed before sowing or
        # not at all. Feeding a seed treatment through the spray template
        # produced "Do not harvest for not applicable (applied at sowing) days
        # after spraying", which is both nonsense and an instruction to do the
        # one thing that does not work.
        method = (t.get("application_method") or "spray").lower()

        if "seed" in method:
            if t.get("dose_per_kg_seed"):
                lines.append(
                    f"This is a seed treatment, not a spray. This disease "
                    f"cannot be sprayed. Mix {t['dose_per_kg_seed']} for every "
                    "kilo of seed before you sow."
                )
            if t.get("slurry_water_per_kg_seed"):
                lines.append(
                    f"Use {t['slurry_water_per_kg_seed']} of water per kilo of "
                    "seed to make the slurry."
                )
            lines.append("Treat the seed in shade, dry it in shade, and sow it "
                         "within a few days.")
            lines.append("Never feed treated seed to people or to animals.")
        else:
            if t.get("dilution_per_litre"):
                lines.append(f"Mix {t['dilution_per_litre']} in one litre of water.")
            if t.get("dose_per_acre") and t.get("spray_volume_per_acre"):
                lines.append(
                    f"For one acre, use {t['dose_per_acre']} "
                    f"in {t['spray_volume_per_acre']} of water."
                )
            if "drench" in method:
                lines.append("Pour this onto the soil around the plants. "
                             "Do not spray it on the leaves.")
            # A PHI is only meaningful when something was applied to a standing
            # crop. Seed treatment happens before the crop exists.
            phi = t.get("phi_days")
            if phi is not None and str(phi).strip().replace(".", "").isdigit():
                lines.append(f"Do not harvest for {phi} days after applying.")
        triangle = t.get("toxicity_triangle")
        if triangle == "verify_on_container":
            lines.append(
                "Check the coloured triangle on the container before you use it. "
                "Cover your mouth and hands. Do not spray against the wind."
            )
        elif triangle:
            lines.append(
                f"The label has a {triangle} triangle. "
                "Cover your mouth and hands. Do not spray against the wind."
            )
        break  # speak one primary recommendation; alternatives shown on screen

    return " ".join(lines)


# Emergency detection.
#
# Split into two lists after a real false positive: "plant collapsed while leaves
# are still green" and "clump collapsed flat" were both diverted to poisoning
# first aid, because "collapsed" was treated as unambiguous. Plants collapse too,
# and a diagnosis query reaching a first-aid answer is a failure in the direction
# that matters.
#
# UNAMBIGUOUS phrases only apply to people. AMBIGUOUS phrases fire only when a
# person is also named, so a wilting crop stays a crop.
_EMERGENCY_UNAMBIGUOUS = (
    "drank pesticide", "swallowed", "swallow pesticide", "ate pesticide",
    "drank the spray", "poisoning", "poisoned", "unconscious", "fainted",
    "antidote", "vomiting", "convulsion", "fits", "seizure",
    "foaming at the mouth", "pinpoint pupils",
)

_EMERGENCY_AMBIGUOUS = (
    "collapsed", "not breathing", "difficulty breathing", "breathless",
    "dizzy", "burning eyes", "in the eye", "on the skin", "hospital",
    "emergency", "sick after spraying", "ill after spraying",
)

# Matched on word boundaries, not as substrings. "he" inside "the" fired the
# emergency path for "the clump collapsed flat and the rhizome is pulpy" — a
# ginger rot query answered with poisoning first aid.
_PERSON_WORDS = (
    "he", "she", "him", "her", "someone", "somebody", "person", "people",
    "husband", "wife", "son", "daughter", "child", "boy", "girl", "worker",
    "labour", "labourer", "father", "mother", "brother", "sister",
    "my hand", "my eye", "my skin", "my face", "i feel", "i am feeling",
    "sprayman", "operator",
)


def _is_emergency(query: str) -> bool:
    """Life-threatening phrasing that must bypass ranking entirely.

    Ambiguous words need a person in the sentence, because a plant collapsing and
    a person collapsing are different emergencies and only one of them is this.
    """
    lowered = " " + query.lower() + " "
    if any(p in lowered for p in _EMERGENCY_UNAMBIGUOUS):
        return True
    if any(p in lowered for p in _EMERGENCY_AMBIGUOUS):
        import re as _re
        return any(
            _re.search(r"" + _re.escape(w) + r"", lowered) for w in _PERSON_WORDS
        )
    return False


def _summarise(text: str, max_chars: int = 420) -> str:
    """Trim a retrieved passage into something speakable.

    Guideline passages are written for a device to read aloud, so they are
    already short sentences. This drops markdown furniture and caps the length
    so the TTS hop stays quick.
    """
    import re as _re
    clean = _re.sub(r"[*_`#>|]", "", text)
    clean = _re.sub(r"^\s*[-\d]+[.)]?\s*", "", clean, flags=_re.M)
    clean = " ".join(clean.split())
    if len(clean) <= max_chars:
        return clean
    cut = clean[:max_chars]
    stop = cut.rfind(". ")
    return (cut[: stop + 1] if stop > 120 else cut).strip()


ABSTENTION_TEXT = (
    "I am not sure what this is. Please show this plant to your nearest "
    "Krishi Vigyan Kendra. I have saved this photo."
)

HEALTHY_TEXT = (
    "This plant looks healthy. I do not see any disease or pest damage. "
    "Show it to me again if you notice any change."
)


class CoverageGate:
    """Structural crop boundary, loaded from /crops/coverage.md.

    Kept separate from the score threshold because it answers a different
    question. The threshold asks "does anything in the corpus resemble this?";
    the gate asks "is this crop one we are allowed to speak about at all?".
    A banana query out-scores a correct Hindi query on similarity, so only the
    second question has a safe answer.
    """

    def __init__(self, concepts_by_id: dict[str, Concept]):
        concept = concepts_by_id.get("/crops/coverage")
        covered = (concept.frontmatter.get("covered_crops") or {}) if concept else {}
        uncovered = (concept.frontmatter.get("uncovered_crops") or []) if concept else []

        self.canonical: dict[str, str] = {}
        for canon, aliases in covered.items():
            for alias in aliases or []:
                self.canonical[str(alias).strip().lower()] = canon

        self.blocked: dict[str, str] = {}
        for group in uncovered:
            names = group if isinstance(group, list) else [group]
            head = str(names[0]).strip().lower()
            for name in names:
                self.blocked[str(name).strip().lower()] = head

    def resolve(self, crop: str | None) -> tuple[str | None, str | None]:
        """Map a crop label to its canonical name. Returns (canonical, blocked_as)."""
        if not crop:
            return None, None
        key = crop.strip().lower()
        if key in self.canonical:
            return self.canonical[key], None
        if key in self.blocked:
            return None, self.blocked[key]
        return None, key  # named but unknown — treat as out of coverage

    def scan_query(self, query: str) -> str | None:
        """Backstop for when the VLM reports no crop: find a blocked crop term."""
        tokens = {t.strip(".,!?;:") for t in query.lower().split()}
        for name, head in self.blocked.items():
            if " " in name:
                if name in query.lower():
                    return head
            elif name in tokens:
                return head
        return None

    def scan_covered(self, query: str) -> str | None:
        """Find a COVERED crop named in the query text.

        Used when the vision model reports no crop but the farmer's own words
        name one — "my cotton is yellowing" carries the crop even if the photo
        was too close to show the whole plant.
        """
        lowered = query.lower()
        tokens = {t.strip(".,!?;:") for t in lowered.split()}

        # Match singulars too. NMT hands us plurals constantly - "blight in
        # potatoes", "whitefly in tomatoes" - and an exact token match missed
        # every one of them. The crop filter was then never applied, and on one
        # real recording an ONION disease outranked the potato disease for a
        # question that said "potatoes". Six farmers asked the same potato
        # blight question in the test set and got five different answers,
        # partly because of this.
        #
        # Kept deliberately narrow. Crop names are short and there are 454 of
        # them, so aggressive stemming would collide genuinely different crops
        # (jau/jowar, kel/kela) that carry different diseases and different
        # chemicals. These three rules only ever REMOVE a plural ending; they
        # never transform one word into another root.
        for t in list(tokens):
            if len(t) > 4 and t.endswith("ies"):
                tokens.add(t[:-3] + "y")      # chillies -> chilly
            elif len(t) > 3 and t.endswith("es"):
                tokens.add(t[:-2])            # potatoes -> potato
                tokens.add(t[:-1])            # limes -> lime
            elif len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
                tokens.add(t[:-1])            # beans -> bean

        for name, canon in self.canonical.items():
            if " " in name:
                if name in lowered:
                    return canon
            elif name in tokens:
                return canon
        return None


def lookup_treatment(label_id, concepts_by_id) -> "Response":
    """Return one treatment record by its label_id. No search involved.

    This is the pesticide path, and it is deliberately a lookup rather than a
    retrieval. Similarity search over pesticide records can return a plausible
    product registered for a different crop — and crop registration on a CIB&RC
    label is legally binding, not advisory. An exact key cannot make that
    mistake.
    """
    for concept in concepts_by_id.values():
        if concept.label_id != label_id:
            continue
        t = _fmt_treatment(concept)
        crop = concept.frontmatter.get("registered_crop", "this crop")
        targets = concept.frontmatter.get("registered_targets") or []
        lines = [f"{concept.title}."]
        lines.append(
            "Registered for {} against {}.".format(
                crop, ", ".join(str(x) for x in targets) if targets else "the listed pests"
            )
        )
        if t.get("dilution_per_litre"):
            lines.append(f"Mix {t['dilution_per_litre']} in one litre of water.")
        if t.get("dose_per_acre"):
            lines.append(f"For one acre, use {t['dose_per_acre']}.")
        if t.get("phi_days") is not None:
            lines.append(f"Do not harvest for {t['phi_days']} days after spraying.")
        else:
            lines.append(
                "The waiting period before harvest is not printed in the "
                "government table. Check the container and ask your Krishi "
                "Vigyan Kendra before you pick the crop."
            )
        lines.append(
            "Check the coloured triangle on the container. Cover your mouth "
            "and hands. Do not spray against the wind."
        )
        return Response(
            outcome=Outcome.GROUNDED,
            condition=concept.title,
            condition_id=concept.concept_id,
            confidence=1.0,
            trust_tier=concept.trust_tier,
            label_ids=[label_id],
            treatments=[t],
            spoken_text=" ".join(lines),
            debug={"lookup": label_id, "registered_crop": crop},
        )

    return Response(
        outcome=Outcome.ABSTAINED_NO_LABEL,
        spoken_text=(
            "I do not have a verified record for that product. Please ask your "
            "Krishi Vigyan Kendra."
        ),
        debug={"lookup_failed": label_id},
    )


_CROPMAP_CACHE: dict[int, dict[str, str]] = {}


def _crop_aliases(concepts_by_id: dict) -> dict[str, str]:
    """Every surface form a farmer might use -> canonical crop name."""
    key = len(concepts_by_id)
    m = _CROPMAP_CACHE.get(key)
    if m is None:
        m = {}
        cov = concepts_by_id.get("/crops/coverage")
        covered = (cov.frontmatter.get("covered_crops") or {}) if cov else {}
        for canon, aliases in covered.items():
            m[str(canon).strip().lower()] = canon
            for a in (aliases or []):
                m[str(a).strip().lower()] = canon
        _CROPMAP_CACHE[key] = m
    return m


def registration_holds(query: str, treatments: list[dict],
                       concepts_by_id: dict, crop: str | None) -> str | None:
    """Return the offending crop name if a label is being used off-registration.

    Crop registration on a CIB&RC label is legally binding, not advisory. A
    product registered on wheat is not registered on radish, and offering it
    anyway is both illegal and unsafe.

    This became a real failure, not a theoretical one. A farmer asked, with
    PERFECT speech recognition, "how long can radish seed last at home without
    medication". Radish is not a crop we cover, so no crop filter applied, and
    the wheat loose smut seed dressing matched on the words "seed" and
    "medication" alone. The device offered a wheat product for radish.

    So: the crop on the label has to actually appear in what the farmer said.
    If it does not, we cannot confirm the registration applies and we do not
    prescribe. Silence is recoverable; a wrong-crop chemical is not.
    """
    aliases = _crop_aliases(concepts_by_id)
    lowered = query.lower()
    words = set(re.findall(r"[a-z]+", lowered))

    for t in treatments:
        reg = (t.get("registered_crop") or "").strip().lower()
        if not reg:
            continue                      # nothing to check against
        if crop and crop.strip().lower() == reg:
            continue                      # router already identified this crop
        # Accept any alias of the registered crop appearing in the query.
        forms = {a for a, canon in aliases.items() if canon.strip().lower() == reg}
        forms.add(reg)
        if any((f in words) or (" " in f and f in lowered) for f in forms):
            continue
        return reg
    return None


def _no_label_text(concept: Concept) -> str:
    """What to say when we know the condition but hold no verified dose."""
    advice = non_chemical_advice(concept)
    if not advice:
        return (f"This looks like {concept.title}. "
                "I do not have a verified treatment for it. "
                "Please ask your Krishi Vigyan Kendra before spraying anything.")
    body = " ".join(f"{i}. {a}." for i, a in enumerate(advice, 1))
    return (f"This looks like {concept.title}. I do not have a verified "
            f"medicine to give you for it, so please do not spray anything on "
            f"guesswork. There are things you can do today. {body} "
            "For a spray, ask your Krishi Vigyan Kendra.")


def build_response(
    query: str,
    retriever: HybridRetriever,
    concepts_by_id: dict[str, Concept],
    crop: str | None = None,
    top_k: int = 8,
    require_crop: bool = True,
    boost_source: str | None = None,
) -> Response:
    """Run retrieval and decide: prescribe, or abstain.

    `require_crop=False` turns off the crop-identification gate for questions
    that legitimately have no crop — scheme eligibility, pesticide poisoning
    first response, how to read a Soil Health Card. Those gates were written when
    every query was a crop diagnosis; applying them to a guideline lookup blocks
    the answer. The router decides which mode applies.
    """

    # Sufficiency gate runs first. If the query carries too little information to
    # diagnose anything, ask for more rather than ranking on noise.
    words = content_words(query)
    if require_crop and len(words) < MIN_CONTENT_WORDS:
        return Response(
            outcome=Outcome.ABSTAINED_TOO_VAGUE,
            spoken_text=(
                "I need to know a little more. Which crop is this, "
                "and which part of the plant is affected?"
            ),
            debug={"reason": "insufficient detail", "content_words": words},
        )

    # Emergency short-circuit.
    #
    # Poisoning is the one question where ranking is not good enough. Asked
    # "someone drank pesticide what do I do", retrieval returned the
    # after-spraying hygiene passage — sensible text, lethal timing. Anything
    # matching an emergency phrase goes straight to the first-response concept.
    if _is_emergency(query):
        concept = concepts_by_id.get("/guidelines/pesticide-poisoning")
        if concept is not None:
            section = concept.section("Immediate first response") or concept.section(
                "First response"
            )
            body = section.text if section else concept.body
            return Response(
                outcome=Outcome.EMERGENCY,
                condition=concept.title,
                condition_id=concept.concept_id,
                confidence=1.0,
                spoken_text=_summarise(body, max_chars=600),
                debug={"reason": "emergency phrase matched"},
            )

    # Coverage gate runs before ranking. An out-of-coverage crop is refused
    # regardless of how well its description happens to match the corpus.
    gate = CoverageGate(concepts_by_id)
    canonical_crop, blocked = gate.resolve(crop)
    if blocked is None and crop is None:
        blocked = gate.scan_query(query)

    if blocked:
        return Response(
            outcome=Outcome.ABSTAINED_OUT_OF_COVERAGE,
            spoken_text=(
                f"I do not know about {blocked} yet. "
                "Please show this plant to your nearest Krishi Vigyan Kendra."
            ),
            debug={"reason": "crop outside coverage boundary", "crop": blocked},
        )

    # Crop-identification gate.
    #
    # At 6 conditions, retrieval could tell diseases apart from a symptom
    # description alone. At 54 it cannot, and that is correct rather than broken:
    # "brown spots with rings on the lower leaves" genuinely describes early
    # blight on tomato AND on potato — the same pathogen, Alternaria solani.
    # Asked without a crop, the honest answer is that the question is ambiguous.
    #
    # Measured: the same query scores 0.555 with no crop (returning the wrong
    # crop's disease) and 0.629 with crop=tomato (returning the right one).
    #
    # This also removes non-crop photographs structurally. Soil, sky, a tractor
    # and a brick wall have no crop, and "dry brown soil with small stones"
    # scores 0.625 against a 54-condition corpus — high enough that no threshold
    # separates it safely. The VLM always reports a crop in production, so its
    # absence is itself the signal.
    if require_crop and canonical_crop is None:
        named = gate.scan_covered(query)
        if named is None:
            return Response(
                outcome=Outcome.ABSTAINED_NO_CROP,
                spoken_text=(
                    "I cannot tell which crop this is. "
                    "Please tell me the crop, or take the photo closer to the plant."
                ),
                debug={"reason": "no crop identified and none named in query"},
            )
        canonical_crop = named

    # Default the boost in diagnosis mode.
    #
    # The entomology and pathology concepts carry no `crop` field, so they pass
    # the crop filter for every crop, and they are long documents that match a
    # great many symptom words. Once they were added, a tomato early blight query
    # started returning Alternaria pathology and yellow-mite entomology chunks
    # ahead of the tomato disease concept — correct background reading, wrong
    # answer to "what is wrong with my plant".
    #
    # Boosting `diseases` in diagnosis mode restores the ordering. It is still a
    # boost and not a filter: the biology concepts stay reachable and will win
    # when the question is actually about biology.
    if boost_source is None and require_crop:
        boost_source = ["diseases", "deficiencies"]

    hits = retriever.search(query, top_k=top_k, crop=canonical_crop,
                            boost_source=boost_source)
    if not hits:
        return Response(
            outcome=Outcome.ABSTAINED_LOW_CONF,
            spoken_text=ABSTENTION_TEXT,
            debug={"reason": "no candidates after filtering", "crop_filter": crop},
        )

    # Aggregate chunk hits up to their parent concept, keeping only diagnosable
    # conditions. Treatment chunks are reached through the condition, never
    # ranked directly into a prescription — otherwise a query mentioning a
    # product name could surface a dose with no diagnosis behind it.
    # Scope concepts compete on equal footing with the diseases.
    #
    # Two kinds, both typed Reference so the emitter has nothing to prescribe
    # from and abstains by construction rather than by threshold:
    #
    #   healthy-plant  — an undamaged leaf resembling "no spots, uniform green"
    #                    more than any disease. The honest answer is that nothing
    #                    is wrong, not the nearest disease by elimination.
    #   source_type: scope — a question about something outside the corpus, such
    #                    as fertiliser. "How much urea on my cotton" was matching
    #                    cotton whitefly and cotton jassid on the shared word
    #                    "cotton" and refusing as ambiguous. Safe, but the farmer
    #                    heard two pest names in reply to a fertiliser question.
    #
    # Adding a new out-of-scope topic needs only a file with a `# Response`
    # section — no code change.
    healthy_score = max(
        (h.relevance for h in hits if h.chunk.concept_id == "/diseases/healthy-plant"),
        default=0.0,
    )

    scope_scores: dict[str, float] = {}
    for hit in hits:
        if hit.chunk.source_type != "scope":
            continue
        cid = hit.chunk.concept_id
        scope_scores[cid] = max(scope_scores.get(cid, 0.0), hit.relevance)

    # Aggregate by MAX, not sum. Summing rewards concepts that happen to have
    # more chunks in the corpus rather than better evidence — a long document
    # would out-score a short, exactly-correct one purely on length.
    # Deficiency is a first-class diagnosis, not a disease.
    #
    # A farmer describing brown spots and stunting may be looking at infection
    # OR at hunger, and the two are indistinguishable from the words alone.
    # While only Pest and Disease could be diagnosed here, zinc deficiency in
    # rice was answered with "Rice bacterial leaf blight, use copper
    # oxychloride" - a fungicide-class product for a problem no spray can fix,
    # costing the farmer money and the crop anyway.
    #
    # Deficiency concepts carry no treatments, so a deficiency winning here
    # produces a diagnosis with no label_id. That is the correct outcome, and
    # the existing "no label_id, no prescription" rule turns it into an honest
    # "this is not a disease, do not spray, get a soil test" answer for free.
    condition_scores: dict[str, float] = {}
    for hit in hits:
        if hit.chunk.concept_type not in {"Pest", "Disease", "Deficiency"}:
            continue
        cid = hit.chunk.concept_id
        condition_scores[cid] = max(condition_scores.get(cid, 0.0), hit.relevance)

    best_disease = max(condition_scores.values(), default=0.0)

    if scope_scores:
        cid, score = max(scope_scores.items(), key=lambda kv: kv[1])
        if score > best_disease and score > healthy_score:
            concept = concepts_by_id[cid]
            section = concept.section("Response")
            spoken = (
                section.text.lstrip("> ").replace("\n> ", " ").replace("\n", " ").strip()
                if section
                else "I do not have verified guidance for this. Please ask your "
                     "Krishi Vigyan Kendra."
            )
            return Response(
                outcome=Outcome.OUT_OF_SCOPE,
                condition=concept.title,
                condition_id=cid,
                confidence=score,
                spoken_text=spoken,
                debug={"scope": round(score, 4),
                       "best_disease": round(best_disease, 4)},
            )

    if healthy_score > best_disease:
        return Response(
            outcome=Outcome.HEALTHY,
            condition="Healthy plant",
            condition_id="/diseases/healthy-plant",
            confidence=healthy_score,
            spoken_text=HEALTHY_TEXT,
            debug={"healthy": round(healthy_score, 4),
                   "best_disease": round(best_disease, 4)},
        )

    if not condition_scores:
        # Guideline mode: the answer is a scheme or practice concept, which has
        # no label_id and nothing to prescribe. Return the best passage directly.
        if not require_crop and hits:
            best = hits[0]
            concept = concepts_by_id.get(best.chunk.concept_id)
            if concept and best.relevance >= MIN_RELEVANCE:
                return Response(
                    outcome=Outcome.GUIDELINE,
                    condition=concept.title,
                    condition_id=concept.concept_id,
                    confidence=best.relevance,
                    trust_tier=concept.trust_tier,
                    spoken_text=_summarise(best.chunk.text),
                    debug={"section": best.chunk.heading,
                           "source_type": best.chunk.source_type},
                )
        return Response(
            outcome=Outcome.ABSTAINED_LOW_CONF,
            spoken_text=ABSTENTION_TEXT,
            debug={"reason": "no Pest/Disease concept retrieved",
                   "top_hit": hits[0].chunk.chunk_id},
        )

    ranked = sorted(condition_scores.items(), key=lambda kv: -kv[1])
    top_id, top_score = ranked[0]
    concept = concepts_by_id[top_id]

    debug = {
        "ranked": [(cid, round(s, 4)) for cid, s in ranked[:4]],
        "top_chunks": [
            (h.chunk.chunk_id, f"rel={h.relevance:.3f}",
             f"cos={h.dense_score:.3f}", f"bm25={h.sparse_score:.3f}")
            for h in hits[:4]
        ],
        "crop_filter": crop,
    }

    # Unverified concepts must clear a higher bar than machine-confirmed ones.
    threshold = MIN_RELEVANCE
    if concept.trust_tier == "unverified":
        threshold *= UNVERIFIED_PENALTY
    debug["threshold"] = round(threshold, 4)

    if top_score < threshold:
        return Response(
            outcome=Outcome.ABSTAINED_LOW_CONF,
            condition=concept.title,
            condition_id=top_id,
            confidence=top_score,
            trust_tier=concept.trust_tier,
            spoken_text=ABSTENTION_TEXT,
            debug=debug,
        )

    # Two conditions scoring within a hair of each other is exactly the
    # early-blight/late-blight case. Guessing here is the most expensive error
    # the device can make, so it abstains and names both for the human.
    if len(ranked) > 1 and (top_score - ranked[1][1]) < AMBIGUITY_MARGIN:
        runner = concepts_by_id[ranked[1][0]]
        return Response(
            outcome=Outcome.ABSTAINED_AMBIGUOUS,
            condition=concept.title,
            condition_id=top_id,
            confidence=top_score,
            trust_tier=concept.trust_tier,
            runner_up=runner.title,
            spoken_text=(
                f"This could be {concept.title} or {runner.title}. "
                "I cannot tell them apart. "
                "Please show this plant to your nearest Krishi Vigyan Kendra."
            ),
            debug=debug,
        )

    # Disease-vs-deficiency confusion. Wider than AMBIGUITY_MARGIN, and
    # deliberately one-directional, because the two mistakes do not cost the
    # same. Selling a fungicide to a farmer whose crop is actually short of
    # zinc takes his money AND leaves the real problem untreated; suggesting a
    # soil check when it turns out to be rust costs him a few days. So a
    # deficiency sitting close behind a disease blocks the prescription, while
    # a disease sitting close behind a deficiency does not (that path never
    # prescribes anyway - deficiency concepts carry no label record).
    #
    # 0.11 is measured, not guessed. Across the eval suites the lowest gap on a
    # correct grounded disease answer is 0.149 ("rice leaf turning straw colour
    # from the tip"); the three real-audio failures sit at 0.042, 0.070 and
    # 0.079. Nothing falls in between, and 0.11 is the middle of that gap.
    if len(ranked) > 1 and concept.type in {"Disease", "Pest"}:
        for rid, rscore in ranked[1:]:
            other = concepts_by_id.get(rid)
            if other is None or other.type != "Deficiency":
                continue
            if top_score - rscore >= DEFICIENCY_CONFUSION_MARGIN:
                break
            debug["deficiency_gap"] = round(top_score - rscore, 4)
            debug["deficiency_runner"] = rid
            return Response(
                outcome=Outcome.ABSTAINED_AMBIGUOUS,
                condition=concept.title,
                condition_id=top_id,
                confidence=top_score,
                trust_tier=concept.trust_tier,
                runner_up=other.title,
                spoken_text=(
                    f"This could be {concept.title}, which is a disease, or it "
                    f"could be {other.title}, which means the soil is short of "
                    "food. The treatment is completely different, and a spray "
                    "will not fix a shortage in the soil. Please show the plant "
                    "to your nearest Krishi Vigyan Kendra before buying anything."
                ),
                debug=debug,
            )
            break

    # Resolve linked Treatment concepts. This is the grounding step.
    treatments: list[dict] = []
    for link in concept.treatments:
        tid = link[: -len(".md")] if link.endswith(".md") else link
        treatment = concepts_by_id.get(tid)
        if treatment is not None and treatment.label_id:
            treatments.append(_fmt_treatment(treatment))

    if not treatments:
        # Diagnosis succeeded but there is no verified label record to quote.
        # The device says what it sees and stops. It does not improvise.
        return Response(
            outcome=Outcome.ABSTAINED_NO_LABEL,
            condition=concept.title,
            condition_id=top_id,
            confidence=top_score,
            trust_tier=concept.trust_tier,
            spoken_text=_no_label_text(concept),
            debug=debug,
        )

    # A symptom-evidence gate used to sit here and has been REMOVED. Recorded
    # so nobody rebuilds it:
    #
    # It required the query to contain at least 2 words from a vocabulary
    # harvested out of the corpus's own symptom sections, on the theory that a
    # crop name alone should never buy a pesticide. It did fix the two cases it
    # was built for (a fertiliser question whose key word ASR had destroyed).
    #
    # It also blocked the single most common thing a farmer says:
    #
    #   "आलू में झुलसा रोग के दवा का नाम बताइए"  (case 11, 0.0% WER)
    #   -> "Name the medicine for blight in potatoes"      scored 0
    #   "आलू में झुलसा रोग लगा है, क्या करें?"    (case 12)
    #   -> "What to do if the potato is infected"          scored 1
    #
    # Naming the disease IS describing the problem. The farmer does not have to
    # narrate spots and colours when they already know what it is. A vocabulary
    # of symptom *descriptions* cannot see that, and title matching does not
    # rescue it either - NMT rendered झुलसा (blight) as "scabies", so the query
    # shared no words with the concept it correctly matched.
    #
    # Confidence does not separate the two groups either, measured:
    #   case 11 legitimate 0.531   case 26 bad 0.535   case 13 bad 0.631
    #
    # Blocking "my crop has blight, what medicine" to catch a mangled fertiliser
    # question trades the device's core purpose for a rare edge case. The
    # remaining exposure is real and is documented in COMPARISON.md, but it
    # needs ASR that keeps entity words, or intent classification in the router
    # - not another retrieval-side gate.

    # Off-registration guard. The last thing checked before a chemical is named.
    off = registration_holds(query, treatments, concepts_by_id, crop)
    if off:
        debug["off_registration"] = off
        return Response(
            outcome=Outcome.ABSTAINED_NO_LABEL,
            condition=concept.title,
            condition_id=top_id,
            confidence=top_score,
            trust_tier=concept.trust_tier,
            spoken_text=(
                f"The medicine I have on record for this is registered for "
                f"{off}, and I cannot tell that your crop is {off}. Using it on "
                "a crop it is not registered for is unsafe and not allowed. "
                "Please tell me which crop this is, or ask your Krishi Vigyan "
                "Kendra."
            ),
            debug=debug,
        )

    return Response(
        outcome=Outcome.GROUNDED,
        condition=concept.title,
        condition_id=top_id,
        confidence=top_score,
        trust_tier=concept.trust_tier,
        label_ids=[t["label_id"] for t in treatments],
        treatments=treatments,
        spoken_text=_speak(concept.title, treatments),
        debug=debug,
    )
