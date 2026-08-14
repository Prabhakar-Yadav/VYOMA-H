"""Thin client for the NASA POWER (Prediction Of Worldwide Energy Resources) daily/point API.

No API key needed. POWER (power.larc.nasa.gov) is a separate, fully open NASA service from
the api.nasa.gov gateway that APOD/DONKI/EPIC/etc. sit behind -- the `nasa_api_key` in this
repo's .env is for *that* gateway, and this module never reads it.

Docs: https://power.larc.nasa.gov/docs/services/api/temporal/daily/
API explorer: https://power.larc.nasa.gov/data-access-viewer/

Adapted from https://github.com/kdmayer/nasa-power-api/blob/main/src/power_api.py, extended
with retries, fill-value handling, transparent multi-parameter batching, and a pandas
DataFrame return shape so it slots straight into fetch_weather_history.py.
"""
from __future__ import annotations

import logging
import time
from datetime import date

import pandas as pd
import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"

# Confirmed empirically: POWER's `point` endpoint rejects a request with more than 20
# parameters ("A maximum of 20 parameters are can currently be requested in one submission.").
# DEFAULT_PARAMETERS below has 35, so fetch_point_daily() batches into ceil(35/20) = 2 requests
# per point and merges them -- see _fetch_one_batch / the batching loop in fetch_point_daily.
MAX_PARAMS_PER_REQUEST = 20

# Full parameter set -- deliberately broad. Grabbing everything agriculture-plausibly-relevant
# now, in the one bulk historical pull, is cheap (an extra ~1 request/cell); going back later
# for one more column means re-running the whole ~987-cell fetch a second time. Units and
# definitions verified against POWER's own metadata endpoint (GET /api/system/manager/parameters),
# not assumed -- full writeup with per-parameter reasoning in DATA_DICTIONARY.md.
DEFAULT_PARAMETERS = [
    # --- core (originally selected against the farmer-tool table) ---
    "PRECTOTCORR",       # precipitation, bias-corrected, mm/day
    "T2M",               # mean air temp @2m, C
    "T2M_MAX",           # max air temp @2m, C
    "T2M_MIN",           # min air temp @2m, C
    "RH2M",              # relative humidity @2m, %
    "WS2M",              # mean wind speed @2m, m/s
    "WS2M_MAX",          # max (gust-ish) wind speed @2m, m/s -- spray-window drift risk
    "ALLSKY_SFC_SW_DWN", # solar irradiance, MJ/m^2/day (NOT kWh/m^2/day) -- solar-drying-days
    "T2MDEW",            # dew/frost point @2m, C -- disease pressure (leaf-wetness proxy) + frost risk
    "FROST_DAYS",        # 1 if T2M_MIN and dew point both < 0C that day, else 0 -- heat/frost risk
    "GWETTOP",            # topsoil (0-5cm) wetness, 0-1 -- dry-spell / sowing-window (germination)
    "GWETROOT",            # root-zone (~1m) wetness, 0-1 -- crop water need / dry-spell risk
    "EVPTRNS",             # evapotranspiration energy flux, MJ/m^2/day -- crop water need (divide by
                           # ~2.45 MJ/kg latent heat of vaporization to get ET in mm/day)
    # --- extended (grabbed now so a future tool never needs a second full re-fetch) ---
    "GWETPROF",           # soil wetness, full profile (surface to bedrock), 0-1
    "T2MWET",             # wet-bulb temp @2m, C -- combined heat+humidity stress
    "QV2M",               # specific humidity @2m, g/kg
    "WD2M",                # wind direction @2m, degrees
    "WD10M",                # wind direction @10m, degrees
    "ALLSKY_SFC_PAR_TOT",    # photosynthetically active radiation, MJ/m^2/day -- crop-growth-specific
                             # radiation signal (narrower band than ALLSKY_SFC_SW_DWN)
    "CLRSKY_SFC_SW_DWN",     # clear-sky solar irradiance, MJ/m^2/day -- ALLSKY/CLRSKY ratio = cloudiness
    "TSOIL1", "TSOIL2", "TSOIL3", "TSOIL4", "TSOIL5", "TSOIL6",  # soil temp, 6 depth layers, C
    "PRECSNO",             # snow precipitation, mm/day -- only matters for hill-agriculture states
    "WS10M", "WS10M_MAX", "WS10M_MIN", "WS10M_RANGE",  # wind speed @10m, m/s
    "WS50M", "WS50M_MAX", "WS50M_MIN", "WS50M_RANGE",  # wind speed @50m, m/s
]

# POWER fills missing/unavailable cells with this sentinel instead of a JSON null.
FILL_VALUE = -999.0


def _fetch_one_batch(
    latitude: float,
    longitude: float,
    start: date,
    end: date,
    parameters: list[str],
    community: str,
    max_retries: int,
    timeout: int,
) -> pd.DataFrame:
    """Single HTTP call, <=20 parameters. Internal -- fetch_point_daily() is the public API."""
    params = {
        "parameters": ",".join(parameters),
        "community": community,
        "longitude": longitude,
        "latitude": latitude,
        "start": start.strftime("%Y%m%d"),
        "end": end.strftime("%Y%m%d"),
        "format": "JSON",
    }

    last_err = None
    payload = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(BASE_URL, params=params, timeout=timeout)
            resp.raise_for_status()
            payload = resp.json()
            break
        except (requests.RequestException, ValueError) as exc:
            last_err = exc
            wait = 2 ** attempt  # 2s, 4s, 8s, 16s
            logger.warning(
                "POWER request failed (attempt %d/%d) for (%.3f, %.3f) [%s..%s]: %s -- retrying in %ds",
                attempt, max_retries, latitude, longitude, start, end, exc, wait,
            )
            time.sleep(wait)

    if payload is None:
        raise RuntimeError(
            f"NASA POWER request failed after {max_retries} attempts for "
            f"({latitude}, {longitude}) [{start}..{end}]"
        ) from last_err

    try:
        param_data = payload["properties"]["parameter"]
    except KeyError as exc:
        # POWER returns HTTP 200 with an error payload (e.g. bad param name, point over
        # ocean/no-data) rather than a 4xx -- surface that instead of a cryptic KeyError.
        raise RuntimeError(
            f"NASA POWER returned no data for ({latitude}, {longitude}): {payload}"
        ) from exc

    df = pd.DataFrame(param_data)
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    df.index.name = "date"
    df = df.replace(FILL_VALUE, pd.NA)
    return df


def fetch_point_daily(
    latitude: float,
    longitude: float,
    start: date,
    end: date,
    parameters: list[str] | None = None,
    community: str = "AG",
    max_retries: int = 4,
    timeout: int = 60,
    batch_sleep_seconds: float = 1.0,
) -> pd.DataFrame:
    """Fetch one point's daily weather for [start, end] (inclusive) as a DataFrame.

    community="AG" (Agroclimatology) is the community whose derived/bias-corrected variants
    (e.g. PRECTOTCORR) this parameter set expects; POWER also has RE (renewable energy) and SB
    (sustainable buildings) communities, mainly relevant if you add radiation/energy params.

    Transparently splits into multiple requests if `parameters` exceeds
    MAX_PARAMS_PER_REQUEST (20) -- confirmed empirically as a hard API limit -- and merges the
    results on date. DEFAULT_PARAMETERS (35 params) always triggers 2 requests per point;
    callers don't need to think about this, just budget for it in rate-limit/timing math (see
    fetch_weather_history.py, which sleeps between cells; this sleeps between a cell's own
    batches too, so the two compose into one steady, still-polite request rate).

    Returns a DataFrame with a `date` column plus one column per requested parameter, values
    coerced to NaN wherever POWER used its -999 fill sentinel.
    """
    params_list = parameters or DEFAULT_PARAMETERS
    batches = [
        params_list[i : i + MAX_PARAMS_PER_REQUEST]
        for i in range(0, len(params_list), MAX_PARAMS_PER_REQUEST)
    ]

    dfs = []
    for i, batch in enumerate(batches):
        dfs.append(_fetch_one_batch(latitude, longitude, start, end, batch, community, max_retries, timeout))
        if i < len(batches) - 1:
            time.sleep(batch_sleep_seconds)

    merged = dfs[0] if len(dfs) == 1 else pd.concat(dfs, axis=1)
    merged.index.name = "date"
    return merged.reset_index()
