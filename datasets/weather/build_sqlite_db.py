"""Build the single SQLite file the agent's weather tools actually query at runtime, from the
parquet weather_data/ produced by fetch_weather_history.py + build_grid_cells.py.

Why SQLite, not parquet/DuckDB, for runtime serving: benchmarked on both this dev machine and
the actual Jetson Orin 8GB deployment target (see DEPLOYMENT.md for full numbers and method).
Summary from the Jetson: an indexed point lookup ("this location's last N days") against the
*full* 7.4M-row, 2.9GB nationwide SQLite file used 9.4MB peak RSS and took ~1ms -- identical to
querying a single 66MB state file, because SQLite only touches the index pages and rows a query
actually needs, not the whole file. The same lookup via DuckDB-on-parquet (predicate pushdown)
used 156MB and 680ms; naive pandas (load the whole state file, filter in memory) used 297MB.
DuckDB/pandas/pyarrow remain useful for the one-time build below (this script, run somewhere
memory isn't scarce) -- the Jetson-side runtime tool code needs nothing but the `sqlite3`
stdlib module to query the result.

Three tables:
  daily_weather  -- every (grid cell, date) row from weather_data/, indexed on
                    (grid_lat, grid_lon, date). This is the full raw history, not a derived
                    climatology table -- deliberately: this pass is data loading only, no
                    aggregation logic baked in yet, so tool-specific rollups (this-year-vs-
                    normal, N-day expected rainfall, etc.) can be decided and iterated on
                    later without re-running this build.
  pincode_grid   -- pincode_grid_mapping.parquet's Pincode -> grid_lat/grid_lon/StateName/
                    District, indexed on Pincode. Lets a tool resolve a farmer's pincode to a
                    weather row without ever touching pandas/parquet at runtime.
  grid_cells     -- grid_cells.csv verbatim (987 rows: grid_lat, grid_lon, state, district,
                    n_pincodes), no index needed -- it exists purely so a lat/lon nearest-
                    neighbor lookup (weather_tools/db.py's get_weather_data) scans 987 tiny
                    rows instead of DISTINCT-ing over daily_weather's 7.4M or even
                    pincode_grid's 20K.

Usage:
    python build_sqlite_db.py                    # reads ./weather_data + ./pincode_grid_mapping.parquet
                                                   # writes ./full_weather.sqlite (~2.9GB, ~7.4M rows
                                                   # for the current full nationwide fetch)

Deploy: copy the resulting full_weather.sqlite to the target device (scp/rsync) -- it's a
single self-contained file, nothing else needs to travel with it. See DEPLOYMENT.md.
"""
from __future__ import annotations

import argparse
import sqlite3
import time
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
WEATHER_DATA_DIR = HERE / "weather_data"
PINCODE_MAPPING = HERE / "pincode_grid_mapping.parquet"
GRID_CELLS_CSV = HERE / "grid_cells.csv"
OUTPUT_DB = HERE / "full_weather.sqlite"


def build(
    weather_data_dir: Path = WEATHER_DATA_DIR,
    pincode_mapping: Path = PINCODE_MAPPING,
    grid_cells_csv: Path = GRID_CELLS_CSV,
    output_db: Path = OUTPUT_DB,
) -> None:
    if not weather_data_dir.exists():
        raise FileNotFoundError(f"{weather_data_dir} not found -- run fetch_weather_history.py first.")
    if not pincode_mapping.exists():
        raise FileNotFoundError(f"{pincode_mapping} not found -- run build_grid_cells.py first.")
    if not grid_cells_csv.exists():
        raise FileNotFoundError(f"{grid_cells_csv} not found -- run build_grid_cells.py first.")

    state_files = sorted(weather_data_dir.glob("state=*/data.parquet"))
    if not state_files:
        raise FileNotFoundError(f"No state=*/data.parquet files under {weather_data_dir}.")

    t0 = time.time()
    con = sqlite3.connect(output_db)
    total_rows = 0
    for i, f in enumerate(state_files):
        df = pd.read_parquet(f)
        df["date"] = df["date"].astype(str)  # SQLite has no native date type; store as ISO text
        df.to_sql("daily_weather", con, if_exists="replace" if i == 0 else "append", index=False)
        total_rows += len(df)
        print(f"  {f.parent.name}: +{len(df)} rows ({total_rows} total)")
    con.execute("CREATE INDEX idx_cell_date ON daily_weather(grid_lat, grid_lon, date)")
    print(f"daily_weather: {total_rows} rows in {time.time() - t0:.1f}s")

    t1 = time.time()
    mapping = pd.read_parquet(pincode_mapping)
    mapping.to_sql("pincode_grid", con, if_exists="replace", index=False)
    con.execute("CREATE INDEX idx_pincode ON pincode_grid(Pincode)")
    print(f"pincode_grid: {len(mapping)} rows in {time.time() - t1:.2f}s")

    t2 = time.time()
    grid = pd.read_csv(grid_cells_csv)
    grid.to_sql("grid_cells", con, if_exists="replace", index=False)
    print(f"grid_cells: {len(grid)} rows in {time.time() - t2:.2f}s")

    con.commit()
    con.close()
    print(f"Done in {time.time() - t0:.1f}s total -> {output_db} ({output_db.stat().st_size / 1e9:.2f} GB)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--weather-data-dir", type=Path, default=WEATHER_DATA_DIR)
    ap.add_argument("--pincode-mapping", type=Path, default=PINCODE_MAPPING)
    ap.add_argument("--grid-cells-csv", type=Path, default=GRID_CELLS_CSV)
    ap.add_argument("--output", type=Path, default=OUTPUT_DB)
    args = ap.parse_args()
    build(args.weather_data_dir, args.pincode_mapping, args.grid_cells_csv, args.output)


if __name__ == "__main__":
    main()
