# Weather history pipeline (NASA POWER)

Raw material for the weather-family agent tools listed in the tool table (`query_rainfall_anomaly`,
`query_dry_spell_risk`, `query_heat_frost_risk`, `query_spray_window`, `query_solar_drying_days`,
`query_harvest_weather_risk`, `query_sowing_window`, `calculate_crop_water_need`,
`query_disease_pressure_forecast`, `recommend_alternative_crop`) — this is where
`daily_climatology` comes from before `anomaly_thresholds` / `crop_requirement_profile` get
layered on top. It replaces the `MOCK` weather tools currently stubbed in
[`gramsahayak/agent/agent.py`](../../agent/agent.py) (e.g. `query_harvest_weather_risk`, whose
docstring already says "will read NASA POWER / IMD Pune gridded rainfall").

This file covers getting the raw data (`weather_data/`, one row per grid cell per day). For how
that gets served to the agent's tools at runtime on the actual Jetson deployment target —
including real benchmark numbers from that hardware — see
**[DEPLOYMENT.md](DEPLOYMENT.md)**.

## The API

**NASA POWER** (power.larc.nasa.gov) — not `api.nasa.gov`. Two different NASA services with
similar names:

| | api.nasa.gov (APOD, DONKI, EPIC, Earth imagery, …) | power.larc.nasa.gov (POWER) |
|---|---|---|
| Auth | API key required (`DEMO_KEY` or your own) | **No key** |
| What's in `.env` | `nasa_api_key` — unused by this pipeline | n/a |
| Used here? | No | Yes |

So the `nasa_api_key` already sitting in this repo's `.env` isn't needed for any of this, and
`nasa_power_client.py` never reads it. Keep it around only if something else in the project
later wants APOD/DONKI/imagery.

Endpoint: `GET https://power.larc.nasa.gov/api/temporal/daily/point`, `community=AG`
(Agroclimatology — matches the bias-corrected precip variant below), one point (lat/lon) per
call, `format=JSON`. Full docs: https://power.larc.nasa.gov/docs/services/api/temporal/daily/

There's also a `regional` (bounding-box) endpoint that returns a whole grid in one call — I
tested it directly and it's not a fit here: **max 1 parameter per request** and a **max 10°×10°
box**, so covering all parameters nationwide would mean tiling + a per-parameter merge, for
no real win over the point endpoint (see "Why grid cells, not raw pincodes" below — once you're
deduped to ~987 points, the point endpoint alone is already fast). It was useful for one thing
though: querying it is how the 0.5°×0.625° grid spacing below got confirmed — read straight off
its own returned grid-point coordinates, not assumed.

**35 parameters fetched** (`nasa_power_client.DEFAULT_PARAMETERS`) — grabbed broadly on purpose:
going back for one more column later means re-running the whole ~987-cell pull a second time,
so this pipeline fetches everything agriculture-plausibly-relevant in the one bulk run instead.
The `point` endpoint caps at **20 parameters per request** (confirmed empirically, a 422 error
past that) — `fetch_point_daily()` transparently splits into 2 batched requests per cell and
merges them, so this doesn't change how you call it, just the request count (see "Fetching the
weather data" below). Full definitions, exact units, and per-tool reasoning (pulled live from
POWER's own parameter-metadata endpoint, not memory) in **[DATA_DICTIONARY.md](DATA_DICTIONARY.md)**.
The 13 originally selected against a named tool:

| Parameter | Meaning | Feeds |
|---|---|---|
| `PRECTOTCORR` | bias-corrected precipitation, mm/day | rainfall anomaly, dry spell, spray window, sowing window, crop water need |
| `T2M`, `T2M_MAX`, `T2M_MIN` | 2m air temperature, °C | heat/frost risk, crop water need |
| `RH2M` | relative humidity at 2m, % | disease pressure forecast |
| `WS2M`, `WS2M_MAX` | wind speed at 2m, mean/max, m/s | spray window (drift risk) |
| `ALLSKY_SFC_SW_DWN` | surface solar irradiance, **MJ/m²/day** | solar drying days |
| `T2MDEW` | dew/frost point at 2m, °C | disease pressure (leaf-wetness proxy), heat/frost risk |
| `FROST_DAYS` | POWER's own frost-day flag (0/1) | heat/frost risk |
| `GWETTOP`, `GWETROOT` | topsoil / root-zone soil wetness, 0–1 | dry spell risk, sowing window, crop water need |
| `EVPTRNS` | evapotranspiration energy flux, MJ/m²/day | crop water need |

Plus 22 more (soil moisture profile, soil temp at 6 depths, wind speed/direction at 10m/50m,
PAR, clear-sky radiation, wet-bulb temp, specific humidity, snow) — not tied to a named tool
yet, fetched now so they're already there when one needs them. Full list with units and
reasoning: [DATA_DICTIONARY.md](DATA_DICTIONARY.md#extended-columns).

> **Correction**: an earlier version of this doc said `ALLSKY_SFC_SW_DWN` was in kWh/m²/day.
> Checked against POWER's metadata endpoint directly — it's **MJ/m²/day** (divide by 3.6 for
> kWh/m²/day). Fixed here and in `DATA_DICTIONARY.md`.

POWER fills missing cells with `-999` instead of `null`; `fetch_point_daily()` converts those
to `NaN` for you. Data is available back to 1981, and — confirmed empirically — **a single
`point` request has no multi-year limit**: a 10-year pull for one point (per 20-param batch)
returned in ~1 second. (The `regional` endpoint does cap at 366 days per request; irrelevant
here since we don't use it.)

## Locations: pincodes → grid cells, not a hand-picked list

Earlier iteration of this pipeline used a hand-picked `locations.csv` of ~150 district-HQ
coordinates. That's gone now — `pincode_with_lat-long.csv` (India Post's full pincode list,
157k post offices / ~20,300 distinct pincodes, all-India) is a much better source of truth for
"where do farmers actually are," so location selection now derives from that file instead of
guesswork. Run once:

```bash
python build_grid_cells.py
```

This produces two tables (no network calls, finishes in seconds):

- **`pincode_grid_mapping.parquet`** — every valid pincode (20,308 of them) with the NASA POWER
  grid cell it falls in (`grid_lat`, `grid_lon`). The lookup table: given a farmer's pincode,
  join here to find their grid cell, then join that into `weather_data/` (see below).
- **`grid_cells.csv`** — the deduplicated list of **987 unique grid cells** nationwide. This is
  what `fetch_weather_history.py` actually fetches from NASA POWER.

### Why grid cells, not raw pincodes

NASA POWER's underlying reanalysis grid is **0.5° lat × 0.625° lon** (~50-60km cells) — this
isn't a guess, it's read straight off the API's own `regional` response grid spacing. Two
pincodes inside the same cell get back **identical** weather. I verified this directly against
the live API: pincodes `695313` and `695024` (Thiruvananthapuram, 34km apart) land in the same
grid cell and returned byte-for-byte identical `PRECTOTCORR`/`T2M` series.

So fetching once per pincode (~20,300 requests) would mean ~95% of those calls return data
you've already fetched under a different pincode. Snapping every pincode to its grid cell first
collapses that to **987 requests** — same coverage, 20x fewer calls. `n_pincodes` in
`grid_cells.csv` tells you how many real pincodes each cell represents (ranges from 1 in sparse
areas to 190+ in dense districts like Thrissur).

Caveat: `state`/`district` in `grid_cells.csv` are just the *most common* label among a cell's
pincodes, for readable logging — a handful of cells straddle a state border or carry a
mislabeled row from the source data (e.g. one Kerala-bordering cell shows `district=CHENNAI`
because of a stray postal record). Harmless for fetching (the real key is `grid_lat`/`grid_lon`
and the point endpoint is queried by coordinate, not label) but don't treat those columns as
authoritative for anything else.

## Fetching the weather data

```bash
cd gramsahayak/datasets/weather
pip install -r ../../../requirements.txt   # pandas, requests, pyarrow
python build_grid_cells.py                 # if you haven't already — produces grid_cells.csv

# Quick smoke test: one state, one year
python fetch_weather_history.py --state KERALA --years 1

# Full pull: all 987 grid cells across every state, ~1,974 requests (35 params, batched
# 20+15 per cell — see DEFAULT_PARAMETERS)
python fetch_weather_history.py --years 10
```

`--state` matches `grid_cells.csv`'s `state` column, which is upper-cased India-Post style
(`KERALA`, not `Kerala`).

- **~1,974 requests total** (987 cells × 2 batches), not × years — each batch pulls the whole
  date range for that cell in one shot. Budget **40-55 min** at the default 1 req/sec pace for
  a full nationwide run.
- **Saved per state, incrementally — not just once at the end.** As soon as a state's cells are
  all fetched, that state's `weather_data/state=<STATE>/data.parquet` is written immediately,
  before moving to the next state. A ~45-minute run stopping partway (crash, network drop, an
  undocumented rate limit) doesn't lose everything — `weather_data/` itself shows you exactly
  which states finished: `ls weather_data` lists the completed `state=...` folders, and
  whatever's missing is what's left. Rerunning the same command skips any state that already
  has a `data.parquet` (add `--force` to re-fetch and overwrite a state anyway).
- **Two layers of resumability.** Per-state (above) plus per-cell: each grid cell's raw
  response is cached to `cache/<lat>_<lon>_<start>_<end>_<params_hash>.parquet` the first time
  it succeeds, so even a state that gets re-fetched (e.g. after `--force`, or because it never
  finished) doesn't re-request cells it already has.
- **Rate-limited & retried.** One request per second, exponential backoff (2s/4s/8s/16s) on
  transient failures. POWER doesn't require a key but is still a shared public endpoint — don't
  drop the sleep when scaling this up.
- **Output**: `weather_data/state=<STATE>/data.parquet` per state — one row per `(grid cell,
  date)`, 35 weather columns plus `grid_lat, grid_lon, state, district, date`. Full
  column-by-column reference: [DATA_DICTIONARY.md](DATA_DICTIONARY.md). Load one state directly:

  ```python
  import pandas as pd
  kerala = pd.read_parquet("gramsahayak/datasets/weather/weather_data/state=KERALA/data.parquet")
  ```

  To load *every* state, **don't** call `pd.read_parquet("weather_data")` directly — tested
  this and it raises `ArrowTypeError` (`Field state has incompatible types: string vs
  dictionary<...>`). Cause: pyarrow's Hive-partition auto-discovery infers a `state` column
  from the `state=<STATE>` folder names (typed as dictionary/categorical) which collides with
  the literal `state` column already embedded in each file (typed as plain string). Use a plain
  glob + concat instead — sidesteps partition auto-discovery entirely, confirmed working:

  ```python
  from pathlib import Path
  import pandas as pd
  files = sorted(Path("gramsahayak/datasets/weather/weather_data").glob("state=*/data.parquet"))
  all_states = pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)
  ```

  `weather_data/` holds *only* `.parquet` files, deliberately — the same directory-scan that
  trips on the dictionary-type mismatch above would also choke outright on a stray `.csv` next
  to a state's `data.parquet` (also confirmed directly). A plain-text mirror goes to the
  sibling `weather_data_csv/state=<STATE>/data.csv` instead — same layout, safe to open in a
  text editor without touching the parquet tree.

  `cache/`, `weather_data/`, and `weather_data_csv/` are all gitignored (regenerate, don't
  commit — same pattern as the model checkpoints elsewhere in this repo). `pincode_grid_mapping.parquet`
  and `grid_cells.csv` *are* committed — they're small, deterministic derivations of
  `pincode_with_lat-long.csv`, and other code depends on `grid_cells.csv` existing.

## Resolving a farmer's pincode to weather

Goes straight to that pincode's own state partition — no need to load the whole dataset (and
sidesteps the partitioned-read gotcha above entirely, since this only ever opens one file):

```python
import pandas as pd
from pathlib import Path

mapping = pd.read_parquet("pincode_grid_mapping.parquet")  # Pincode -> StateName, grid_lat, grid_lon
WEATHER_DIR = Path("weather_data")

def weather_for_pincode(pincode: str) -> pd.DataFrame:
    row = mapping.loc[mapping["Pincode"] == pincode].iloc[0]
    state_file = WEATHER_DIR / f"state={row['StateName']}" / "data.parquet"
    state_weather = pd.read_parquet(state_file)
    return state_weather[
        (state_weather["grid_lat"] == row["grid_lat"]) & (state_weather["grid_lon"] == row["grid_lon"])
    ]
```

Note `mapping`'s `StateName` (India Post's actual per-pincode label) is what's used to pick the
file here, not `grid_cells.csv`'s `state` (the cell's *most common* label, which is what
`weather_data`'s own partition folders are actually named after) — for the handful of border
cells where those two disagree, trust the folder name over `StateName` if a direct lookup
misses (i.e. treat this as a fast path, and fall back to scanning `grid_cells.csv` for the
matching `grid_lat`/`grid_lon` to get the folder's real state name on a `FileNotFoundError`).

## From raw history to `daily_climatology` / `anomaly_thresholds`

This pipeline stops at the raw daily table. The two derived tables the tool group needs are a
short `groupby` away and deliberately left for whoever wires up the real tools (so the
aggregation windows can be tuned against real farmer questions). The example below only
aggregates precip/temp for brevity — the same pattern applies to any of the 13 columns in
[DATA_DICTIONARY.md](DATA_DICTIONARY.md) (e.g. `GWETROOT` normals for `calculate_crop_water_need`,
`FROST_DAYS` counts for `query_heat_frost_risk`):

```python
df["doy"] = df["date"].dt.dayofyear

# daily_climatology: per-cell, per-day-of-year normals
daily_climatology = (
    df.groupby(["grid_lat", "grid_lon", "doy"])
      .agg(precip_mean=("PRECTOTCORR", "mean"),
           precip_std=("PRECTOTCORR", "std"),
           tmax_mean=("T2M_MAX", "mean"),
           tmin_mean=("T2M_MIN", "mean"))
      .reset_index()
)

# anomaly_thresholds: e.g. 10th/90th percentile bands per cell/day-of-year, for
# "is this year's rain unusually low" / dry-spell-risk style comparisons
anomaly_thresholds = (
    df.groupby(["grid_lat", "grid_lon", "doy"])["PRECTOTCORR"]
      .quantile([0.1, 0.9])
      .unstack()
      .rename(columns={0.1: "precip_p10", 0.9: "precip_p90"})
      .reset_index()
)
```

A day-of-year join needs a `±N`-day window (not exact-day) to get enough samples per bucket
across only 10 years of history — worth deciding alongside whoever builds
`query_rainfall_anomaly` / `query_dry_spell_risk`, since the window size is really a tool
design choice, not a data pipeline one.
