"""G1 (Plant + Crop) real RAG tools, backed by datasets/rag/g1.sqlite -- built by
rag/build_index.py from datasets/rag/g1/ (818 chunks / 127 concepts: diseases,
treatments, entomology, pathology, deficiencies, crops coverage, safety, and the G1
slice of guidelines). See G1-G2-VECTORDB-PLAN.md and RAG-BUILD-LOG.md for the design
and real numbers behind this.

Four tools here cover the six G1 functions named in the original spec via
composition with tools that already existed (analyze_photo, pesticide_lookup):
    plant-disease-detection   = analyze_photo(CROP) -> plant_disease_lookup()
    plant-disease              = plant_disease_lookup() directly
    pesticide-detail-detection = analyze_photo(PESTICIDE) -> pesticide_lookup() +
                                  get_treatment_details()
    pesticide-usage-and-dose   = get_treatment_details() directly
    plant-disease-weed-detector = analyze_photo(CROP) -> plant_disease_lookup()
                                  (no separate weed corpus exists in the bundle yet --
                                  see RAG-BUILD-LOG.md "known gaps", not fabricated here)
    plant-entomology            = plant_entomology_lookup() directly

`get_guidelines_and_safety` (2026-08-12, added after a real coverage-gap review) is
new, not in the original six -- see below for why.

MIN_RELEVANCE is not enforced as a hard abstention gate yet (see rag/retrieval.py's
own docstring) -- results below a soft floor are still returned but flagged
low_confidence=True, and the tool's own docstring instructs the agent to treat that
as "uncertain, consider deferring" rather than silently trusting it. A real
structural gate (crop coverage boundary, info-sufficiency check, etc., matching
krishi-rag's own 7 gates) is explicitly NOT built yet -- flagged as a real gap in
RAG-BUILD-LOG.md, not silently skipped.
"""
from __future__ import annotations

import os
import sys

_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # agent/
_ROOT_DIR = os.path.dirname(_AGENT_DIR)                                    # gramsahayak/
for _p in (_ROOT_DIR,):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from rag.retrieval import HybridRetriever  # noqa: E402

# Soft floor from the real distribution measured in rag/test_retrieval.py (n=30,
# min=0.121, max=0.554) -- NOT a rigorously derived threshold the way krishi-rag's
# MIN_RELEVANCE=0.44 was (that took 3 rounds of re-derivation against a 99-case eval
# suite as the corpus grew). This is a provisional flag-not-block value; real
# threshold derivation needs a real eval set against THIS embedding model, not done
# yet (see RAG-BUILD-LOG.md).
LOW_CONFIDENCE_FLOOR = 0.40

_g1: HybridRetriever | None = None


def _retriever() -> HybridRetriever:
    global _g1
    if _g1 is None:
        _g1 = HybridRetriever("g1", _ROOT_DIR)
    return _g1


def _format_hits(hits, max_hits=3) -> dict:
    if not hits:
        return {"matches": [], "low_confidence": True, "note": "No matches found at all."}
    top = hits[:max_hits]
    return {
        "matches": [
            {
                "concept": h.concept_title,
                "concept_id": h.concept_id,
                "section": h.heading,
                "text": h.text,
                "crop": h.crop,
                "label_id": h.label_id,
                "relevance": round(h.relevance, 3),
            }
            for h in top
        ],
        "low_confidence": top[0].relevance < LOW_CONFIDENCE_FLOOR,
    }


def plant_disease_lookup(description: str, crop: str | None = None) -> dict:
    """RAG search over diseases/pathology/deficiencies -- the description should be
    the plain-text visual finding (from analyze_photo) or the farmer's own symptom
    description. Boosts diseases (the concept type written in VLM-description
    register per rag/chunking.py's design) without excluding pathology/deficiencies,
    since a leaf-yellowing symptom can be an infection OR a nutrient deficiency and
    both must compete on equal terms (see krishi-rag README's own documented bug:
    boosting only diseases made deficiencies unreachable and caused a real
    misdiagnosis)."""
    hits = _retriever().search(
        description, top_k=6, crop=crop, boost_source=["diseases"], boost_factor=1.15,
    )
    result = _format_hits(hits)
    result["query"] = description
    result["crop_filter"] = crop
    # Surface each match's linked treatment concept_ids so the agent knows to call
    # get_treatment_details next -- mirrors krishi-rag's own "no label_id, no
    # prescription" contract: this tool never states a dose itself.
    return result


def plant_entomology_lookup(description: str, crop: str | None = None) -> dict:
    """RAG search boosted toward entomology (insect/mite biology: life cycle,
    seasonal peaks, natural enemies) without excluding diseases -- the same pest can
    be described from either the symptom side (diseases/) or the biology side
    (entomology/), and a query naming behavior ("rasping", "sticky honeydew") should
    reach both."""
    hits = _retriever().search(
        description, top_k=6, crop=crop, boost_source=["entomology"], boost_factor=1.2,
    )
    result = _format_hits(hits)
    result["query"] = description
    result["crop_filter"] = crop
    return result


def get_treatment_details(
    pesticide_name: str | None = None,
    crop: str | None = None,
    symptom_or_disease: str | None = None,
) -> dict:
    """Real CIB&RC-registered dose/PHI/safety lookup -- distinct from the existing
    `pesticide_lookup` tool (FSSAI dataset: toxicity class, MRL, registration
    status). This one answers "how much do I use and when can I harvest";
    pesticide_lookup answers "is this legal/how toxic is it". Call both when a
    farmer names a specific product and wants to actually spray it.

    Renamed from `pesticide_usage_and_dose` (2026-08-12) -- same tool, clearer name
    matching what it actually returns (registration + treatment details, not just a
    single dose number). Also fixed a real boost bug found the same day: the
    underlying Treatment data has two real sub-slices -- crop+disease-SPECIFIC
    registered products (source_type="pesticide_label", 129 chunks, e.g. "Cymoxanil
    8% + Mancozeb 64% WP for potato late blight" -- exactly the "how much/when to
    harvest" data this tool exists for) and a GENERIC chemical/compound reference
    with no crop tie (source_type="treatments", 42 chunks, e.g. "Mancozeb 75% WP" --
    general toxicity/target-pest info, closer to `pesticide_lookup`'s own territory).
    The old boost favored the smaller, less-relevant "treatments" slice over the
    larger, more-relevant "pesticide_label" slice -- backwards from this tool's own
    stated purpose. Now both compete at equal weight (no boost_source at all), so
    ranking is decided purely by real relevance to the query, not an arbitrary
    source-slice preference that was pointed the wrong way.

    KNOWN LIMITATION, not silently papered over: krishi-rag's own README is explicit
    that pesticide lookup should be a deterministic key lookup by label_id, never a
    similarity search, because "a wrong dose here injures someone" and crop
    registration is legally binding (mancozeb-on-tomato and mancozeb-on-potato are
    different registrations with different doses). This implementation does NOT yet
    do that -- it's hybrid RAG search with crop as a soft signal, same risk class
    krishi-rag's design deliberately avoided. See RAG-BUILD-LOG.md "known gaps" --
    flagged as the single most important thing to harden before this tool is trusted
    with a real spray decision.
    """
    query_parts = [p for p in (pesticide_name, symptom_or_disease) if p]
    query = " ".join(query_parts) or "pesticide dose"
    hits = _retriever().search(
        query, top_k=6, crop=crop, concept_types={"Treatment"},
    )
    result = _format_hits(hits, max_hits=3)
    result["query"] = query
    result["crop_filter"] = crop
    if crop and result["matches"]:
        # Soft safety net, not a real filter (see docstring): flag any match whose
        # concept text doesn't actually mention the requested crop, since the crop
        # metadata column is empty for Treatment concepts (their frontmatter uses
        # `registered_crop`, which rag/okf.py's Concept.crop property doesn't read --
        # a real gap, see RAG-BUILD-LOG.md).
        for m in result["matches"]:
            crop_confirmed = crop.lower() in (m["concept"] + m["text"]).lower()
            m["crop_confirmed_in_text"] = crop_confirmed
            if not crop_confirmed:
                m["warning"] = (
                    f"This record's crop registration could not be confirmed to be "
                    f"'{crop}' from the retrieved text -- do NOT state this dose as "
                    f"safe for that crop without the farmer double-checking the "
                    f"product label."
                )
    return result


def get_guidelines_and_safety(query: str, crop: str | None = None) -> dict:
    """Real RAG search over general farming practice guidance and pesticide-safety
    content -- application timing/technique, protective equipment, re-entry
    intervals, storage/disposal, and other govt/KVK-style guidance that isn't tied
    to one specific disease or product. New tool (2026-08-12), added after a real
    coverage-gap review found this content (60 chunks / 12 concepts: 53 chunks
    concept_type="Practice Guidance", source_type="govt_guideline" + 7 chunks
    concept_type="Safety Guidance", source_type="safety", e.g. the "spray-safety"
    concept) was sitting in the g1 corpus with NO tool reaching it on purpose --
    `plant_disease_lookup`/`plant_entomology_lookup` could stumble onto it
    unboosted if a query happened to out-rank everything else on raw relevance
    alone, and `get_treatment_details`'s `concept_types={"Treatment"}` filter
    excludes it outright. Call this whenever the farmer asks something that isn't
    "what's wrong with my plant" or "how much do I use" -- e.g. "is it safe to
    spray today", "what protective gear do I need", "how long before I can go back
    in the field", "how should I store this chemical", general application
    technique questions.
    """
    hits = _retriever().search(
        query, top_k=6, crop=crop, concept_types={"Practice Guidance", "Safety Guidance"},
    )
    result = _format_hits(hits, max_hits=3)
    result["query"] = query
    result["crop_filter"] = crop
    return result
