"""Location-flexible read access to full_weather.sqlite (see
gramsahayak/datasets/weather/DEPLOYMENT.md for why this is SQLite and how the file is built).

The one function here, get_weather_data(), is the low-level primitive every G3 weather tool
(query-weather-anomaly, query-dry-spell-risk, query-spray-window, ...) will eventually call --
none of them need anything more specific than "averaged daily weather for a resolved location,
optionally date-bounded." Nothing above this layer is built yet; this is deliberately just the
retrieval primitive, tested for memory/speed/correctness before anything is layered on top.

Self-contained within gramsahayak/ (matches pesticide_lookup.py's DEFAULT_JSON_PATH pattern) --
this package is meant to be copyable on its own, so it resolves the DB path relative to this
file rather than depending on a sibling folder outside gramsahayak/.
"""
from __future__ import annotations

import difflib
import re
import sqlite3
from pathlib import Path

# parents[3]: weather_tools/ -> tools/ -> agent/ -> gramsahayak/ (this file is
# gramsahayak/agent/tools/weather_tools/db.py).
DEFAULT_DB_PATH = Path(__file__).resolve().parents[3] / "datasets" / "weather" / "full_weather.sqlite"

# Non-metric columns in daily_weather -- everything else is a weather parameter to average.
# Discovered from the table schema at query time (PRAGMA table_info) rather than hardcoded
# against nasa_power_client.DEFAULT_PARAMETERS, so this stays correct if that list changes
# without needing a fragile cross-directory import (gramsahayak/datasets/weather/ isn't set up
# as an importable package -- its scripts are run directly, not imported).
_KEY_COLUMNS = {"grid_lat", "grid_lon", "state", "district", "date"}


class LocationNotFound(ValueError):
    """Raised when a pincode/district/state input matches no grid cell in the DB."""


def _metric_columns(con: sqlite3.Connection) -> list[str]:
    cols = con.execute("PRAGMA table_info(daily_weather)").fetchall()
    return [row[1] for row in cols if row[1] not in _KEY_COLUMNS]


def _nearest_cell(con: sqlite3.Connection, lat: float, lon: float) -> tuple[float, float]:
    """Nearest grid cell by planar squared-distance over the 987-row grid_cells table.

    Flat (non-haversine) distance is fine here: cells are ~0.5deg apart, and we only need the
    single closest one, not an accurate physical distance -- a full scan of 987 tiny rows to
    find one ORDER BY minimum is sub-millisecond regardless of which distance formula is used.
    """
    row = con.execute(
        """
        SELECT grid_lat, grid_lon
        FROM grid_cells
        ORDER BY (grid_lat - :lat) * (grid_lat - :lat) + (grid_lon - :lon) * (grid_lon - :lon) ASC
        LIMIT 1
        """,
        {"lat": lat, "lon": lon},
    ).fetchone()
    if row is None:
        raise LocationNotFound("grid_cells table is empty -- has full_weather.sqlite been built?")
    return row[0], row[1]


def _cells_for_pincode(con: sqlite3.Connection, pincode: str) -> list[tuple[float, float]]:
    rows = con.execute(
        "SELECT DISTINCT grid_lat, grid_lon FROM pincode_grid WHERE Pincode = ?", (pincode.strip(),)
    ).fetchall()
    if not rows:
        raise LocationNotFound(f"No grid cell found for pincode={pincode!r}.")
    return rows


def _cells_for_field(con: sqlite3.Connection, field: str, value: str) -> list[tuple[float, float]]:
    # field is one of a fixed internal set ("district"/"state"), never user input -- safe to
    # interpolate into the SQL text; `value` itself is always passed as a bound parameter.
    rows = con.execute(
        f"SELECT DISTINCT grid_lat, grid_lon FROM grid_cells WHERE LOWER({field}) = LOWER(?)",
        (value.strip(),),
    ).fetchall()
    if not rows:
        raise LocationNotFound(f"No grid cell found for {field}={value!r}.")
    return rows


# --- district alias resolution (2026-09-14): transliteration-tolerant matching without a
# hardcoded alias list. Colloquial English spellings ("Bangalore", "Mysore", "Shimoga") and
# ASR/NMT garbles ("Shivamanga") never exactly equal the canonical DB names ("BENGALURU
# URBAN", "MYSURU", "SHIVAMOGGA"), and plain difflib on raw strings actively mis-resolves
# (measured: "Bangalore" -> BAGALKOTE, "Shivamanga" -> SIVAGANGA in Tamil Nadu). Stripping
# vowels collapses exactly the transliteration variance (galore/guru, ore/uru, ee/i) while
# keeping consonant skeletons distinct: bangalore/bengaluru -> bnglr, mysore/mysuru -> msr.
# Stdlib only (re/difflib), ~539 short names, runs solely on the exact-miss path. ---
_SKEL_DROP_WORDS = {"urban", "rural", "district", "zila", "zilla", "jilla"}

# Below this, a fuzzy hit is treated as "not understood" and the caller keeps the old
# behavior (state fallback / LocationNotFound) -- fuzzy can only upgrade a fallback,
# never convert one into a wrong-district answer. Country-wide (no state to scope by)
# demands a higher bar since a wrong-state hit is the worst outcome.
_FUZZY_MIN_SCORE_SCOPED = 0.70
_FUZZY_MIN_SCORE_COUNTRY = 0.80
_FUZZY_MIN_MARGIN = 0.05


def _skel(name: str) -> str:
    """Consonant skeleton: lowercase, drop urban/rural-type suffix words, keep a-z,
    delete vowels (incl. y, a vowel in transliteration). Generic character rule -- no
    district names encoded. Returns "" if nothing survives (caller treats as no-match)."""
    words = re.sub(r"[^a-z ]", " ", name.lower()).split()
    words = [w for w in words if w not in _SKEL_DROP_WORDS]
    return re.sub(r"[aeiouy]", "", "".join(words))


def _district_names(con: sqlite3.Connection, state: str | None = None) -> list[tuple[str, str]]:
    """Canonical (district, state) pairs from grid_cells -- the pool always has cells,
    so a hit here can never land on a cell-less name (e.g. BENGALURU RURAL, which has
    pincodes but zero grid cells)."""
    if state is not None and state.strip():
        return con.execute(
            "SELECT DISTINCT district, state FROM grid_cells WHERE LOWER(state) = LOWER(?)",
            (state.strip(),),
        ).fetchall()
    return con.execute("SELECT DISTINCT district, state FROM grid_cells").fetchall()


def _resolve_district(con: sqlite3.Connection, district: str, state: str | None = None) -> tuple[str, str] | None:
    """Canonical (district, state) for a possibly-aliased district string, or None when
    not confidently understood (caller keeps the old fallback path). Never raises."""
    try:
        want = district.strip()
        if not want:
            return None
        scoped = state is not None and bool(state.strip())
        pool = _district_names(con, state if scoped else None)
        if not pool:
            return None  # unknown state spelling: states stay exact-only, no fuzzy on them
        # Exact first (case-insensitive) -- preserves today's behavior for canonical names.
        for d, s in pool:
            if d.lower() == want.lower():
                return (d, s)
        # Fuzzy on consonant skeletons. difflib on raw strings is proven wrong here
        # (Bangalore->BAGALKOTE, Shivamanga->SIVAGANGA), skeletons fix the measured cases.
        target = _skel(want)
        if not target:
            return None
        scored = sorted(
            ((difflib.SequenceMatcher(None, target, _skel(d)).ratio(), d, s) for d, s in pool if _skel(d)),
            reverse=True,
        )
        if not scored:
            return None
        (best, best_d, best_s) = scored[0]
        floor = _FUZZY_MIN_SCORE_SCOPED if scoped or len(pool) <= 60 else _FUZZY_MIN_SCORE_COUNTRY
        if best < floor:
            return None
        if len(scored) > 1 and (best - scored[1][0]) < _FUZZY_MIN_MARGIN:
            return None  # ambiguous top-2: safer to fall back than to guess
        return (best_d, best_s)
    except Exception:
        return None  # fuzzy must never raise outward -- old path handles it


def _cells_for_district(
    con: sqlite3.Connection, district: str, state: str | None = None
) -> list[tuple[float, float]]:
    """District cells honoring an accompanying state (fixes the AURANGABAD-type
    cross-state averaging today's district-alone lookup does even when the agent passed
    both). Falls back to the old district-alone averaging when no state was given, so
    no-state semantics are unchanged. Raises LocationNotFound exactly as before when
    nothing resolves -- the caller's state-fallback/error path then runs untouched."""
    if state is not None and state.strip():
        rows = con.execute(
            "SELECT DISTINCT grid_lat, grid_lon FROM grid_cells "
            "WHERE LOWER(district) = LOWER(?) AND LOWER(state) = LOWER(?)",
            (district.strip(), state.strip()),
        ).fetchall()
        if rows:
            return rows
        resolved = _resolve_district(con, district, state)
        if resolved is not None:
            rows = con.execute(
                "SELECT DISTINCT grid_lat, grid_lon FROM grid_cells "
                "WHERE LOWER(district) = LOWER(?) AND LOWER(state) = LOWER(?)",
                (resolved[0], resolved[1]),
            ).fetchall()
            if rows:
                return rows
        # Scoped miss (incl. weak fuzzy): raise so the caller falls back to STATE,
        # never to the old district-alone lookup -- that lookup ignores the state and
        # would average in another state's same-named district (the AURANGABAD bug).
        raise LocationNotFound(f"No grid cell found for district={district!r} in state={state!r}.")
    else:
        resolved = _resolve_district(con, district, None)
        if resolved is not None and resolved[0].lower() != district.strip().lower():
            # Alias hit without a state to scope by: only trust a strong, unambiguous
            # one (country bar + margin already enforced inside); otherwise keep old path.
            rows = con.execute(
                "SELECT DISTINCT grid_lat, grid_lon FROM grid_cells WHERE LOWER(district) = LOWER(?)",
                (resolved[0],),
            ).fetchall()
            if rows:
                return rows
    return _cells_for_field(con, "district", district)


def describe_location(
    *,
    lat: float | None = None,
    lon: float | None = None,
    pincode: str | None = None,
    district: str | None = None,
    state: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> str:
    """Short truthful label for which place a tool's numbers represent
    ("district=SHIVAMOGGA, Karnataka" vs "state=Karnataka average (district
    'Shivamanga' not matched)"). Mirrors get_weather_data()'s own priority
    (lat/lon > pincode > district > state, with miss fallthrough), sharing
    _resolve_district with the data path, so the label can never disagree with
    the cells actually used. Never raises -- worst case "location unknown"."""
    try:
        con = sqlite3.connect(db_path)
        try:
            if lat is not None and lon is not None:
                return f"lat/lon=({lat}, {lon})"
            if pincode is not None and pincode.strip():
                hit = con.execute(
                    "SELECT 1 FROM pincode_grid WHERE Pincode = ? LIMIT 1", (pincode.strip(),)
                ).fetchone()
                if hit:
                    return f"pincode={pincode.strip()}"
                # Miss: falls through exactly like the data path below.
            if district is not None and district.strip():
                resolved = _resolve_district(con, district, state)
                if resolved is not None:
                    return f"district={resolved[0]}, {resolved[1]}"
                if state is not None and state.strip():
                    return f"state={state.strip()} average (district {district.strip()!r} not matched)"
                return f"district {district.strip()!r} not matched"
            if state is not None and state.strip():
                return f"state={state.strip()} average"
            return "location unknown"
        finally:
            con.close()
    except Exception:
        return "location unknown"


def get_weather_data(
    *,
    lat: float | None = None,
    lon: float | None = None,
    pincode: str | None = None,
    district: str | None = None,
    state: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict]:
    """Fetch daily weather for a location given one of: lat+lon together, pincode, district,
    or state (district/state matched case-insensitively). If you're not sure which fields you
    actually have reliable values for, only pass ONE -- don't guess-fill the rest. Giving more
    than one anyway is not an error: it resolves via the most specific by granularity
    (lat/lon > pincode > district > state, in that order) rather than erroring. lat/lon ranks
    above pincode because it's an exact coordinate with no lookup step at all, whereas a
    pincode still depends on a text match succeeding -- both usually land on the same grid
    cell, but lat/lon can't be typo'd or hallucinated as a plausible-looking wrong value the
    way a 6-digit pincode can.

    lat/lon resolves to the single nearest grid cell. pincode/district/state resolve to
    whichever grid cell(s) match -- a pincode is normally exactly one cell, but a district or
    state can span many. In every case the returned rows are one per date, each weather column
    averaged across however many cells matched (a single-cell match averages over 1, so this is
    the same code path regardless of input type -- not a special case for lat/lon vs the rest).

    start_date/end_date (inclusive, 'YYYY-MM-DD') optionally bound the date range; omitted
    means every date in the table for the resolved cell(s).

    Returns a list of dicts, one per date, ordered oldest to newest: {"date": ..., "PRECTOTCORR":
    ..., "T2M": ..., ...}. Raises LocationNotFound if pincode/district/state matches nothing,
    ValueError if the location arguments themselves are ambiguous or incomplete.
    """
    # Blank/whitespace-only strings count as "not given", not "given but invalid" -- confirmed
    # in a real agent test run that a tool-calling small model sometimes includes an empty
    # string for an optional field it's not actually using (e.g. `pincode=""` alongside a real
    # `district=`) rather than omitting the key outright; treating that as a real value would
    # make it wrongly win priority over the district that was actually meant.
    given = {
        "lat_lon": lat is not None or lon is not None,
        "pincode": bool(pincode and pincode.strip()),
        "district": bool(district and district.strip()),
        "state": bool(state and state.strip()),
    }
    if given["lat_lon"] and (lat is None or lon is None):
        raise ValueError("lat and lon must both be given together.")
    active = [k for k, v in given.items() if v]
    if not active:
        raise ValueError("One of lat+lon, pincode, district, or state must be given; got none.")
    # More than one given (e.g. an agent tool call naturally including both district and
    # state) resolves via the most specific rather than erroring -- confirmed in a real agent
    # test run that over-supplying location fields is a common, reasonable LLM tool-call
    # pattern, and bouncing it back as an error just burns iterations for no benefit.
    # Ranked by granularity, finest first: lat/lon (exact coordinate, no lookup) > pincode
    # (small area, but a text match that can fail/be wrong) > district > state (broadest).
    priority = [k for k in ("lat_lon", "pincode", "district", "state") if given[k]]

    con = sqlite3.connect(db_path)
    try:
        # If the highest-priority mode fails to resolve, fall through to the next one supplied
        # instead of hard-erroring -- confirmed directly on real Jetson hardware that a small
        # tool-calling model sometimes hallucinates a plausible-looking but wrong pincode
        # alongside a correct district (e.g. a real Tamil Nadu pincode attached to a Kerala
        # district query); the district was right there the whole time, no reason to fail.
        cells = None
        last_err = None
        for mode in priority:
            try:
                if mode == "lat_lon":
                    cells = [_nearest_cell(con, lat, lon)]
                elif mode == "pincode":
                    cells = _cells_for_pincode(con, pincode)
                elif mode == "district":
                    # State-scoped when the caller supplied one (fixes cross-state
                    # district collisions); miss (incl. weak fuzzy) raises exactly as
                    # before so the state-fallback below runs untouched.
                    cells = _cells_for_district(con, district, state if given["state"] else None)
                else:
                    cells = _cells_for_field(con, "state", state)
                break
            except LocationNotFound as exc:
                last_err = exc
                cells = None
        if cells is None:
            raise last_err

        metric_cols = _metric_columns(con)
        select_clause = ", ".join(f"AVG({c}) AS {c}" for c in metric_cols)

        cell_clause = " OR ".join(["(grid_lat = ? AND grid_lon = ?)"] * len(cells))
        params: list = [v for cell in cells for v in cell]

        date_clause = ""
        if start_date is not None:
            date_clause += " AND date >= ?"
            params.append(start_date)
        if end_date is not None:
            date_clause += " AND date <= ?"
            params.append(end_date)

        sql = (
            f"SELECT date, {select_clause} FROM daily_weather "
            f"WHERE ({cell_clause}){date_clause} "
            f"GROUP BY date ORDER BY date"
        )
        con.row_factory = sqlite3.Row
        rows = con.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()
