"""Route a farmer's question to the right RAG module.

Two engines now answer questions, and they overlap:

    krishi-rag       crops, pests, diseases, deficiencies, pesticide doses,
                     safety — and 15 government scheme concepts
    schemes-rag      Palak's engine — 15 government schemes, Hinglish query
                     expansion, LCD + voice output formatting

Ten of the fifteen schemes appear in BOTH (PM-KISAN, PMFBY, KCC, PMKSY, Soil
Health Card, PM-KMY, e-NAM, PKVY, AIF, RKVY). So this is not "add a second
index" — without a routing decision the same question has two answers and
whichever engine is asked first wins by accident.

WHY A RULE-BASED ROUTER

This is the intent-classification step Vinay described, and it does not need a
model. Scheme questions are marked by a small closed vocabulary — the scheme
name itself, or words like subsidy, eligibility, apply, documents. A rule set is
inspectable, costs microseconds, and adds nothing to the memory budget. A
measured rule-based intent classifier on Hindi already scored 86% in this
project, so the approach is not a guess.

WHO OWNS WHAT, AND WHY

  schemes  -> Palak's engine. It is purpose-built: query expansion for Hinglish
              ("paisa", "karza", "tubewell"), per-intent answers (documents vs
              eligibility vs how-to-apply), and a farmer-voice output format.
              Our scheme concepts are prose passages by comparison.
  crops    -> krishi-rag. Palak's engine has no crop, disease or dose data at
              all, and its own out-of-domain gate rejects those questions.
  unsure   -> krishi-rag, because its abstention gates are the stricter of the
              two and a wrong crop answer is more dangerous than a wrong
              scheme answer.

That last line is the safety argument for the default: the worst a misrouted
scheme question produces is an unhelpful reply, while a misrouted crop question
could reach a pesticide dose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Module(Enum):
    SCHEMES = "schemes"
    CROP = "crop"


# Scheme names and their common spoken forms. Presence of any of these is close
# to conclusive - a farmer does not say "PM Kisan" about a leaf spot.
SCHEME_NAMES = (
    "pm kisan", "pm-kisan", "pmkisan", "kisan samman", "samman nidhi",
    "fasal bima", "pmfby", "crop insurance", "beema", "bima",
    "kisan credit", "kcc", "credit card",
    "sinchayee", "pmksy", "per drop", "micro irrigation", "drip", "sprinkler",
    "soil health card", "shc",
    "maandhan", "pension", "pm-kmy", "pmkmy",
    "kusum", "solar pump",
    "e-nam", "enam", "national agriculture market", "mandi portal",
    "smam", "mechanization", "custom hiring", "tractor subsidy",
    "pkvy", "paramparagat", "organic farming scheme", "jaivik kheti",
    "mgnrega", "nrega", "job card",
    "pmfme", "food processing",
    "agriculture infrastructure fund", "aif", "cold storage subsidy",
    "rkvy", "raftaar", "agri startup",
    "matsya", "pmmsy", "fisheries", "fish pond",
    "fertiliser subsidy", "fertilizer subsidy", "seed subsidy",
    "lakhpati didi", "drone didi", "vishwakarma", "svamitva", "ujjwala",
    "ayushman", "pm-jay", "pmgkay", "pmay", "pmay-g", "green credit",
    "carbon credit", "carbon market", "stubble burning", "livestock mission", "nlm",
)

# Words that signal a benefits/administration question rather than a plant one.
SCHEME_INTENT = (
    "scheme", "yojana", "yojna", "subsidy", "subsidi", "loan", "karza", "karz",
    "eligible", "eligibility", "patra", "apply", "avedan", "application",
    "register", "registration", "documents", "document", "kagaz", "paper",
    "installment", "kist", "benefit", "labh", "entitle", "government",
    "sarkar", "sarkari", "portal", "form", "bank account", "dbt",
    "how much money", "kitna paisa", "pension", "insurance", "claim",
)

# Words that mean a plant problem. These WIN over scheme words, because
# "subsidy for pesticide for my tomato blight" is a crop question wearing a
# scheme word.
CROP_INTENT = (
    "leaf", "leaves", "patta", "patte", "spot", "spots", "dhabba", "blight",
    "rot", "wilt", "rust", "mildew", "mosaic", "curl", "borer", "caterpillar",
    "sundi", "aphid", "whitefly", "thrips", "mite", "pest", "insect", "keeda",
    "disease", "rog", "bimari", "fungus", "fungicide", "insecticide",
    "pesticide", "spray", "chidkav", "chhidkav", "dose", "how much to spray",
    "yellowing", "stunted", "deficiency", "kami", "crop is", "plant is",
    "my tomato", "my rice", "my wheat", "my cotton", "my paddy",
)

_WORD = re.compile(r"[a-z0-9\-]+")


@dataclass
class ModuleDecision:
    module: Module
    reason: str
    confidence: str          # "high" | "low"


def route_module(question: str) -> ModuleDecision:
    """Pick the module. English text, post-NMT — the RAG only sees English."""
    q = question.lower()
    words = set(_WORD.findall(q))

    crop_hit = next((t for t in CROP_INTENT
                     if (t in q if " " in t else t in words)), None)
    name_hit = next((n for n in SCHEME_NAMES if n in q), None)
    intent_hit = next((t for t in SCHEME_INTENT
                       if (t in q if " " in t else t in words)), None)

    # A plant word present at all means a crop question, even alongside scheme
    # words. "Is there a subsidy for the spray for my tomato blight" is asking
    # about a blight; answering it with a scheme leaves the disease untreated.
    if crop_hit:
        return ModuleDecision(
            Module.CROP, f"crop term '{crop_hit}'",
            "low" if (name_hit or intent_hit) else "high")

    if name_hit:
        return ModuleDecision(Module.SCHEMES, f"scheme named '{name_hit}'", "high")
    if intent_hit:
        return ModuleDecision(Module.SCHEMES, f"scheme intent '{intent_hit}'", "high")

    # Nothing matched. Default to the crop engine because its abstention gates
    # are stricter, so an unclear question ends in an honest refusal rather
    # than a confident irrelevant answer.
    return ModuleDecision(Module.CROP, "no signal; defaulting to stricter engine",
                          "low")


if __name__ == "__main__":
    TESTS = [
        "am I eligible for PM Kisan",
        "how much money do I get under pm kisan",
        "what documents are needed for kisan credit card",
        "brown spots with rings on lower tomato leaves",
        "my rice leaves have brown spots and plants are stunted",
        "how much mancozeb for potato blight",
        "is there a subsidy for the spray for my tomato blight",
        "solar pump subsidy",
        "someone drank pesticide",
        "when will the rain come",
    ]
    for t in TESTS:
        d = route_module(t)
        print(f"  {d.module.value:8} {d.confidence:5}  {t[:48]:48} ({d.reason})")
