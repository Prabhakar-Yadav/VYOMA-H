# Serving weather data to agent tools: architecture + benchmark evidence

The question this answers: once `weather_data/` exists (987 grid cells × up to 20 years ×
35 parameters, 324MB as partitioned parquet), how do the agent's weather tools (`query-
weather-anomaly`, `query-dry-spell-risk`, `query-spray-window`, `query-sowing-window`,
`query-crop-suitability`, `recommend-alternative-crop`, ...) read from it at runtime — without
loading the whole dataset into memory, and fast — on the actual deployment target: a **Jetson
Orin, 8GB RAM (7.4GB usable), shared with resident ASR/TTS/NMT/LLM models**, where memory
headroom for this component is genuinely thin.

## The decision: SQLite for runtime serving, one file, indexed

Not DuckDB, not raw parquet reads, not pandas — **SQLite**, and not by assumption: benchmarked
on real hardware, both a dev machine (gx10, aarch64) and the actual Jetson Orin target
(`jetson@100.118.21.46`, Tegra R36.4.2, 6-core ARMv8, 7.4GB RAM, 116GB flash storage with 69GB
free at test time). Same query on all three approaches — "this grid cell's weather since a
given date," the shape every one of the tools above actually needs:

| Approach | gx10 peak RSS | gx10 time | **Jetson peak RSS** | **Jetson time** |
|---|---|---|---|---|
| Naive pandas (load whole state file, filter in memory) | 240 MB | 46 ms | 297 MB | 92 ms |
| DuckDB, querying parquet directly (predicate pushdown) | 141 MB | 313 ms | 156 MB | 680 ms |
| **SQLite, indexed lookup** | **11 MB** | **0.6 ms** | **9.4 MB** | **1-3 ms** |

That last row was tested against a **single 66MB state file**. The real question was whether
that low-memory behavior holds once the file is the *entire* nationwide dataset, not just one
state — since "pull only what's needed per query, regardless of total DB size" was the actual
requirement. Built the full 7,426,188-row, 34-state, **2.9GB** SQLite file directly on the
Jetson (`build_sqlite_db.py`, 262s) and re-ran the same query:

```
sqlite full-db (indexed): 38 rows in 0.0013s, peak RSS 9.4 MB
```

Identical to the single-state result. Confirmed again across 5 different random grid cells
scattered across different states (Jammu & Kashmir, Maharashtra, Bihar ×2, Madhya Pradesh) in
the same process — all sub-1.2ms, cumulative peak RSS never moved past 12.1MB. SQLite's B-tree
index lookup genuinely only touches the pages a query needs; total file size is irrelevant to
per-query memory. That's the property this deployment needs, and it's the one DuckDB/pandas
don't give you at this end of the memory budget.

**Also confirmed**: a pincode → grid cell → weather lookup end-to-end using nothing but
Python's built-in `sqlite3` module (no pandas/pyarrow/duckdb at runtime at all):

```python
cell = con.execute("SELECT grid_lat, grid_lon FROM pincode_grid WHERE Pincode = ?", (pincode,)).fetchone()
rows = con.execute(
    "SELECT date, PRECTOTCORR, T2M, T2M_MAX, T2M_MIN, RH2M FROM daily_weather "
    "WHERE grid_lat = ? AND grid_lon = ? ORDER BY date DESC LIMIT ?",
    (cell["grid_lat"], cell["grid_lon"], days),
).fetchall()
```
`pincode 695024 -> KERALA, 14 days fetched in 0.96ms, peak RSS 9.4 MB`

That means the Jetson-side runtime dependency footprint for weather tools is **zero extra
packages** — `sqlite3` ships with Python.

## What NOT to do: expose raw SQL as an agent tool

Don't give the LLM a `run_sql(query: str)` tool. An LLM-authored query against even a properly
indexed table can accidentally full-scan (wrong column in a WHERE clause, a `SELECT *` without
a filter, a join that fans out) — on a device already budgeting every MB against resident
ASR/TTS/NMT/LLM models, one bad generated query is a real failure mode, not just a style
concern. Instead: a small number of narrow, parameterized Python functions — matching the
existing pattern in `gramsahayak/agent/tools/` (`pesticide_lookup(pesticide_name: str)`, not
`run_sql`) — each running one fixed, pre-indexed SQL statement:

```python
def get_recent_weather(pincode: str, days: int = 30) -> list[dict]:
    """Backs query-weather-anomaly / query-dry-spell-risk / query-spray-window's 'what has
    actually happened' side."""
    ...

def get_climatology(grid_lat: float, grid_lon: float, day_of_year: int, window_days: int = 7):
    """Backs the 'vs normal' side -- needs a derived table, see Known gap below."""
    ...
```

None of the tools in the current spec need ad hoc querying; they all reduce to "recent days for
this cell" or "historical normal for this cell/day-of-year" — both are single indexed lookups.

## Known gap: this ships raw daily history, not climatology yet

`build_sqlite_db.py` loads `daily_weather` as-is from `weather_data/` — every raw
`(grid cell, date)` row, no aggregation. That's deliberate for this pass (data loading only,
per the "one-time data addition, don't worry about ETL" scope) but it means `query-weather-
anomaly` ("this year vs last 10 years") and the "expected weather for the next N days" half of
`query-dry-spell-risk`/`query-spray-window` still need a **derived table** — day-of-year
climatology (mean/percentile bands per grid cell), not currently in `full_weather.sqlite`. That
derivation is cheap (small output — ~987 cells × 366 days ≈ 361K rows) and can be added as a
third table in the same file without touching this build's approach; it's just not built yet.
`query-crop-suitability` and `recommend-alternative-crop` additionally need a
`crop_requirement_profile` data source this pipeline doesn't produce at all (agronomic
thresholds per crop — not a NASA POWER output).

## Reproducing / updating the deployed file

```bash
# On a machine with weather_data/ + pincode_grid_mapping.parquet present (memory not a concern):
python build_sqlite_db.py                 # writes ./full_weather.sqlite, ~2.9GB, ~4.5 min

# Ship it -- single self-contained file, nothing else needs to travel with it:
scp full_weather.sqlite jetson@<host>:~/.../gramsahayak/datasets/weather/
```

Rebuilding is a full replace, not incremental — fine for the current one-time-load scope; worth
revisiting if this becomes a recurring refresh (e.g. re-running `fetch_weather_history.py`
periodically to extend the history forward).
