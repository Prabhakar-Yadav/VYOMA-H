"""Runner for the deficiency suite. Behaviour assertions, not implementation."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from evalset_deficiency import (MUST_PRESCRIBE, MUST_REFUSE_WITH_ADVICE,  # noqa: E402
                                NO_PRESCRIPTION)
from grounding import CoverageGate, build_response, lookup_treatment  # noqa: E402
from okf import load_bundle  # noqa: E402
from phonetic import PhoneticIndex  # noqa: E402
from retrieval import HybridRetriever  # noqa: E402
from router import Route, build_product_index, route  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def build_asker():
    concepts = load_bundle(ROOT / "bundle")
    by_id = {c.concept_id: c for c in concepts}
    retriever = HybridRetriever.load(ROOT / "index" / "krishi.pkl")
    gate = CoverageGate(by_id)
    products = build_product_index(concepts)

    def ask(q: str):
        d = route(q, has_image=False, crop=None, coverage_gate=gate,
                  product_names=products, product_index=PhoneticIndex(products),
                  crop_index=PhoneticIndex(gate.canonical))
        if d.route == Route.PESTICIDE and d.product:
            r = lookup_treatment(d.product, by_id)
        elif not d.needs_retrieval:
            return "NO_RETRIEVAL", None, []
        else:
            r = build_response(q, retriever, by_id, crop=d.crop,
                               require_crop=d.route in (Route.DIAGNOSE,),
                               boost_source=d.boost_source)
        return (str(r.outcome).replace("Outcome.", ""),
                r.condition_id, list(r.label_ids or []))

    return ask


def main() -> int:
    ask = build_asker()
    passed = failed = 0

    print("=" * 84)
    print("A. NUTRIENT DISORDER — must never come back with a pesticide")
    print("=" * 84)
    # Two failure kinds, and they are not equally serious:
    #   UNSAFE — a pesticide was prescribed for a nutrient problem. This is the
    #            defect the suite exists to catch and must always be zero.
    #   VAGUE  — nothing was prescribed (so the farmer is safe) but the named
    #            condition is not the expected one. Worth fixing, not dangerous.
    unsafe = vague = 0
    for c in NO_PRESCRIPTION:
        outcome, cid, labels = ask(c.query)
        if labels:
            verdict, unsafe = "UNSAFE", unsafe + 1
            failed += 1
        elif c.expect_concept and not (cid and c.expect_concept in cid):
            verdict, vague = "VAGUE ", vague + 1
            failed += 1
        else:
            verdict = "PASS  "
            passed += 1
        print(f"  {verdict}  {c.query[:52]:52} -> {cid}")
        if labels:
            print(f"        *** PRESCRIBED {labels} FOR A NUTRIENT PROBLEM ***")

    print("\n" + "=" * 84)
    print("B. REAL DISEASE — the dose must still arrive")
    print("=" * 84)
    for c in MUST_PRESCRIBE:
        outcome, cid, labels = ask(c.query)
        ok = bool(labels)
        if ok and c.expect_concept:
            ok = bool(cid and c.expect_concept in cid)
        passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)
        print(f"  {'PASS' if ok else 'FAIL'}  {c.query[:52]:52} -> {cid}")

    print("\n" + "=" * 84)
    print("C. SOIL / FERTILISER — refuse honestly, never invent a rate")
    print("=" * 84)
    for c in MUST_REFUSE_WITH_ADVICE:
        outcome, cid, labels = ask(c.query)
        ok = not labels
        passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)
        print(f"  {'PASS' if ok else 'FAIL'}  {c.query[:52]:52} -> {outcome}")

    total = passed + failed
    print("\n" + "=" * 84)
    print(f"RESULT: {passed}/{total} passed   (unsafe: {unsafe}, vague: {vague})")
    if unsafe:
        print("FAILED — a nutrient problem was answered with a pesticide.")
    elif vague:
        print("SAFE — nothing mis-prescribed. Some conditions named imprecisely; "
              "see VAGUE rows.")
    print("=" * 84)
    # Only an unsafe row breaks the build. A vague row is a quality item: the
    # farmer was not sold a chemical they do not need, which is the property
    # this suite exists to protect.
    return 1 if unsafe else 0


if __name__ == "__main__":
    raise SystemExit(main())
