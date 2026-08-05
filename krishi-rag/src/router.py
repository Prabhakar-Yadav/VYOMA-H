"""Consequence-based routing: what the model may answer, and what must be grounded.

The rule is not "how confident is the model" — it will be confident either way.
The rule is **what does a wrong answer cost the farmer**.

    "Why are my cotton leaves turning yellow?"
        Nitrogen shortage, waterlogging or sucking pests. A slightly imperfect
        explanation costs nothing. Let the model answer.

    "How much urea should I put?"
        A number the farmer will act on. The model will produce a confident,
        plausible dose from parametric memory. We hold no verified fertiliser
        records, so retrieval finds nothing, confidence drops, and the device
        says it does not know. That only works if retrieval is not optional.

So: **anything carrying a number, a product name, or a safety instruction is
grounded. General explanation is not.**

Routing runs on cheap deterministic checks before any model call. Crop names
(454 of them) and product names are fixed lists, so those lookups are exact and
free. Qwen 2B is unreliable at tool selection, so the fewer decisions it makes,
the fewer it gets wrong.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from phonetic import CONFIDENT, MIN_FUZZY_LEN, PLAUSIBLE, PhoneticIndex


class Route(str, Enum):
    DIAGNOSE = "crop_diagnosis"      # photo present, or crop + symptom
    PESTICIDE = "pesticide_lookup"   # product named, or a dose/safety question
    GUIDELINE = "guideline_lookup"   # scheme, subsidy, safety practice, procedure
    GROUNDED_GENERAL = "grounded_general"  # consequential, but not the above
    MODEL_MAY_ANSWER = "model_may_answer"  # low stakes, model is fine


# Scheme, entitlement and official-procedure terms.
#
# These must be grounded even though they carry no crop. A model asked "am I
# eligible for PM-KISAN" produces a fluent, plausible, wrong answer, and the
# farmer finds out at the bank counter. Eligibility rules, amounts, documents and
# deadlines are exactly the kind of detail that gets invented confidently.
SCHEME_TERMS = {
    "pm kisan", "pm-kisan", "pmkisan", "samman nidhi",
    "fasal bima", "pmfby", "crop insurance", "insurance",
    "kisan credit", "kcc", "credit card", "loan", "subsidy", "subsidised",
    "soil health card", "soil card", "soil test", "soil testing", "soil sample",
    "sinchayee", "pmksy", "drip", "sprinkler", "micro irrigation",
    "paramparagat", "pkvy", "organic certification",
    "e-nam", "enam", "mandi", "msp", "minimum support price",
    "smam", "machinery subsidy", "tractor subsidy",
    "maandhan", "pension", "rkvy", "nmeo",
    "scheme", "yojana", "eligible", "eligibility", "apply", "application",
    "documents", "registration", "register", "aadhaar", "beneficiary",
    "kisan call centre", "helpline", "kvk", "krishi vigyan kendra",
    "installment", "instalment", "benefit",
}

# Official safety practice. No crop, but high consequence.
SAFETY_TERMS = {
    "triangle", "red triangle", "yellow triangle", "blue triangle", "green triangle",
    "poison", "poisoning", "swallowed", "drank", "inhaled", "antidote",
    "first aid", "emergency", "hospital", "ambulance",
    "empty container", "dispose", "disposal", "store pesticide", "storage",
    "protective", "gloves", "mask", "spray safely", "safety",
    "residue", "mrl", "pre-harvest interval", "waiting period",
    "seed treatment", "treat seed", "stubble", "residue burning",
    "ipm", "integrated pest management",
}


# Words that mean the answer will be acted on with money, chemicals or a harvest
# decision. Any of these forces grounding regardless of what the model "knows".
CONSEQUENTIAL = {
    # quantity
    "dose", "dosage", "how much", "how many", "quantity", "per acre", "per litre",
    "per hectare", "ml", "gram", "grams", "kg", "litre", "liter", "spray rate",
    # timing that gates food safety
    "harvest", "waiting period", "pre-harvest", "phi", "how long before",
    "how many days", "when can i pick", "when can i sell",
    # safety
    "safe", "poison", "toxic", "bees", "children", "cattle", "drink", "eat",
    "antidote", "protective", "mask",
    # mixing and application
    "mix", "tank mix", "combine", "together with", "rain", "rainfast",
    "how to apply", "how to spray",
}

# Biology questions — life cycle, seasonality, hosts, spread, why a control
# works. These belong to the entomology/pathology corpora and must not be routed
# through crop diagnosis, which boosts `diseases` and would bury them.
BIOLOGY_TERMS = {
    "life cycle", "lifecycle", "how long", "how many generations", "generations",
    "when does", "when do", "peak", "season", "seasonal", "which month", "months",
    "overwinter", "survive", "carry over", "carryover", "diapause",
    "where does", "where do", "lay eggs", "eggs", "larva", "nymph", "pupa",
    "alternate host", "weed host", "host plant", "spread", "how does it spread",
    "natural enemies", "predator", "parasitoid", "biological control",
    "threshold", "etl", "resistance", "why does", "fungal", "bacterial", "viral",
    "fungicide work", "does a fungicide", "what kind of",
}

# Question shapes that are explanatory rather than actionable.
EXPLANATORY_OPENERS = (
    "what is", "what are", "why do", "why does", "why is", "why are",
    "how does", "how do", "explain", "tell me about", "what causes",
)

_SPLIT = re.compile(r"[^\w%]+")


@dataclass
class RouteDecision:
    route: Route
    reason: str
    crop: str | None = None
    product: str | None = None
    # A crop problem may be an infection OR a nutrient deficiency, and the two
    # are indistinguishable from a farmer's words alone, so diagnosis routes
    # boost both corpora. A single string is still accepted for the routes that
    # genuinely want one corpus (treatments, guidelines, entomology).
    boost_source: str | list[str] | None = None
    matched: list[str] = field(default_factory=list)
    # Confidence of the entity match that drove the decision. 1.0 for an exact
    # hit. Below phonetic.CONFIDENT the caller must treat the match as a guess
    # and prefer deferring to a Krishi Vigyan Kendra.
    entity_confidence: float = 1.0
    heard_as: str | None = None

    @property
    def needs_retrieval(self) -> bool:
        return self.route != Route.MODEL_MAY_ANSWER


def _tokens(text: str) -> set[str]:
    return {t for t in _SPLIT.split(text.lower()) if t}


def _find_phrase(text: str, phrases) -> list[str]:
    lowered = text.lower()
    toks = _tokens(text)
    return [p for p in phrases if (p in lowered if " " in p else p in toks)]


_SYMPTOM_WORDS = (
    "spot", "spots", "patch", "patches", "lesion", "blotch", "curl", "curling",
    "yellow", "brown", "black", "white", "powder", "wilting", "wilted", "rot",
    "hole", "holes", "ring", "rings", "streak", "stripe", "mould", "mold",
    "dying", "drooping", "collapsed", "shrivel", "frass", "webbing",
)


def crop_symptom_shape(lowered: str) -> bool:
    """True when the query reads as a description of what a plant looks like.

    Keeps "my chilli leaves are curling and yellow" on the diagnosis path even
    though it contains the biology word "yellow".
    """
    return sum(1 for w in _SYMPTOM_WORDS if w in lowered) >= 2


def route(
    query: str,
    has_image: bool,
    crop: str | None,
    coverage_gate,
    product_names: dict[str, str] | None = None,
    product_index: PhoneticIndex | None = None,
    crop_index: PhoneticIndex | None = None,
) -> RouteDecision:
    """Decide where a query goes. No model call involved.

    `coverage_gate` is a grounding.CoverageGate — it already holds every crop
    name we recognise. `product_names` maps a lowercase trade or molecule name
    onto its label_id.
    """
    product_names = product_names or {}
    lowered = query.lower()

    # 1. A photograph can only be about crop diagnosis. Nothing else takes images.
    if has_image:
        return RouteDecision(
            Route.DIAGNOSE, "image present", crop=crop,
            boost_source=["diseases", "deficiencies"]
        )

    # 2. A named product goes straight to the label record. Exact list, exact match.
    hits = _find_phrase(lowered, product_names.keys())
    if hits:
        name = max(hits, key=len)
        return RouteDecision(
            Route.PESTICIDE,
            f"product named: {name}",
            product=product_names[name],
            boost_source="treatments",
            matched=hits,
        )

    # Phonetic fallback for products.
    #
    # Product names are the one entity class NMT never translates — "Mancozeb"
    # is a proper noun and passes through untouched, so an ASR mishearing
    # arrives intact. They are also long and distinctive, which makes fuzzy
    # matching safe here in a way it is not for short crop names.
    if product_index is not None:
        value, score, heard = product_index.match_query(query, threshold=PLAUSIBLE)
        if value is not None:
            return RouteDecision(
                Route.PESTICIDE,
                "product heard as '{}' ({:.0%})".format(heard, score),
                product=value,
                boost_source="treatments",
                entity_confidence=score,
                heard_as=heard,
            )

    # 3. Schemes and official safety practice. Checked before the consequential
    #    and explanatory tests, because these questions carry no crop and would
    #    otherwise either fall to the model or be blocked by the crop gate.
    #    "How much do I get under PM-KISAN" contains "how much" but is a scheme
    #    question, not a dose question.
    scheme_hits = _find_phrase(lowered, SCHEME_TERMS)
    safety_hits = _find_phrase(lowered, SAFETY_TERMS)
    if scheme_hits or safety_hits:
        hits_all = sorted(scheme_hits + safety_hits, key=len, reverse=True)
        return RouteDecision(
            Route.GUIDELINE,
            f"scheme/safety terms: {', '.join(hits_all[:3])}",
            boost_source="govt_guideline",
            matched=hits_all,
        )

    # 4. Anything with a number, a waiting period or a safety implication must be
    #    grounded, whatever the subject.
    consequential = _find_phrase(lowered, CONSEQUENTIAL)
    if consequential:
        named_crop = crop or coverage_gate.scan_covered(query)
        return RouteDecision(
            Route.DIAGNOSE if named_crop else Route.GROUNDED_GENERAL,
            f"consequential terms: {', '.join(sorted(consequential)[:3])}",
            crop=named_crop,
            boost_source="treatments",
            matched=consequential,
        )

    # 4. Biology questions go to the entomology/pathology corpora.
    bio = _find_phrase(lowered, BIOLOGY_TERMS)
    if bio and not crop_symptom_shape(lowered):
        return RouteDecision(
            Route.GUIDELINE,
            f"biology question: {', '.join(sorted(bio, key=len, reverse=True)[:2])}",
            boost_source="entomology",
            matched=bio,
        )

    # 5. Explanatory questions with nothing actionable in them. Checked BEFORE
    #    the crop test, because "why are my cotton leaves turning yellow" names a
    #    crop but asks for an explanation, not a prescription. Nitrogen shortage,
    #    waterlogging or sucking pests are all reasonable answers and a slightly
    #    imperfect one costs the farmer nothing.
    if any(lowered.strip().startswith(o) for o in EXPLANATORY_OPENERS):
        return RouteDecision(Route.MODEL_MAY_ANSWER, "explanatory question, no action implied")

    # 6. A crop plus a symptom description is a diagnosis question.
    named_crop = crop or coverage_gate.scan_covered(query)
    if named_crop:
        return RouteDecision(
            Route.DIAGNOSE, f"crop named: {named_crop}",
            crop=named_crop, boost_source=["diseases", "deficiencies"],
        )

    # Phonetic crop match, deliberately much stricter than for products.
    #
    # Crop names are short and there are 454 of them, so loosening the match
    # creates collisions between genuinely different crops — jau (barley)
    # against jowar (sorghum), kel against kela. Those carry different diseases
    # and different chemicals, so a wrong match is worse than no match.
    #
    # Two guards: the heard word must be long enough to be distinctive, and the
    # score must clear the high bar rather than the plausible one. Anything
    # weaker falls through and the query is deferred.
    if crop_index is not None:
        value, score, heard = crop_index.match_query(query, threshold=0.0)
        if value and heard and len(heard) >= MIN_FUZZY_LEN and score >= CONFIDENT:
            return RouteDecision(
                Route.DIAGNOSE,
                "crop heard as '{}' ({:.0%})".format(heard, score),
                crop=value, boost_source=["diseases", "deficiencies"],
                entity_confidence=score, heard_as=heard,
            )

    # 7. Default to grounding. When in doubt, retrieve — the failure mode of
    #    unnecessary retrieval is 16 ms, and the failure mode of skipping it is
    #    a confident invented answer.
    return RouteDecision(Route.GROUNDED_GENERAL, "default: ground it")


def build_product_index(concepts) -> dict[str, str]:
    """Map every trade name and molecule onto its label_id."""
    index: dict[str, str] = {}
    for c in concepts:
        if c.type != "Treatment" or not c.label_id:
            continue
        for key in [c.frontmatter.get("molecule"), c.title]:
            if key:
                index[str(key).lower()] = c.label_id
        for trade in c.frontmatter.get("common_trade_names") or []:
            index[str(trade).lower()] = c.label_id
    return index
