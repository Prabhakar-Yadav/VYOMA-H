"""Krishi RAG command line interface.

    python src/cli.py build                      # build the index
    python src/cli.py ask "leaves yellow, white flies underneath"
    python src/cli.py ask "..." --crop cotton    # crop pre-filter from the VLM
    python src/cli.py eval                       # run the test suite
    python src/cli.py stats                      # bundle overview
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from chunking import chunk_bundle
from grounding import Outcome, build_response
from okf import load_bundle
from retrieval import HybridRetriever

ROOT = Path(__file__).resolve().parent.parent
BUNDLE = ROOT / "bundle"
INDEX = ROOT / "index" / "krishi.pkl"


def _load_all():
    concepts = load_bundle(BUNDLE)
    return concepts, {c.concept_id: c for c in concepts}


def cmd_build(args) -> int:
    concepts, _ = _load_all()
    print(f"Loaded {len(concepts)} concepts from {BUNDLE}")

    chunks = chunk_bundle(concepts)
    print(f"Produced {len(chunks)} chunks")

    retriever = HybridRetriever(chunks)
    start = time.time()
    retriever.build()
    retriever.save(INDEX)
    print(f"\nIndex saved to {INDEX}  ({time.time() - start:.1f}s)")
    return 0


def _print_response(resp, elapsed_ms: float, show_debug: bool) -> None:
    icon = {
        Outcome.GROUNDED: "[GROUNDED]",
        Outcome.ABSTAINED_LOW_CONF: "[ABSTAIN: low confidence]",
        Outcome.ABSTAINED_NO_LABEL: "[ABSTAIN: no label record]",
        Outcome.ABSTAINED_AMBIGUOUS: "[ABSTAIN: ambiguous]",
        Outcome.ABSTAINED_OUT_OF_COVERAGE: "[ABSTAIN: crop not covered]",
        Outcome.ABSTAINED_TOO_VAGUE: "[ABSTAIN: not enough detail]",
        Outcome.ABSTAINED_NO_CROP: "[ABSTAIN: crop not identified]",
        Outcome.HEALTHY: "[HEALTHY]",
        Outcome.OUT_OF_SCOPE: "[OUT OF SCOPE]",
        Outcome.GUIDELINE: "[GUIDELINE]",
        Outcome.EMERGENCY: "[EMERGENCY]",
    }.get(resp.outcome, f"[{resp.outcome.value}]")

    print(f"\n{icon}")
    if resp.condition:
        print(f"  condition   : {resp.condition}")
    if resp.runner_up:
        print(f"  runner-up   : {resp.runner_up}")
    print(f"  confidence  : {resp.confidence:.5f}")
    if resp.trust_tier:
        print(f"  trust tier  : {resp.trust_tier}")
    if resp.label_ids:
        print(f"  label_ids   : {', '.join(resp.label_ids)}")
    print(f"  safe to speak: {resp.is_safe_to_speak}")
    print(f"  retrieval    : {elapsed_ms:.0f} ms")

    print(f"\n  SPOKEN >> {resp.spoken_text}")

    if resp.treatments:
        print("\n  Retrieved label records:")
        for t in resp.treatments:
            print(f"    - {t['title']}  [{t['label_id']}]")
            print(
                f"        {t['dilution_per_litre']}/L | {t['dose_per_acre']}/acre "
                f"| PHI {t['phi_days']}d | {t['toxicity_triangle']} triangle"
            )

    if show_debug:
        print("\n  debug:")
        print("   ", json.dumps(resp.debug, indent=4, default=str).replace("\n", "\n    "))


def cmd_ask(args) -> int:
    if not INDEX.exists():
        print(f"No index at {INDEX}. Run: python src/cli.py build", file=sys.stderr)
        return 1

    concepts, by_id = _load_all()
    retriever = HybridRetriever.load(INDEX)

    # Route before retrieving. No model call — crop names and product names are
    # exact lists, so the decision is deterministic and free.
    from grounding import CoverageGate
    from phonetic import CONFIDENT, PhoneticIndex
    from router import Route, build_product_index, route

    gate = CoverageGate(by_id)
    products = build_product_index(concepts)
    decision = route(
        args.query,
        has_image=args.image,
        crop=args.crop,
        coverage_gate=gate,
        product_names=products,
        product_index=PhoneticIndex(products),
        crop_index=PhoneticIndex(gate.canonical),
    )
    print(f"\n  route       : {decision.route.value}  ({decision.reason})")

    # Deferral is the strict default on an uncertain entity match. A guessed
    # crop or product leads to a real dose for the wrong thing, so anything
    # short of high confidence asks the farmer to confirm instead of proceeding.
    if decision.entity_confidence < CONFIDENT and decision.heard_as:
        print("  [DEFER]     : heard '{}' but only {:.0%} sure".format(
            decision.heard_as, decision.entity_confidence))
        print("\n  SPOKEN >> I think you said {}, but I am not certain. "
              "Please say the name again, or show this to your Krishi Vigyan "
              "Kendra.".format(decision.heard_as))
        return 0

    # A named product is answered by exact lookup, never by search.
    if decision.route == Route.PESTICIDE and decision.product:
        from grounding import lookup_treatment
        start = time.time()
        resp = lookup_treatment(decision.product, by_id)
        _print_response(resp, (time.time() - start) * 1000, args.debug)
        return 0

    if not decision.needs_retrieval:
        print("  -> the model may answer this directly; a wrong answer here is harmless.")
        return 0

    start = time.time()
    resp = build_response(
        args.query, retriever, by_id,
        crop=decision.crop or args.crop,
        require_crop=decision.route in (Route.DIAGNOSE,),
        boost_source=decision.boost_source,
    )
    elapsed = (time.time() - start) * 1000

    _print_response(resp, elapsed, args.debug)
    return 0


def cmd_stats(args) -> int:
    concepts, _ = _load_all()
    chunks = chunk_bundle(concepts)

    by_type: dict[str, int] = {}
    by_trust: dict[str, int] = {}
    for c in concepts:
        by_type[c.type] = by_type.get(c.type, 0) + 1
        by_trust[c.trust_tier] = by_trust.get(c.trust_tier, 0) + 1

    print(f"Bundle: {BUNDLE}")
    print(f"  concepts : {len(concepts)}")
    print(f"  chunks   : {len(chunks)}")
    print("\n  by type:")
    for k, v in sorted(by_type.items()):
        print(f"    {k:20s} {v}")
    print("\n  by trust tier (OKF 5.3):")
    for k, v in sorted(by_trust.items()):
        print(f"    {k:20s} {v}")

    treatments = [c for c in concepts if c.type == "Treatment"]
    missing = [c.concept_id for c in treatments if not c.label_id]
    print(f"\n  treatments with label_id : {len(treatments) - len(missing)}/{len(treatments)}")
    if missing:
        print(f"  MISSING label_id: {missing}")
        return 1

    conditions = [c for c in concepts if c.type in {"Pest", "Disease"}]
    orphans = [c.concept_id for c in conditions if not c.treatments]
    if orphans:
        print(f"  conditions with no linked treatment: {orphans}")
    return 0


def cmd_eval(args) -> int:
    from evalset import run_eval

    if not INDEX.exists():
        print(f"No index at {INDEX}. Run: python src/cli.py build", file=sys.stderr)
        return 1
    _, by_id = _load_all()
    retriever = HybridRetriever.load(INDEX)
    return run_eval(retriever, by_id, verbose=not args.quiet)


def cmd_eval100(args) -> int:
    import evalset100

    if not INDEX.exists():
        print(f"No index at {INDEX}. Run: python src/cli.py build", file=sys.stderr)
        return 1
    concepts, by_id = _load_all()
    retriever = HybridRetriever.load(INDEX)
    return evalset100.run(retriever, by_id, verbose=not args.quiet, concepts=concepts)


def main() -> int:
    parser = argparse.ArgumentParser(prog="krishi-rag")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("build", help="build the retrieval index").set_defaults(func=cmd_build)

    ask = sub.add_parser("ask", help="query the knowledge bundle")
    ask.add_argument("query")
    ask.add_argument("--crop", default=None, help="crop pre-filter (from the VLM)")
    ask.add_argument("--image", action="store_true",
                     help="a photo accompanied this query (forces crop diagnosis)")
    ask.add_argument("--debug", action="store_true")
    ask.set_defaults(func=cmd_ask)

    ev100 = sub.add_parser("eval100", help="run the 93-case cluster suite")
    ev100.add_argument("--quiet", action="store_true")
    ev100.set_defaults(func=cmd_eval100)

    sub.add_parser("stats", help="bundle overview and integrity check").set_defaults(
        func=cmd_stats
    )

    ev = sub.add_parser("eval", help="run the retrieval test suite")
    ev.add_argument("--quiet", action="store_true")
    ev.set_defaults(func=cmd_eval)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
