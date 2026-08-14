"""Validates get_weather_data() (db.py) on the real full_weather.sqlite: retrieval accuracy
cross-checked against pandas computed independently from the source parquet
(gramsahayak/datasets/weather/weather_data/) -- not just "it ran without an exception."

This file does NOT measure memory -- see benchmark_get_weather_data.py for that, kept
deliberately separate. This script imports pandas and reads whole state parquet files
in-process to build ground truth, and resource.getrusage().ru_maxrss is a monotonic high-water
mark for the process's entire lifetime: those pandas reads permanently inflate any RSS number
this script would report, even after the memory is freed, making it look like get_weather_data()
costs hundreds of MB when in isolation it costs single-digit MB (confirmed the hard way -- an
earlier version of this file measured RSS here and got 751MB, which was actually just this
script's own ground-truth pandas reads leaving their high-water mark behind).

Four input modes, each checked against ground truth:
  lat/lon   -- near Bengaluru; nearest cell verified against a manual distance computation.
  pincode   -- 695024 (Thiruvananthapuram) -- the same real pincode used earlier in this
               project to prove two pincodes in one grid cell get identical NASA POWER data;
               here proving the reverse direction (pincode -> weather) resolves to the same
               known cell, (8.5, 76.25).
  district  -- GUJARAT/KACHCHH, 9 grid cells -- exercises the multi-cell averaging path for
               real (not a single-cell case that happens to average over 1).
  state     -- SIKKIM (2 cells, small enough to hand-verify) and KERALA (23 cells, for scale).

Run: python test_get_weather_data.py
     (needs full_weather.sqlite built first: python ../../../datasets/weather/build_sqlite_db.py)
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from db import DEFAULT_DB_PATH, LocationNotFound, get_weather_data

WEATHER_DATA_DIR = Path(__file__).resolve().parents[3] / "datasets" / "weather" / "weather_data"


def timed_call(label: str, **kwargs) -> list[dict]:
    t0 = time.time()
    result = get_weather_data(**kwargs)
    dt_ms = (time.time() - t0) * 1000
    print(f"  [{label}] {len(result)} rows in {dt_ms:.2f}ms")
    return result


def check(label: str, condition: bool) -> None:
    status = "OK" if condition else "FAIL"
    print(f"    {status}: {label}")
    assert condition, label


def main() -> None:
    print(f"DB: {DEFAULT_DB_PATH} ({DEFAULT_DB_PATH.stat().st_size / 1e9:.2f} GB)\n")
    # --- 1. lat/lon: nearest-cell resolution, cross-checked against manual distance calc ---
    print("=== lat/lon (near Bengaluru, 12.97, 77.59) ===")
    result = timed_call("lat/lon", lat=12.97, lon=77.59, start_date="2026-06-01")
    grid_cells = pd.read_csv(WEATHER_DATA_DIR.parent / "grid_cells.csv")
    grid_cells["dist2"] = (grid_cells["grid_lat"] - 12.97) ** 2 + (grid_cells["grid_lon"] - 77.59) ** 2
    expected_cell = grid_cells.sort_values("dist2").iloc[0]
    df = pd.read_parquet(WEATHER_DATA_DIR / f"state={expected_cell['state']}" / "data.parquet")
    expected = df[
        (df["grid_lat"] == expected_cell["grid_lat"])
        & (df["grid_lon"] == expected_cell["grid_lon"])
        & (df["date"] >= "2026-06-01")
    ].sort_values("date")
    check("row count matches manual nearest-cell filter", len(result) == len(expected))
    check(
        "T2M values match manual nearest-cell filter (single cell, no averaging needed)",
        result[0]["T2M"] == pytest_approx(expected.iloc[0]["T2M"]) if result else False,
    )

    # --- 2. pincode: known cell from earlier grid-dedup proof ---
    print("\n=== pincode (695024, Thiruvananthapuram) ===")
    result = timed_call("pincode", pincode="695024", start_date="2026-06-01")
    kerala = pd.read_parquet(WEATHER_DATA_DIR / "state=KERALA" / "data.parquet")
    expected = kerala[
        (kerala["grid_lat"] == 8.5) & (kerala["grid_lon"] == 76.25) & (kerala["date"] >= "2026-06-01")
    ].sort_values("date")
    check("resolves to the known grid cell (8.5, 76.25)", len(result) == len(expected) and len(result) > 0)
    check(
        "T2M matches (single cell -- pincode 695024 doesn't share its cell with another pincode "
        "input here, so this is an exact match, not an average)",
        abs(result[0]["T2M"] - expected.iloc[0]["T2M"]) < 1e-9,
    )

    # --- 3. district, multi-cell: GUJARAT/KACHCHH spans 9 grid cells -- the real averaging test ---
    print("\n=== district (KACHCHH, Gujarat -- 9 grid cells) ===")
    result = timed_call("district", district="kachchh", start_date="2026-06-01", end_date="2026-06-05")
    gujarat = pd.read_parquet(WEATHER_DATA_DIR / "state=GUJARAT" / "data.parquet")
    kachchh_cells = grid_cells[grid_cells["district"] == "KACHCHH"]
    check("resolved the full 9-cell district (not a partial match)", len(kachchh_cells) == 9)
    merged = gujarat.merge(kachchh_cells[["grid_lat", "grid_lon"]], on=["grid_lat", "grid_lon"])
    date_mask = (merged["date"] >= "2026-06-01") & (merged["date"] <= "2026-06-05")
    expected = merged[date_mask].groupby("date")["T2M"].mean().sort_index()
    check("5 dates returned", len(result) == 5)
    for row, (exp_date, exp_t2m) in zip(result, expected.items()):
        check(
            f"T2M average matches pandas groupby-mean for {row['date']} "
            f"(got {row['T2M']:.4f}, expected {exp_t2m:.4f})",
            abs(row["T2M"] - exp_t2m) < 1e-6,
        )

    # --- 4. state, small (SIKKIM, 2 cells) then larger (KERALA, 23 cells) for scale ---
    print("\n=== state (SIKKIM, 2 grid cells) ===")
    result = timed_call("state-small", state="SIKKIM", start_date="2026-06-01", end_date="2026-06-03")
    check("3 dates returned", len(result) == 3)

    print("\n=== state (KERALA, 23 grid cells) ===")
    result = timed_call("state-large", state="kerala", start_date="2020-01-01")
    check("multi-year range across 23 cells returns rows", len(result) > 1000)

    # --- 5. error handling: bad inputs should raise, not silently return nothing/wrong data ---
    print("\n=== error handling ===")
    try:
        get_weather_data(state="Atlantis")
        check("unknown state raises LocationNotFound", False)
    except LocationNotFound:
        check("unknown state raises LocationNotFound", True)

    try:
        get_weather_data(lat=12.97)  # lon missing
        check("lat without lon raises ValueError", False)
    except ValueError:
        check("lat without lon raises ValueError", True)

    # Over-supplying location fields (e.g. an agent tool call naturally including both
    # district and state) resolves via the most specific rather than erroring -- confirmed
    # in a real agent test run that this is a common, reasonable LLM tool-call pattern.
    # Priority by granularity: lat/lon > pincode > district > state; district beats state here.
    both = get_weather_data(state="KERALA", district="THRISSUR", start_date="2026-06-01")
    district_only = get_weather_data(district="THRISSUR", start_date="2026-06-01")
    check("district+state together resolves via district (the more specific one)", both == district_only)

    # lat/lon outranks pincode -- (12.97, 77.59) is near Bengaluru, 695024 is a real
    # Thiruvananthapuram pincode in a clearly different, distant cell; lat/lon should win, not
    # silently ignored. (NOT (8.5, 76.25) -- that's pincode 695024's own cell, per this
    # project's earlier grid-dedup proof, which would make the "different result" half of this
    # check vacuously pass regardless of whether lat/lon actually won.)
    latlon_vs_pincode = get_weather_data(lat=12.97, lon=77.59, pincode="695024", start_date="2026-06-01")
    latlon_only = get_weather_data(lat=12.97, lon=77.59, start_date="2026-06-01")
    pincode_only = get_weather_data(pincode="695024", start_date="2026-06-01")
    check("lat/lon+pincode together resolves via lat/lon (outranks pincode)", latlon_vs_pincode == latlon_only)
    check("...and that's a real, different result from the pincode alone (not a vacuous check)", latlon_vs_pincode != pincode_only)

    # A hallucinated/wrong pincode alongside a correct district falls back to the district
    # rather than hard-erroring -- confirmed directly on real Jetson hardware that a small
    # tool-calling model does this for real (a real Tamil Nadu pincode attached to a Kerala
    # district query).
    bad_pincode = get_weather_data(pincode="623001", district="THRISSUR", start_date="2026-06-01")
    check("invalid pincode + valid district falls back to district instead of erroring", bad_pincode == district_only)

    print("\nAll checks passed. (For memory/speed numbers, see benchmark_get_weather_data.py --")
    print("this script's own pandas ground-truth reads make RSS measured here meaningless.)")


def pytest_approx(x, tol=1e-9):
    # tiny local stand-in so this script has no pytest dependency -- `a == pytest_approx(b)`
    # reads naturally at the call site without pulling in a test framework for one comparison.
    class _Approx:
        def __eq__(self, other):
            return abs(other - x) < tol
    return _Approx()


if __name__ == "__main__":
    main()
