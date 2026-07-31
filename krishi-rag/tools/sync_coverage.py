# -*- coding: utf-8 -*-
"""Sync coverage.md against the disease concepts that actually exist.

Any crop with at least one Pest/Disease concept belongs in `covered_crops`.
Leaving it in `uncovered_crops` makes the gate refuse a crop we can diagnose —
which is how 37 of 93 test cases failed after the corpus expansion.

The reverse error is the dangerous one and this script never makes it: a crop is
only promoted when concepts for it exist.
"""

import io
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from okf import load_bundle

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
COVERAGE = os.path.join(ROOT, "bundle", "crops", "coverage.md")


def main():
    concepts = load_bundle(os.path.join(ROOT, "bundle"))
    diagnosable = {
        c.crop for c in concepts
        if c.type in ("Pest", "Disease") and c.crop
    }
    print(f"crops with concepts: {len(diagnosable)}")

    text = io.open(COVERAGE, encoding="utf-8").read()
    covered_block = re.search(r"covered_crops:\n(.*?)\nuncovered_crops:", text, re.S).group(1)
    uncovered_block = re.search(r"uncovered_crops:\n(.*?)\nsources:", text, re.S).group(1)

    already = set(re.findall(r"^  (\w[\w ]*?):", covered_block, re.M))
    promote = sorted(diagnosable - already)
    if not promote:
        print("nothing to promote — coverage is in sync")
        return 0

    # Pull each promoted crop's alias line out of uncovered and rewrite it as a
    # covered entry keyed on its canonical name.
    moved, remaining = [], []
    for line in uncovered_block.split("\n"):
        stripped = line.strip()
        if not stripped.startswith("- ["):
            remaining.append(line)
            continue
        aliases = [a.strip() for a in stripped[3:].rstrip("]").split(",")]
        canon = next((p for p in promote if p in aliases), None)
        if canon:
            moved.append(f"  {canon}: [{', '.join(aliases)}]")
        else:
            remaining.append(line)

    if moved:
        text = text.replace(
            "covered_crops:\n" + covered_block,
            "covered_crops:\n" + covered_block.rstrip("\n") + "\n" + "\n".join(moved),
        )
        text = text.replace(
            "uncovered_crops:\n" + uncovered_block,
            "uncovered_crops:\n" + "\n".join(l for l in remaining if l.strip()),
        )

    n_cov = len(already) + len(moved)
    text = re.sub(r"Currently \*\*\d+ crops diagnosable, \d+ recognised\*\*\.",
                  f"Currently **{n_cov} crops diagnosable, 63 recognised**.", text)

    io.open(COVERAGE, "w", encoding="utf-8").write(text)
    for m in moved:
        print("  promoted:", m.strip().split(":")[0])
    print(f"\ncovered_crops now: {n_cov}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
