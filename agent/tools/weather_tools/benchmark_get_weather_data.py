"""Pure memory/speed benchmark for get_weather_data() -- deliberately separate from
test_get_weather_data.py (correctness), because that script imports pandas and reads whole
state parquet files in-process to build ground truth, and resource.getrusage().ru_maxrss is a
monotonic high-water mark for the process's entire lifetime, not current usage -- one big
pandas read early on permanently inflates every RSS number reported for the rest of that
process, even after the memory is freed. This file imports nothing but db.py (sqlite3-only, no
pandas/pyarrow) so its RSS numbers are actually representative of runtime tool-call cost.

Run: python benchmark_get_weather_data.py
"""
from __future__ import annotations

import resource
import time

from db import get_weather_data


def peak_rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def run(label: str, **kwargs) -> None:
    t0 = time.time()
    result = get_weather_data(**kwargs)
    dt_ms = (time.time() - t0) * 1000
    print(f"  [{label}] {len(result)} rows in {dt_ms:.2f}ms, cumulative peak RSS {peak_rss_mb():.1f} MB")


def main() -> None:
    print(f"Interpreter baseline (no query yet): {peak_rss_mb():.1f} MB\n")

    print("=== single calls, one per mode ===")
    run("lat/lon (Bengaluru)", lat=12.97, lon=77.59, start_date="2026-06-01")
    run("pincode (695024)", pincode="695024", start_date="2026-06-01")
    run("district, 9-cell (KACHCHH)", district="kachchh", start_date="2026-06-01")
    run("state, 2-cell (SIKKIM)", state="SIKKIM", start_date="2026-01-01")
    run("state, 23-cell (KERALA), full 20yr history", state="KERALA")
    run("state, 55-cell (ANDHRA PRADESH), full 20yr history", state="ANDHRA PRADESH")

    print("\n=== 50 repeated calls, mixed modes+states -- does RSS grow across a long-lived agent process? ===")
    before = peak_rss_mb()
    modes = [
        dict(pincode="695024", start_date="2026-01-01"),
        dict(state="GOA", start_date="2026-01-01"),
        dict(district="kachchh", start_date="2026-01-01"),
        dict(lat=19.07, lon=72.87, start_date="2026-01-01"),  # Mumbai-ish
        dict(state="KERALA", start_date="2026-06-01"),
    ]
    t0 = time.time()
    for i in range(50):
        get_weather_data(**modes[i % len(modes)])
    total_ms = (time.time() - t0) * 1000
    after = peak_rss_mb()
    print(f"  50 calls in {total_ms:.1f}ms ({total_ms/50:.2f}ms/call avg)")
    print(f"  peak RSS before: {before:.1f} MB, after: {after:.1f} MB (delta: {after - before:+.1f} MB)")

    print(f"\nFinal peak RSS: {peak_rss_mb():.1f} MB")


if __name__ == "__main__":
    main()
