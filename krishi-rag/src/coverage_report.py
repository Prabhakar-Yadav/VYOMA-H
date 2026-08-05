"""Which conditions can produce a verified dose, and which cannot.

Written for the question Ishaan asked: how many diseases actually have a
verified treatment and dose record behind them. The honest answer is not one
number, because "no dose" splits into two very different cases:

  - a chemical exists and we simply have not recorded it yet  -> a data gap
  - no chemical can work (viruses, nutrient shortages)        -> correct as is

Lumping those together makes the corpus look worse than it is and hides the
work that actually needs doing.

    python src/coverage_report.py            # print
    python src/coverage_report.py --md FILE  # write markdown
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from grounding import non_chemical_advice          # noqa: E402
from okf import load_bundle                        # noqa: E402

BUNDLE = Path(__file__).resolve().parent.parent / "bundle"

# Conditions no spray can cure. Not a data gap - the right answer for these is
# vector control, roguing and resistant varieties, which the corpus already
# carries in its non-chemical sections.
INCURABLE = ("virus", "mosaic", "leaf-curl", "bunchy-top", "little-leaf",
             "greening", "sterility", "phytoplasma")


def classify(c):
    if c.treatments:
        return "has_dose"
    if c.type == "Deficiency":
        return "deficiency"        # deliberate: we hold no fertiliser doses
    if any(k in c.concept_id for k in INCURABLE):
        return "incurable"
    return "gap"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md")
    a = ap.parse_args()

    concepts = load_bundle(BUNDLE)
    cond = [c for c in concepts if c.type in ("Disease", "Pest", "Deficiency")]
    groups: dict[str, list] = {}
    for c in cond:
        groups.setdefault(classify(c), []).append(c)

    has = groups.get("has_dose", [])
    gap = groups.get("gap", [])
    inc = groups.get("incurable", [])
    dfc = groups.get("deficiency", [])
    advice = [c for c in cond if not c.treatments and non_chemical_advice(c)]

    L = []
    w = L.append
    w("# Treatment coverage")
    w("")
    w(f"**{len(has)} of {len(cond)} conditions carry a verified CIB&RC dose.**")
    w("")
    w("| | count | what the device says |")
    w("|---|---|---|")
    w(f"| Verified dose on record | **{len(has)}** | names the disease and gives the dose |")
    w(f"| No chemical can cure it | {len(inc)} | names it, gives vector control and roguing |")
    w(f"| Nutrient disorder | {len(dfc)} | names it, refuses to guess a fertiliser rate |")
    w(f"| **Dose missing, chemical exists** | **{len(gap)}** | names it, gives prevention, no dose |")
    w("")
    w(f"Of the {len(cond) - len(has)} without a dose, **{len(advice)} still give "
      "actionable non-chemical advice** rather than only a KVK referral.")
    w("")
    w("Only the last row is a data gap. The other two are correct behaviour: no")
    w("spray cures a virus, and we deliberately hold no fertiliser doses.")
    w("")

    w("## Verified dose on record")
    w("")
    w("| Condition | Label ID |")
    w("|---|---|")
    by_id = {c.concept_id: c for c in concepts}
    for c in sorted(has, key=lambda x: x.concept_id):
        ids = []
        for link in c.treatments:
            t = by_id.get(link[:-3] if link.endswith(".md") else link)
            if t:
                ids.append(t.frontmatter.get("label_id", "?"))
        w(f"| {c.title} | {', '.join(ids) or '?'} |")
    w("")

    w("## Dose missing — this is the work")
    w("")
    w("A registered chemical exists for each of these; we have not recorded it.")
    w("")
    w("| Condition | Has prevention advice? |")
    w("|---|---|")
    for c in sorted(gap, key=lambda x: x.concept_id):
        w(f"| {c.title} | {'yes' if non_chemical_advice(c) else 'NO'} |")
    w("")

    w("## No chemical cure — correct as is")
    w("")
    for c in sorted(inc, key=lambda x: x.concept_id):
        w(f"- {c.title}")
    w("")
    w("## Nutrient disorders — deliberately no dose")
    w("")
    for c in sorted(dfc, key=lambda x: x.concept_id):
        w(f"- {c.title}")

    out = "\n".join(L)
    if a.md:
        Path(a.md).write_text(out + "\n", encoding="utf-8")
        print(f"written to {a.md}")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
