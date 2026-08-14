"""G2 (Government Schemes + Programs) real RAG tools, backed by
datasets/rag/g2.sqlite (60 chunks / 17 concepts: 15 real schemes + 2 shared
human-escalation docs also present in G1). See G1-G2-VECTORDB-PLAN.md and
RAG-BUILD-LOG.md for the design and real numbers behind this.

Four tools requested, all real RAG over the same g2 index -- there is no separate
eligibility-rules table or disaster-relief table in the corpus (the original spec
called for "Eligibility Rules -> RAG + Table" and "-> RAG (TABLE)" for these), so
match_eligible_schemes and get_disaster_relief_options are HONEST soft-RAG wrappers
with query-shaping, not table lookups against real structured eligibility data --
flagged clearly in each docstring, not disguised as more deterministic than they are.
"""
from __future__ import annotations

import os
import sys

_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROOT_DIR = os.path.dirname(_AGENT_DIR)
for _p in (_ROOT_DIR,):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from rag.retrieval import HybridRetriever  # noqa: E402

LOW_CONFIDENCE_FLOOR = 0.40  # same provisional floor as g1_rag_tools.py -- see that
# module's docstring for why this isn't a rigorously derived threshold yet.

_g2: HybridRetriever | None = None


def _retriever() -> HybridRetriever:
    global _g2
    if _g2 is None:
        _g2 = HybridRetriever("g2", _ROOT_DIR)
    return _g2


def _format_hits(hits, max_hits=3) -> dict:
    if not hits:
        return {"matches": [], "low_confidence": True, "note": "No matching scheme found."}
    top = hits[:max_hits]
    return {
        "matches": [
            {
                "scheme": h.concept_title,
                "concept_id": h.concept_id,
                "section": h.heading,
                "text": h.text,
                "relevance": round(h.relevance, 3),
            }
            for h in top
        ],
        "low_confidence": top[0].relevance < LOW_CONFIDENCE_FLOOR,
    }


def get_scheme_details(query: str, scheme_name: str | None = None) -> dict:
    """RAG search for a specific scheme's details -- eligibility, benefit amount,
    application process, documents needed, FAQ. Pass `scheme_name` if the farmer
    already named one (e.g. "PM-KISAN", "PMFBY", "KCC") to narrow the query text;
    otherwise pass their raw question and let retrieval find the right scheme."""
    text = f"{scheme_name}: {query}" if scheme_name else query
    hits = _retriever().search(text, top_k=5)
    result = _format_hits(hits)
    result["query"] = text
    return result


def match_eligible_schemes(
    state: str | None = None,
    land_size_acres: float | None = None,
    crop: str | None = None,
    category: str | None = None,
) -> dict:
    """SOFT RAG, not a real eligibility-rules engine -- turns the farmer's profile
    into a natural-language query and searches the same scheme corpus everything
    else here uses. There is no structured eligibility-rules table in the corpus
    (each scheme concept's eligibility criteria are prose inside its own body text,
    not a queryable table) -- this returns schemes whose text is *topically close* to
    the given profile, which is a real, useful first pass but is NOT the same as
    evaluating "is this specific farmer actually eligible" against real rules. The
    agent must still tell the farmer to confirm eligibility on the scheme's own
    application channel, never state eligibility as settled from this alone."""
    profile_bits = []
    if land_size_acres is not None:
        size_class = "small/marginal" if land_size_acres <= 2 else (
            "medium" if land_size_acres <= 10 else "large")
        profile_bits.append(f"{land_size_acres} acre {size_class} landholding farmer")
    if crop:
        profile_bits.append(f"growing {crop}")
    if state:
        profile_bits.append(f"in {state}")
    if category:
        profile_bits.append(category)
    query = "government schemes for a farmer: " + ", ".join(profile_bits) if profile_bits \
        else "general government schemes for farmers"

    hits = _retriever().search(query, top_k=6)
    result = _format_hits(hits, max_hits=5)
    result["profile"] = {"state": state, "land_size_acres": land_size_acres, "crop": crop, "category": category}
    result["query"] = query
    result["disclaimer"] = (
        "These are topically relevant schemes, not a confirmed eligibility "
        "determination -- the farmer should verify against the scheme's own "
        "eligibility rules before applying."
    )
    return result


def get_disaster_relief_options(query: str) -> dict:
    """RAG search shaped toward disaster/crop-loss relief -- boosts the query text
    with disaster-relief vocabulary since there's no separate disaster-relief corpus
    (PMFBY crop insurance is the real disaster-relief-relevant scheme currently in
    the bundle; a dedicated disaster-relief fund/scheme, if one exists, is not yet
    in this corpus -- see RAG-BUILD-LOG.md known gaps). Kept as its own tool (not
    folded into get_scheme_details) per the original spec's note that this needs
    separate tone control -- disaster queries deserve a calmer, more direct answer
    register than a routine scheme lookup, which is a prompt-level concern for the
    agent, not something this retrieval call itself can enforce."""
    text = f"disaster relief crop loss compensation insurance: {query}"
    hits = _retriever().search(text, top_k=5)
    result = _format_hits(hits)
    result["query"] = text
    return result


def get_subsidy_details(query: str) -> dict:
    """RAG search shaped toward subsidy schemes (fertiliser, seed, mechanization,
    infrastructure, micro-irrigation -- all real concepts in the corpus). Same corpus
    as get_scheme_details, kept separate per the original spec since "subsidy"
    queries (a farmer asking "what money can I get for X equipment/input") are a
    distinct, common enough question shape to deserve its own named tool rather than
    relying on the agent to phrase a generic scheme query well."""
    text = f"subsidy: {query}"
    hits = _retriever().search(text, top_k=5)
    result = _format_hits(hits)
    result["query"] = text
    return result
