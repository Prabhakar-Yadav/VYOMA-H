"""Look up pesticide records from the scraped FSSAI dataset by name.

Tries, in order: exact match, substring match, then fuzzy match (stdlib
difflib — no extra dependency needed for ~283 names).
"""

import difflib
import json
from functools import lru_cache
from pathlib import Path

# Self-contained within this package (gramsahayak/datasets/json/pesticides.json) rather than
# reaching into the wider blue-parrot repo's own datasets/ -- gramsahayak/ is meant to be
# copyable/shareable on its own (see gramsahayak/README.md), so it carries its own copy of
# the real FSSAI data this tool needs instead of depending on a sibling folder that may not
# exist wherever this package ends up. parents[2]: tools/ -> agent/ -> gramsahayak/ (this
# file is gramsahayak/agent/tools/pesticide_lookup.py).
DEFAULT_JSON_PATH = Path(__file__).resolve().parents[2] / "datasets" / "json" / "pesticides.json"


@lru_cache(maxsize=8)
def _load(json_path: str) -> list[dict]:
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_pesticide(name: str, json_path: str | Path = DEFAULT_JSON_PATH, n: int = 1):
    """Find the pesticide record(s) whose name best matches `name`.

    Returns a single record dict (or None if nothing matches) when n == 1,
    otherwise a list of up to n record dicts ordered by match quality.
    """
    records = _load(str(json_path))
    query = name.strip().lower()

    exact = [r for r in records if r["pesticide"].strip().lower() == query]
    if exact:
        return exact[0] if n == 1 else exact[:n]

    substring = [r for r in records if query in r["pesticide"].lower()]
    if substring:
        substring.sort(key=lambda r: len(r["pesticide"]))
        return substring[0] if n == 1 else substring[:n]

    names = [r["pesticide"] for r in records]
    close = difflib.get_close_matches(name, names, n=n, cutoff=0.4)
    if not close:
        return None if n == 1 else []

    by_name = {r["pesticide"]: r for r in records}
    matches = [by_name[c] for c in close]
    return matches[0] if n == 1 else matches


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python pesticide_lookup.py <pesticide name>")
        raise SystemExit(1)

    result = find_pesticide(" ".join(sys.argv[1:]))
    print(json.dumps(result, indent=2) if result else "No match found.")
