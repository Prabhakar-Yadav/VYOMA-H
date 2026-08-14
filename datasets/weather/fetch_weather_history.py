"""Bulk-fetch N years of NASA POWER daily weather for every grid cell in grid_cells.csv and
save the result as a state-partitioned dataframe ("database") on disk -- the raw table that
daily_climatology / anomaly_thresholds get derived from for the weather tools in
gramsahayak/agent/tools/ (see gramsahayak/agent/agent.py's MOCK query_harvest_weather_risk
and friends for the tools this is meant to eventually back for real).

grid_cells.csv comes from build_grid_cells.py, which snaps every pincode in
pincode_with_lat-long.csv (India Post's full pincode list) to the NASA POWER grid cell it
falls in and dedupes -- ~20,300 pincodes collapse to ~987 grid cells nationwide, since POWER's
underlying resolution is ~0.5deg x 0.625deg (~50-60km) and two pincodes in the same cell return
identical weather. Run that script first if grid_cells.csv doesn't exist yet.

The `point` endpoint has no multi-year date-range limit (confirmed empirically: a 10-year pull
for one point returns in ~1 second) but it does cap at 20 parameters per request (also
confirmed empirically, via a 422 error). DEFAULT_PARAMETERS has grown to 35 -- deliberately, so
this pipeline only has to run its one full historical pull once instead of needing a second
pass later for whatever a future tool turns out to want -- so nasa_power_client.fetch_point_daily()
transparently splits each cell's request into 2 batched calls and merges them. That means
this script makes **~1,974 requests total** (987 cells x 2 batches), not ~987.

Usage:
    python fetch_weather_history.py                  # last 10 years, all ~987 grid cells,
                                                       # every state (~1,974 requests total --
                                                       # 2 per cell, 35 params split into
                                                       # 20+15; budget 40-55 min at the
                                                       # default 1 req/sec pace)
    python fetch_weather_history.py --years 5
    python fetch_weather_history.py --state KERALA    # one state only, for a quick smoke test
                                                       # (matches grid_cells.csv's `state`
                                                       # column, which is upper-cased India
                                                       # Post style)

Saved incrementally, one state at a time -- not just once at the very end. A ~45-minute run
covering 25+ states means a crash, a NASA POWER outage, or hitting some undocumented rate limit
partway through would otherwise lose everything; instead, each state's data.parquet/.csv lands
on disk as soon as that state's cells finish, so weather_data/ itself shows you exactly which
states are done and which remain if a run stops early -- just look at what folders exist. Two
layers of resumability stack on top of that:
  - Per-cell: cache/<grid_lat>_<grid_lon>_<start>_<end>_<params_hash>.parquet, written the first
    time a cell is fetched successfully. Re-running skips whatever's already cached.
  - Per-state: weather_data/state=<STATE>/data.parquet, (re)written once all of that state's
    cells are in hand. A state whose folder already has today's data isn't refetched at all --
    see --force below to override that.
Changing --years, or editing DEFAULT_PARAMETERS in nasa_power_client.py, changes the per-cell
cache filename, so a rerun can't silently reuse a shorter date range or a narrower column set
as if it were fresh -- it just fetches fresh under the new cache key (and rewrites that state's
partition once the new data is in).

    python fetch_weather_history.py --force           # re-fetch + rewrite every state's
                                                        # partition even if already present
                                                        # (per-cell cache is still honored --
                                                        # this only skips the "state folder
                                                        # already has data" shortcut)

Output: weather_data/state=<STATE>/data.parquet -- one row per (grid cell, date): 5 key/label
columns (grid_lat, grid_lon, state, district, date) + 35 weather columns (see
DEFAULT_PARAMETERS in nasa_power_client.py for the full list). Column-by-column meaning, units,
and which tool each one backs: DATA_DICTIONARY.md.
`state`/`district` are the representative labels from grid_cells.csv (a cell can straddle more
than one district; the weather series itself doesn't care). To resolve a farmer's actual
pincode to a weather row, join pincode_grid_mapping.parquet (Pincode -> grid_lat, grid_lon)
into this table on (grid_lat, grid_lon).

weather_data/ holds *only* .parquet files, deliberately -- pd.read_parquet("weather_data")
scans every file under the directory tree, and a stray .csv sitting next to a state's
data.parquet breaks that scan outright (confirmed: pyarrow errors trying to parse the .csv as
parquet). A plain-text mirror is written instead to the sibling weather_data_csv/ tree, same
state=<STATE>/data.csv layout, safe to eyeball without touching the parquet tree at all.

Load a single state:   pd.read_parquet("weather_data/state=KERALA/data.parquet")  -- each file
                        is self-contained (includes its own `state` column, not relying on the
                        directory name being parsed).
Load every state:       DON'T call pd.read_parquet("weather_data") directly -- confirmed this
                        raises ArrowTypeError ("Field state has incompatible types: string vs
                        dictionary<...>"), because pyarrow's own Hive-partition auto-discovery
                        (which infers a `state` column from the state=<STATE> folder names,
                        typed as dictionary/categorical) collides with the literal `state`
                        column already embedded in each file (typed as plain string). Instead:

    from pathlib import Path
    import pandas as pd
    files = sorted(Path("weather_data").glob("state=*/data.parquet"))
    all_states = pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)

Eyeball one state as text:    weather_data_csv/state=KERALA/data.csv
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import time
from datetime import date
from pathlib import Path

import pandas as pd

from nasa_power_client import DEFAULT_PARAMETERS, fetch_point_daily

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
GRID_CELLS_CSV = HERE / "grid_cells.csv"
CACHE_DIR = HERE / "cache"
DATA_DIR = HERE / "weather_data"       # parquet only -- pd.read_parquet("weather_data") scans
                                        # every file under here, so nothing but .parquet lives
                                        # in this tree (a stray .csv breaks that scan outright,
                                        # confirmed: pyarrow errors trying to parse it as parquet)
CSV_DIR = HERE / "weather_data_csv"    # human-readable mirror, same state=<STATE>/ layout,
                                        # kept in a separate tree for exactly that reason

REQUEST_SLEEP_SECONDS = 1.0  # be polite to the (unauthenticated, key-less) POWER endpoint


def _params_key(parameters: list[str]) -> str:
    """Short hash of the (sorted) parameter set, folded into the cache filename so changing
    DEFAULT_PARAMETERS (e.g. adding a column) can't silently serve an old, narrower-schema
    cached response as if it were fresh -- it just lands under a new filename instead."""
    return hashlib.sha1(",".join(sorted(parameters)).encode()).hexdigest()[:8]


def _cache_path(grid_lat: float, grid_lon: float, start: date, end: date, params: list[str]) -> Path:
    # start/end folded in too: a --years 1 cache must never be reused to answer --years 10 (or
    # vice versa) just because the grid cell matches -- each distinct (cell, range, param-set)
    # combination gets its own file.
    return CACHE_DIR / (
        f"{grid_lat:.3f}_{grid_lon:.3f}_{start:%Y%m%d}_{end:%Y%m%d}_{_params_key(params)}.parquet"
    )


def _state_dir(state: str) -> Path:
    # Deterministic path, deterministic filename inside it (see fetch_state below) -- a rerun
    # overwrites this state's own data.parquet in place rather than accumulating extra files
    # the way pandas' auto-partitioned writer (random UUID filenames) would.
    return DATA_DIR / f"state={state}"


def _state_csv_dir(state: str) -> Path:
    return CSV_DIR / f"state={state}"


def fetch_state(state: str, state_cells: pd.DataFrame, start: date, today: date, total_cells: int, done_so_far: int) -> pd.DataFrame:
    """Fetch every grid cell for one state (using/populating the per-cell cache), return the
    combined per-state DataFrame. Progress logging counts against the full run's total cell
    count (`total_cells`/`done_so_far`) so the numbers stay meaningful under --state too."""
    frames = []
    for cell in state_cells.itertuples():
        done_so_far += 1
        cache_file = _cache_path(cell.grid_lat, cell.grid_lon, start, today, DEFAULT_PARAMETERS)
        if cache_file.exists():
            frames.append(pd.read_parquet(cache_file))
            continue

        logger.info(
            "[%d/%d] fetching cell (%.3f, %.3f) -- %s, %s (%d pincodes) (%s..%s)",
            done_so_far, total_cells, cell.grid_lat, cell.grid_lon, cell.district, cell.state,
            cell.n_pincodes, start, today,
        )
        df = fetch_point_daily(cell.grid_lat, cell.grid_lon, start, today, parameters=DEFAULT_PARAMETERS)
        df.insert(0, "grid_lat", cell.grid_lat)
        df.insert(1, "grid_lon", cell.grid_lon)
        df.insert(2, "state", cell.state)
        df.insert(3, "district", cell.district)
        df.to_parquet(cache_file, index=False)
        frames.append(df)
        time.sleep(REQUEST_SLEEP_SECONDS)

    state_df = pd.concat(frames, ignore_index=True)
    return state_df.sort_values(["district", "grid_lat", "grid_lon", "date"]).reset_index(drop=True)


def fetch_all(years: int = 10, state_filter: str | None = None, force: bool = False) -> None:
    if not GRID_CELLS_CSV.exists():
        raise FileNotFoundError(
            f"{GRID_CELLS_CSV.name} not found -- run `python build_grid_cells.py` first "
            "(it derives grid cells from pincode_with_lat-long.csv)."
        )

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cells = pd.read_csv(GRID_CELLS_CSV)
    if state_filter:
        cells = cells[cells["state"].str.lower() == state_filter.lower()]
        if cells.empty:
            raise ValueError(f"No grid cells found for state={state_filter!r}")

    today = date.today()
    start = date(today.year - years, 1, 1)  # calendar-year aligned, avoids Feb-29 edge cases

    states = sorted(cells["state"].unique())
    total_cells = len(cells)
    done_so_far = 0
    logger.info("Fetching %d states, %d grid cells total -> %s", len(states), total_cells, DATA_DIR)

    for s_i, state in enumerate(states, start=1):
        out_parquet = _state_dir(state) / "data.parquet"
        state_cells = cells[cells["state"] == state]

        if out_parquet.exists() and not force:
            logger.info(
                "[state %d/%d] %s: already have %s, skipping (use --force to re-save)",
                s_i, len(states), state, out_parquet,
            )
            done_so_far += len(state_cells)
            continue

        state_df = fetch_state(state, state_cells, start, today, total_cells, done_so_far)
        done_so_far += len(state_cells)

        out_dir = _state_dir(state)
        out_dir.mkdir(parents=True, exist_ok=True)
        state_df.to_parquet(out_dir / "data.parquet", index=False)

        csv_dir = _state_csv_dir(state)
        csv_dir.mkdir(parents=True, exist_ok=True)
        state_df.to_csv(csv_dir / "data.csv", index=False)

        logger.info(
            "[state %d/%d] %s: saved %d rows across %d grid cells -> %s",
            s_i, len(states), state, len(state_df), len(state_cells), out_dir,
        )

    logger.info(
        "Done. Load the whole dataset with pd.read_parquet(%r), or one state with "
        "pd.read_parquet(%r).",
        str(DATA_DIR), str(DATA_DIR / "state=<STATE>" / "data.parquet"),
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", type=int, default=10, help="Years of history to fetch (default 10)")
    ap.add_argument("--state", type=str, default=None, help="Only fetch this state (for a quick test run)")
    ap.add_argument("--force", action="store_true", help="Re-fetch/rewrite a state's partition even if already saved")
    args = ap.parse_args()

    fetch_all(years=args.years, state_filter=args.state, force=args.force)


if __name__ == "__main__":
    main()
