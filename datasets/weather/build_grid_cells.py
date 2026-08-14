"""Turn the India Post pincode -> lat/lon table (pincode_with_lat-long.csv) into the two
tables the rest of this pipeline needs. No network calls -- pure pandas, finishes in seconds.

Why this exists: NASA POWER's underlying reanalysis grid is ~0.5 deg lat x 0.625 deg lon
(roughly 50-60km cells) -- two pincodes in the same cell get back byte-for-byte identical
weather (verified empirically: pincodes 695313 and 695024 in Thiruvananthapuram, 34km apart,
same grid cell, identical PRECTOTCORR/T2M down to the last decimal). India Post lists ~20,300
distinct pincodes nationwide; fetching NASA POWER once per pincode would be ~20,300 requests
for data that only actually contains ~1,000 distinct series. Snapping every pincode to its
grid cell first and fetching once per *cell* gets the same coverage for ~5% of the requests.

Outputs:
  1. pincode_grid_mapping.parquet -- every valid pincode with its grid cell (grid_lat, grid_lon).
     The lookup table: given a farmer's pincode, join here to find which grid cell's weather
     applies, then join that into weather_history.parquet.
  2. grid_cells.csv -- the deduplicated list of unique grid cells to actually fetch from NASA
     POWER. fetch_weather_history.py reads this (it replaced the old hand-picked locations.csv).

Run once, or re-run whenever pincode_with_lat-long.csv is refreshed:
    python build_grid_cells.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
PINCODE_CSV = HERE / "pincode_with_lat-long.csv"
MAPPING_OUT = HERE / "pincode_grid_mapping.parquet"
GRID_CELLS_OUT = HERE / "grid_cells.csv"

# NASA POWER's native grid for these parameters (MERRA-2 based): ~0.5 deg lat x 0.625 deg lon,
# confirmed by inspecting the `regional` endpoint's own returned grid-point spacing. This is
# used only to decide which pincodes share a weather series -- fetch_weather_history.py queries
# each cell's own center point and POWER snaps internally regardless of exact coordinate, so
# this doesn't need to match POWER's grid to sub-degree precision, only to be a consistent,
# non-overlapping bucket.
GRID_LAT_STEP = 0.5
GRID_LON_STEP = 0.625

# Loose India bounding box -- drops the null/zero-filled and clearly-wrong rows that show up
# in the raw India Post extract (~5-6% of rows) without needing a stricter per-state check.
INDIA_LAT_RANGE = (6.0, 38.0)
INDIA_LON_RANGE = (68.0, 98.0)


def build() -> None:
    df = pd.read_csv(PINCODE_CSV, dtype={"Pincode": str}, low_memory=False)
    df["lat"] = pd.to_numeric(df["Latitude"], errors="coerce")
    df["lon"] = pd.to_numeric(df["Longitude"], errors="coerce")

    before = len(df)
    df = df[
        df["lat"].notna()
        & df["lat"].between(*INDIA_LAT_RANGE)
        & df["lon"].between(*INDIA_LON_RANGE)
    ]
    print(f"Dropped {before - len(df)} rows with missing/out-of-range coordinates "
          f"({before} -> {len(df)})")

    # India Post lists multiple post offices per pincode; collapse to one row per pincode,
    # averaging their coordinates.
    pin = (
        df.groupby(["StateName", "District", "Pincode"], as_index=False)
          .agg(lat=("lat", "mean"), lon=("lon", "mean"))
    )
    pin["grid_lat"] = (pin["lat"] / GRID_LAT_STEP).round() * GRID_LAT_STEP
    pin["grid_lon"] = (pin["lon"] / GRID_LON_STEP).round() * GRID_LON_STEP
    pin.to_parquet(MAPPING_OUT, index=False)
    print(f"Wrote {len(pin)} pincode -> grid-cell mappings to {MAPPING_OUT.name}")

    # One row per unique grid cell, with a representative state/district (the most common
    # pincode source in that cell) purely for readable logging in fetch_weather_history.py --
    # a cell can straddle more than one district; the weather series itself doesn't care.
    grid = (
        pin.groupby(["grid_lat", "grid_lon"])
           .agg(
               state=("StateName", lambda s: s.mode().iat[0]),
               district=("District", lambda s: s.mode().iat[0]),
               n_pincodes=("Pincode", "nunique"),
           )
           .reset_index()
           .sort_values(["state", "district"])
    )
    grid.to_csv(GRID_CELLS_OUT, index=False)
    print(f"Wrote {len(grid)} unique grid cells to {GRID_CELLS_OUT.name}")
    print(f"Reduction: {len(pin)} pincodes -> {len(grid)} grid cells "
          f"({len(grid) / len(pin):.1%} of the API calls a naive per-pincode fetch would need)")


if __name__ == "__main__":
    build()
