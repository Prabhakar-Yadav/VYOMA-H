"""Regression test for alias-tolerant district resolution (db.py, 2026-09-14).

Why this exists: real turns kept asking "which district?" after the farmer had named
one three times (Bangalore -> Shivamanga -> Shivamogga). Root cause: district lookup was
exact `LOWER()=` only, so colloquial/ASR spellings missed and silently fell back to the
state average -- while the answer still claimed district-specific detail.

Contract under test (fuzzy can only upgrade a fallback, never break a path):
  1. Aliases resolve to district cells (Bangalore->BENGALURU URBAN, Shivamanga/Shimoga->
     SHIVAMOGGA, Mysore->MYSURU), byte-equal to the canonical call.
  2. Garbage/weak input keeps the OLD behavior: state average when a state is given
     (equal to the state-only call), LocationNotFound otherwise -- never a new error.
  3. Cross-state collisions are state-scoped (AURANGABAD Bihar vs Maharashtra differ).
  4. describe_location() labels agree with the cells used.
  5. Canonical exact matches are untouched (full ground-truth suite stays in
     test_get_weather_data.py -- run that too).

Run: python test_district_resolution.py
     (needs full_weather.sqlite built first, same as test_get_weather_data.py)
"""
from __future__ import annotations

from db import DEFAULT_DB_PATH, LocationNotFound, describe_location, get_weather_data


def check(label: str, condition: bool) -> None:
    print(f"    {'OK' if condition else 'FAIL'}: {label}")
    assert condition, label


def main() -> None:
    print(f"DB: {DEFAULT_DB_PATH} ({DEFAULT_DB_PATH.stat().st_size / 1e9:.2f} GB)\n")
    kw = {"start_date": "2026-06-01", "end_date": "2026-06-03"}

    # --- 1. aliases resolve to district cells, equal to canonical ---
    print("=== aliases ===")
    for alias, canonical in [("Bangalore", "BENGALURU URBAN"), ("Shivamanga", "SHIVAMOGGA"),
                             ("Shimoga", "SHIVAMOGGA"), ("Mysore", "MYSURU")]:
        got = get_weather_data(district=alias, state="Karnataka", **kw)
        want = get_weather_data(district=canonical, state="Karnataka", **kw)
        check(f"{alias} -> {canonical} (same cells as canonical)", got == want and len(got) > 0)

    # --- 2. garbage keeps OLD behavior: state average, no new error ---
    print("\n=== fallback preserved ===")
    garbage = get_weather_data(district="Xyzabad", state="Karnataka", **kw)
    state_only = get_weather_data(state="Karnataka", **kw)
    check("unknown district + state == state-only call (old fallback)", garbage == state_only)
    try:
        get_weather_data(district="Xyzabad", **kw)
        check("unknown district alone raises LocationNotFound (old error)", False)
    except LocationNotFound:
        check("unknown district alone raises LocationNotFound (old error)", True)

    # --- 3. cross-state collisions are scoped, not averaged ---
    print("\n=== collisions ===")
    bih = get_weather_data(district="AURANGABAD", state="BIHAR", **kw)
    mah = get_weather_data(district="AURANGABAD", state="MAHARASHTRA", **kw)
    check("AURANGABAD Bihar vs Maharashtra differ (no cross-state averaging)", bih != mah)
    bih_state = get_weather_data(state="BIHAR", **kw)
    check("AURANGABAD Bihar == Bihar average (no cells there, honest fallback)", bih == bih_state)

    # --- 4. labels agree with cells ---
    print("\n=== labels ===")
    check("alias label names canonical district",
          describe_location(district="Bangalore", state="Karnataka") == "district=BENGALURU URBAN, KARNATAKA")
    check("garbage label says state average",
          describe_location(district="Xyzabad", state="Karnataka")
          == "state=Karnataka average (district 'Xyzabad' not matched)")
    check("label never raises", describe_location(district=None, state=None) == "location unknown")

    # --- 5. canonical exact matches untouched ---
    print("\n=== canonical ===")
    exact = get_weather_data(district="THRISSUR", state="KERALA", **kw)
    exact_only = get_weather_data(district="THRISSUR", **kw)
    check("canonical district+state == district-only (old semantics)", exact == exact_only)

    print("\nAll district-resolution checks passed.")


if __name__ == "__main__":
    main()
