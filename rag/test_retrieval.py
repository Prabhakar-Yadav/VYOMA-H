#!/usr/bin/env python3
"""Real retrieval test against the built g1/g2 sqlite-vec indexes. Not a unit test
suite (that's a follow-up once MIN_RELEVANCE is derived) -- this is the "does this
actually work, and what does the real relevance-score distribution look like" pass
that has to happen before any threshold gets picked.

Run: source venv/bin/activate && cd gramsahayak && python3 rag/test_retrieval.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag.retrieval import HybridRetriever

AGENTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

G1_QUERIES = [
    ("brown spots with rings on the lower leaves of my tomato", "tomato", "expect: tomato early blight"),
    ("small insects rasping leaves causing silvery streaks on chilli", None, "expect: chilli thrips / entomology"),
    ("how much mancozeb should I use per acre for potato", "potato", "expect: mancozeb treatment dose"),
    ("yellowing between veins, older leaves, looks like a nutrient problem", None, "expect: a deficiency concept"),
    ("safety precautions before spraying pesticide", None, "expect: safe-pesticide-handling"),
    ("purple elephant riding a bicycle", None, "expect: LOW relevance across the board (nonsense query)"),
]

G2_QUERIES = [
    ("how much money does PM-KISAN give and how often", None, "expect: pm-kisan"),
    ("crop insurance scheme for weather damage", None, "expect: pmfby"),
    ("loan for buying a tractor or farm equipment", None, "expect: kisan credit card or SMAM"),
    ("what is minimum support price", None, "expect: msp is NOT in g2 (it's G1 Practice Guidance) -- should NOT show up strongly"),
]


def run(name, queries):
    print(f"\n{'=' * 90}\n{name}\n{'=' * 90}")
    retriever = HybridRetriever(name.lower()[:2], AGENTS_DIR)
    all_relevances = []
    for query, crop, expectation in queries:
        t0 = time.perf_counter()
        hits = retriever.search(query, top_k=3, crop=crop)
        elapsed = time.perf_counter() - t0
        print(f"\nQuery: {query!r}  (crop filter={crop})  [{expectation}]")
        print(f"  {elapsed * 1000:.1f}ms")
        for h in hits:
            print(f"  relevance={h.relevance:.3f}  score={h.score:.4f}  "
                  f"{h.concept_id}#{h.heading}  (source_type={h.source_type})")
            all_relevances.append(h.relevance)
    return all_relevances


def main():
    g1_rel = run("G1 (plant/crop)", G1_QUERIES)
    g2_rel = run("G2 (gov schemes)", G2_QUERIES)

    all_rel = g1_rel + g2_rel
    print(f"\n{'=' * 90}\nRELEVANCE DISTRIBUTION (for deriving MIN_RELEVANCE later)\n{'=' * 90}")
    print(f"n={len(all_rel)}  min={min(all_rel):.3f}  max={max(all_rel):.3f}  "
          f"mean={sum(all_rel)/len(all_rel):.3f}")
    print(sorted(round(r, 3) for r in all_rel))


if __name__ == "__main__":
    main()
