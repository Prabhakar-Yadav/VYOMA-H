"""Climatology-derived weather tools for the G3 agent group -- get_weather_forecast() plus
query_spray_window(), query_sowing_window(), query_pest_pressure_window(), and
query_crop_suitability(), all built on the same shared core (one history fetch + per-day stats
+ contiguous-range grouping) so adding a tool means adding a bucket_fn/describe_fn pair, not
re-deriving the fetch/window/grouping machinery each time.

Every tool returns plain dicts of short strings (or a list of such dicts) -- never a DataFrame,
never a per-day table -- so an agent gets ready-to-relay text instead of a table to reason over.
Not a live forecast: this project only has NASA POWER's historical reanalysis, no forecast API;
every number here is "what's typical for this time of year, from the last N years," not a
prediction of this year specifically. See gramsahayak/datasets/weather/DATA_DICTIONARY.md for
units/definitions of the raw columns this reads (PRECTOTCORR, T2M*, WS2M_MAX, T2MWET, RH2M,
ALLSKY_SFC_SW_DWN/PAR_TOT, GWETPROF).
"""
from __future__ import annotations

import datetime
from collections import Counter

import pandas as pd

from .db import describe_location, get_weather_data

# --- thresholds -- judgment calls, documented so they're easy to revisit. Rain threshold/window
# validated against real data (Kerala monsoon-vs-dry-season test in test_forecast_tools.ipynb):
# raising the "wet day" bar from WMO's trace-rain 1.0mm to 5.0mm and narrowing the pooling
# window from +/-5 to +/-2 days gave a much sharper wet/dry seasonal contrast. ---
RAIN_THRESHOLD_MM = 5.0
DRY_THRESHOLD_MM = 2.5          # below this: "properly dry" for spray/sowing purposes
FLOOD_RAIN_MM = 124.5           # IMD's "very heavy rain" floor -- flood/waterlogging risk
DAY_WINDOW_DEFAULT = 2
RAIN_CHANCE_LOW = 30
RAIN_CHANCE_HIGH = 60

WIND_RISK_THRESHOLD_MS = 5.5    # ~20 km/h -- commonly cited spray-drift caution threshold
WIND_RISK_LOW = 20
WIND_RISK_HIGH = 50

HEAT_WAVE_TMAX_C = 40.0         # IMD's typical plains heat-wave threshold
HEAT_STRESS_WETBULB_C = 28.0    # sustained wet-bulb temps at/above this are physiologically
                                 # stressful for outdoor labor
HUMID_FEEL_GAP_C = 4.0          # dry-bulb minus wet-bulb this close = feels muggy
SOLAR_POOR_MJ = 10.0
SOLAR_GOOD_MJ = 18.0

PEST_TEMP_LOW_C = 25.0          # general insect-pest-favorable band (warm + humid) -- a
PEST_TEMP_HIGH_C = 35.0         # generic entomological heuristic, NOT species-specific; no
PEST_HUMIDITY_MIN_PCT = 70.0    # real pest database backs this, see query_pest_pressure_window

GWET_DRY = 0.3                  # GWETPROF (0-1 fraction) below this: dry soil profile
GWET_WET = 0.6                  # at/above this: saturated/waterlogged risk

HIGHLIGHT_WEEKLY_CUTOVER_DAYS = 14  # periods longer than this: group by week-chunk, not day


# ---------------------------------------------------------------------------
# shared core: one history fetch + per-day stats + contiguous-range grouping,
# reused by every tool function below
# ---------------------------------------------------------------------------

def _fetch_history(years_history: int, **loc) -> pd.DataFrame:
    today = datetime.date.today()
    history_start = datetime.date(today.year - years_history, 1, 1)
    raw = get_weather_data(start_date=history_start.isoformat(), end_date=today.isoformat(), **loc)
    if not raw:
        raise ValueError("No historical data found for this location -- check it resolves to a known grid cell.")
    hist = pd.DataFrame(raw)
    hist["date"] = pd.to_datetime(hist["date"])
    hist["doy"] = hist["date"].dt.dayofyear
    return hist


def _window_mask(hist: pd.DataFrame, target_doy: int, day_window: int) -> pd.Series:
    lo, hi = target_doy - day_window, target_doy + day_window
    if lo < 1:
        return (hist["doy"] >= lo + 366) | (hist["doy"] <= hi)
    if hi > 366:
        return (hist["doy"] >= lo) | (hist["doy"] <= hi - 366)
    return (hist["doy"] >= lo) & (hist["doy"] <= hi)


def _any_event_pct(hist: pd.DataFrame, flat_days: list[datetime.date], field: str, threshold: float) -> int:
    """% of years that had AT LEAST ONE day >= threshold within the calendar span `flat_days`
    covers -- for rare/extreme events (flood, heat wave) where a narrow per-day window has too
    few samples to ever detect the event (confirmed on real data: Meghalaya's 124.5mm+ "flood"
    days are ~0.13% of all days, scattered across different years/dates -- a +/-2-day, 10-year
    window has ~94% chance of showing zero of them purely by chance, even in a genuinely
    flood-prone state/season). "Did this happen at some point in this window, historically" is
    a much more statistically meaningful question for a rare event than a narrow daily rate.
    """
    doys = sorted(d.timetuple().tm_yday for d in flat_days)
    window = hist[(hist["doy"] >= doys[0]) & (hist["doy"] <= doys[-1])]
    if window.empty:
        return 0
    per_year = window.groupby(window["date"].dt.year)[field].apply(lambda s: bool((s.dropna() >= threshold).any()))
    return round(100 * per_year.mean()) if len(per_year) else 0


def _day_stats(window: pd.DataFrame) -> dict:
    rain = window["PRECTOTCORR"].dropna()
    wet_days = rain[rain >= RAIN_THRESHOLD_MM]
    rain_chance_pct = round(100 * len(wet_days) / len(rain)) if len(rain) else None
    rain_amount_mm = round(float(wet_days.mean()), 1) if len(wet_days) else 0.0
    dry_chance_pct = round(100 * (rain < DRY_THRESHOLD_MM).sum() / len(rain)) if len(rain) else None

    wind = window["WS2M_MAX"].dropna()
    wind_risk_pct = round(100 * (wind >= WIND_RISK_THRESHOLD_MS).sum() / len(wind)) if len(wind) else None

    tmax = window["T2M_MAX"].dropna()
    tmax_mean = float(tmax.mean()) if len(tmax) else None

    wetbulb = window["T2MWET"].mean()
    heat_flag = bool(pd.notna(wetbulb) and wetbulb >= HEAT_STRESS_WETBULB_C)
    humid_flag = bool(pd.notna(wetbulb) and tmax_mean is not None and (tmax_mean - wetbulb) <= HUMID_FEEL_GAP_C)

    solar = window["ALLSKY_SFC_SW_DWN"].mean()
    solar_cat = None if pd.isna(solar) else ("poor" if solar < SOLAR_POOR_MJ else ("good" if solar >= SOLAR_GOOD_MJ else "moderate"))

    pest_rows = window.dropna(subset=["T2M", "RH2M"])
    pest_pct = (
        round(100 * ((pest_rows["T2M"] >= PEST_TEMP_LOW_C) & (pest_rows["T2M"] <= PEST_TEMP_HIGH_C)
                      & (pest_rows["RH2M"] >= PEST_HUMIDITY_MIN_PCT)).mean())
        if len(pest_rows) else None
    )

    gwetprof = window["GWETPROF"].mean()
    par = window["ALLSKY_SFC_PAR_TOT"].mean()

    return dict(
        rain_chance_pct=rain_chance_pct, rain_amount_mm=rain_amount_mm, dry_chance_pct=dry_chance_pct,
        wind_risk_pct=wind_risk_pct,
        feels_like_c=round(float(wetbulb), 1) if pd.notna(wetbulb) else None,
        heat_flag=heat_flag, humid_flag=humid_flag, solar_cat=solar_cat, pest_pct=pest_pct,
        gwetprof=round(float(gwetprof), 2) if pd.notna(gwetprof) else None,
        par_mj=round(float(par), 1) if pd.notna(par) else None,
    )


def _per_day_stats(hist: pd.DataFrame, forecast_dates: list[datetime.date], day_window: int) -> dict:
    return {d: _day_stats(hist[_window_mask(hist, d.timetuple().tm_yday, day_window)]) for d in forecast_dates}


def _date_ranges(dates: list[datetime.date]) -> str:
    """[Aug9,Aug10,Aug11,Aug14] -> 'Aug 9-11, Aug 14'"""
    dates = sorted(dates)
    ranges, start, prev = [], dates[0], dates[0]
    for d in dates[1:]:
        if (d - prev).days == 1:
            prev = d
            continue
        ranges.append((start, prev))
        start = prev = d
    ranges.append((start, prev))

    def fmt(a, b):
        if a == b:
            return a.strftime("%b %-d")
        if a.month == b.month:
            return f"{a.strftime('%b %-d')}-{b.strftime('%-d')}"
        return f"{a.strftime('%b %-d')}-{b.strftime('%b %-d')}"

    return ", ".join(fmt(a, b) for a, b in ranges)


def _merge_consecutive(items: list, key_of) -> list[tuple[list, object]]:
    """Group strictly-consecutive (by list position) items sharing the same key_of(item) value."""
    groups, cur_items, cur_key = [], [], object()
    for item in items:
        k = key_of(item)
        if cur_items and k == cur_key:
            cur_items.append(item)
        else:
            if cur_items:
                groups.append((cur_items, cur_key))
            cur_items, cur_key = [item], k
    if cur_items:
        groups.append((cur_items, cur_key))
    return groups


def _chunks(forecast_dates: list[datetime.date], period: int) -> tuple[list[list[datetime.date]], bool]:
    use_weekly = period > HIGHLIGHT_WEEKLY_CUTOVER_DAYS
    chunks = [forecast_dates[i:i + 7] for i in range(0, len(forecast_dates), 7)] if use_weekly else [[d] for d in forecast_dates]
    return chunks, use_weekly


def _label(flat: list[datetime.date], group_chunks: list[list[datetime.date]], use_weekly: bool) -> str:
    if use_weekly:
        return "weeks of " + ", ".join(c[0].strftime("%b %-d") for c in group_chunks)
    return _date_ranges(flat)


def _rain_category(mm: float) -> str:
    # IMD's 24-hour rainfall intensity classification, collapsed to plainer-language buckets
    if mm < 2.5:
        return "very light rain"
    if mm < 7.6:
        return "light rain"
    if mm < 35.6:
        return "moderate rain"
    if mm < 64.5:
        return "heavy rain"
    return "very heavy rain"


def _build_highlight(chunks, per_day, bucket_fn, describe_fn, silent_buckets, empty_text, use_weekly) -> str:
    """Shared grouping+formatting loop every highlight (rain/comfort/wind/flood/heat/pest/...)
    uses: bucket each chunk, merge consecutive same-bucket chunks, describe each surviving
    group, join into one string. `silent_buckets` are buckets that never get a clause (e.g.
    "low" wind risk isn't worth mentioning)."""
    parts = []
    for group_chunks, bucket in _merge_consecutive(chunks, bucket_fn):
        if bucket is None or bucket in silent_buckets:
            continue
        flat = [d for c in group_chunks for d in c]
        parts.append(describe_fn(flat, group_chunks, bucket, per_day, use_weekly))
    return ("; ".join(parts) + ".") if parts else empty_text


def _avg(vals: list) -> float | None:
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


# ---------------------------------------------------------------------------
# tool 1: get_weather_forecast -- rain / comfort / wind / sunlight / flood / heat-wave
# ---------------------------------------------------------------------------

def get_weather_forecast(
    lat: float | None = None, lon: float | None = None, pincode: str | None = None,
    district: str | None = None, state: str | None = None,
    start_date: str | None = None, period: int = 30,
    years_history: int = 10, day_window: int = DAY_WINDOW_DEFAULT,
) -> dict:
    """Climatological weather summary as short narrative strings -- see module docstring.
    Returns {"rain", "comfort", "wind", "sunlight", "flood", "heat_wave"}, each one clause per
    contiguous stretch of similar conditions. "flood"/"heat_wave" stay silent ("No ... risk
    expected") unless actually triggered -- most periods won't mention them at all.
    """
    loc = dict(lat=lat, lon=lon, pincode=pincode, district=district, state=state)
    hist = _fetch_history(years_history, **loc)
    start = datetime.date.fromisoformat(start_date) if start_date else datetime.date.today() + datetime.timedelta(days=1)
    forecast_dates = [start + datetime.timedelta(days=i) for i in range(period)]
    per_day = _per_day_stats(hist, forecast_dates, day_window)
    chunks, use_weekly = _chunks(forecast_dates, period)

    def rain_bucket(c):
        vals = [per_day[d]["rain_chance_pct"] for d in c if per_day[d]["rain_chance_pct"] is not None]
        if not vals:
            return None
        pct = round(sum(vals) / len(vals))
        return "low" if pct < RAIN_CHANCE_LOW else ("high" if pct >= RAIN_CHANCE_HIGH else "moderate")

    def rain_desc(flat, gc, bucket, pd_, wk):
        pct = _avg([pd_[d]["rain_chance_pct"] for d in flat]) or 0
        amt = _avg([pd_[d]["rain_amount_mm"] for d in flat if pd_[d]["rain_amount_mm"]]) or 0.0
        label = _label(flat, gc, wk)
        if bucket == "low":
            return f"{label}: low chance of rain (~{round(pct)}%)"
        return f"{label}: {bucket} chance of rain (~{round(pct)}%), expect {_rain_category(amt)} (~{amt}mm) when it falls"

    rain = _build_highlight(chunks, per_day, rain_bucket, rain_desc, set(), "No significant rain chance expected.", use_weekly)

    def comfort_bucket(c):
        if any(per_day[d]["heat_flag"] for d in c):
            return "stressful"
        if any(per_day[d]["humid_flag"] for d in c):
            return "humid"
        return "comfortable"

    def comfort_desc(flat, gc, bucket, pd_, wk):
        feels = _avg([pd_[d]["feels_like_c"] for d in flat])
        feels_str = f"feels like ~{feels}C" if feels is not None else "no temperature data"
        label = _label(flat, gc, wk)
        if bucket == "stressful":
            return f"{label}: {feels_str}, humid heat-stress risk -- avoid strenuous outdoor work midday"
        if bucket == "humid":
            return f"{label}: {feels_str}, high humidity -- will feel hotter/muggier than the temperature alone suggests"
        return f"{label}: {feels_str}, comfortable humidity"

    comfort = _build_highlight(chunks, per_day, comfort_bucket, comfort_desc, set(), "Comfortable conditions expected throughout.", use_weekly)

    def pct_bucket(field, low, high):
        def f(c):
            vals = [per_day[d][field] for d in c if per_day[d][field] is not None]
            if not vals:
                return "unknown"
            pct = round(sum(vals) / len(vals))
            return "high" if pct >= high else ("moderate" if pct >= low else "low")
        return f

    def pct_desc(field, label_word, action):
        def f(flat, gc, bucket, pd_, wk):
            pct = round(_avg([pd_[d][field] for d in flat]) or 0)
            return f"{_label(flat, gc, wk)}: {bucket} {label_word} (~{pct}%) -- {action}"
        return f

    # Deliberately doesn't claim "good for spraying" on the low-risk/default side -- wind alone
    # doesn't make spraying safe (rain does too, and this highlight doesn't know the rain
    # outlook). query_spray_window() is what actually combines both into a spray verdict.
    wind = _build_highlight(chunks, per_day, pct_bucket("wind_risk_pct", WIND_RISK_LOW, WIND_RISK_HIGH),
                             pct_desc("wind_risk_pct", "wind risk", "avoid spraying -- drift risk"),
                             {"low", "unknown"}, "Low wind risk throughout.", use_weekly)

    # Flood/heat-wave are rare-event highlights -- "% of days averaged over a narrow window"
    # (the pct_bucket/pct_desc pattern above) can't reliably detect them: confirmed on real
    # data that a 124.5mm+ "flood" day is rare and scattered enough across years/dates that a
    # narrow window shows zero of them ~94% of the time by chance, even somewhere flood-prone.
    # _any_event_pct asks "did this happen at least once, per year, within this chunk's actual
    # calendar span" instead -- see its docstring for the full reasoning.
    def event_bucket(field, threshold):
        def f(c):
            return "high" if _any_event_pct(hist, c, field, threshold) >= 30 else (
                "moderate" if _any_event_pct(hist, c, field, threshold) >= 10 else "low"
            )
        return f

    def event_desc(field, threshold, label_word, action):
        def f(flat, gc, bucket, pd_, wk):
            pct = _any_event_pct(hist, flat, field, threshold)
            return f"{_label(flat, gc, wk)}: {bucket} {label_word} (~{pct}% of years) -- {action}"
        return f

    flood = _build_highlight(chunks, per_day, event_bucket("PRECTOTCORR", FLOOD_RAIN_MM),
                              event_desc("PRECTOTCORR", FLOOD_RAIN_MM, "flood/waterlogging risk", "avoid low-lying fields, ensure drainage"),
                              {"low", "unknown"}, "No significant flood risk expected.", use_weekly)

    heat_wave = _build_highlight(chunks, per_day, event_bucket("T2M_MAX", HEAT_WAVE_TMAX_C),
                                  event_desc("T2M_MAX", HEAT_WAVE_TMAX_C, "heat-wave risk", "protect crops/livestock from extreme heat"),
                                  {"low", "unknown"}, "No heat-wave risk expected.", use_weekly)

    def sunlight_bucket(c):
        cats = [per_day[d]["solar_cat"] for d in c if per_day[d]["solar_cat"]]
        return Counter(cats).most_common(1)[0][0] if cats else None

    def sunlight_desc(flat, gc, cat, pd_, wk):
        label = _label(flat, gc, wk)
        if cat == "good":
            return f"{label}: good sun for drying"
        if cat == "poor":
            return f"{label}: mostly cloudy, poor sun-drying conditions"
        return f"{label}: moderate sunlight"

    sunlight = _build_highlight(chunks, per_day, sunlight_bucket, sunlight_desc, set(), "Not enough data to summarize sunlight.", use_weekly)

    return {"rain": rain, "comfort": comfort, "wind": wind, "sunlight": sunlight, "flood": flood, "heat_wave": heat_wave,
            # Which place these numbers represent -- district actually resolved, or the
            # state-average fallback when the district wasn't confidently understood.
            # The agent must relay this honestly ("using the state average") instead of
            # re-asking for a place the farmer already gave.
            "location_resolved": describe_location(**loc)}


# ---------------------------------------------------------------------------
# tool 2: query_spray_window -- best dry windows (spray), wet windows (skip watering),
# flood-level windows (protect rain-sensitive crops)
# ---------------------------------------------------------------------------

def query_spray_window(
    lat: float | None = None, lon: float | None = None, pincode: str | None = None,
    district: str | None = None, state: str | None = None,
    start_date: str | None = None, period: int = 30,
    years_history: int = 10, day_window: int = DAY_WINDOW_DEFAULT,
) -> dict:
    """Best windows for pesticide spraying (dry AND calm -- both gate the selection, since
    either rain or wind alone can ruin a spray application) or skipping irrigation (rain
    already expected), plus a warning for rain-sensitive crops. Ranks candidate spray-safe
    stretches by length so the top pick is a real answer ("spray around Aug 20-23") with 1-2
    buffer alternatives, not a single fragile day that might shift.
    """
    loc = dict(lat=lat, lon=lon, pincode=pincode, district=district, state=state)
    hist = _fetch_history(years_history, **loc)
    start = datetime.date.fromisoformat(start_date) if start_date else datetime.date.today() + datetime.timedelta(days=1)
    forecast_dates = [start + datetime.timedelta(days=i) for i in range(period)]
    per_day = _per_day_stats(hist, forecast_dates, day_window)

    # Spray-safe needs BOTH dry (rain washes pesticide off) AND calm (wind causes drift) --
    # neither alone is sufficient, so both gate the selection, not just rain.
    # NOTE: `value or 100` is a real bug here, not just a style choice -- rain_chance_pct/
    # wind_risk_pct are legitimately 0 on plenty of real days (e.g. calm locations), and
    # `0 or 100` evaluates to 100 in Python since 0 is falsy, silently treating a genuinely
    # safe day as "missing data -> assume risky." Explicit None-checks instead.
    def is_spray_safe(d):
        rain_pct, wind_pct = per_day[d]["rain_chance_pct"], per_day[d]["wind_risk_pct"]
        if rain_pct is None or wind_pct is None:
            return False  # no data -> don't recommend it, conservative default
        return rain_pct < RAIN_CHANCE_LOW and wind_pct < WIND_RISK_LOW

    def is_wet(d):
        return (per_day[d]["rain_chance_pct"] or 0) >= RAIN_CHANCE_HIGH

    def is_flood(d):
        # +/-7 day buffer, not just this one day -- flood-level rain is rare enough that even
        # a single day's own climatology window has too few samples to detect it reliably
        # (see _any_event_pct's docstring); passing a wider span gives it a real chance.
        span = [d - datetime.timedelta(days=7), d + datetime.timedelta(days=7)]
        return _any_event_pct(hist, span, "PRECTOTCORR", FLOOD_RAIN_MM) >= 10

    safe_groups = [flat for flat, ok in _merge_consecutive(forecast_dates, is_spray_safe) if ok]
    wet_groups = [flat for flat, is_w in _merge_consecutive(forecast_dates, is_wet) if is_w]
    flood_groups = [flat for flat, is_f in _merge_consecutive(forecast_dates, is_flood) if is_f]

    safe_groups.sort(key=len, reverse=True)
    top_safe = safe_groups[:3]
    if top_safe:
        best = top_safe[0]
        best_rain = round(_avg([per_day[d]["rain_chance_pct"] for d in best]) or 0)
        best_wind = round(_avg([per_day[d]["wind_risk_pct"] for d in best]) or 0)
        spray_text = (
            f"Best spray window: {_date_ranges(best)} ({len(best)} day(s), ~{best_rain}% rain chance, ~{best_wind}% wind risk)."
        )
        if len(top_safe) > 1:
            buffer_text = "; ".join(_date_ranges(g) for g in top_safe[1:])
            spray_text += f" Buffer alternatives if that shifts: {buffer_text}."
    else:
        spray_text = "No window found that's both dry and calm enough to spray safely in this period -- check the rain and wind highlights for the least-risky days."

    watering_text = (
        "No need to water on: " + "; ".join(_date_ranges(g) for g in wet_groups) + " -- rain expected."
        if wet_groups else "No significant rain expected in this period -- irrigation likely needed throughout."
    )

    flood_text = (
        "Rain-sensitive crops: heavy/flood-level rain expected " + "; ".join(_date_ranges(g) for g in flood_groups) + " -- protect or delay exposure."
        if flood_groups else "No flood-level rain expected -- no special protection needed for rain-sensitive crops."
    )

    return {"spray_window": spray_text, "skip_watering": watering_text, "rain_protection_warning": flood_text,
            "location_resolved": describe_location(**loc)}


# ---------------------------------------------------------------------------
# tool 3: query_sowing_window -- best wet/dry/moderate window for a crop's water need,
# plus flood/drought warnings and a soil-moisture (GWETPROF) note
# ---------------------------------------------------------------------------

def query_sowing_window(
    lat: float | None = None, lon: float | None = None, pincode: str | None = None,
    district: str | None = None, state: str | None = None,
    water_need: str = "moderate",  # "dry" | "moderate" | "wet"
    start_date: str | None = None, months: int = 2,
    years_history: int = 10, day_window: int = DAY_WINDOW_DEFAULT,
) -> dict:
    """Identifies sowing windows matching a crop's water preference over the next `months`,
    plus flood/drought warnings and a soil-moisture-profile (GWETPROF) note for the best
    window found. No crop database exists yet (see DATA_DICTIONARY.md's known gaps) -- caller
    supplies `water_need` directly rather than a crop name.
    """
    if water_need not in ("dry", "moderate", "wet"):
        raise ValueError(f"water_need must be 'dry', 'moderate', or 'wet', got {water_need!r}")

    loc = dict(lat=lat, lon=lon, pincode=pincode, district=district, state=state)
    hist = _fetch_history(years_history, **loc)
    start = datetime.date.fromisoformat(start_date) if start_date else datetime.date.today() + datetime.timedelta(days=1)
    period = months * 30
    forecast_dates = [start + datetime.timedelta(days=i) for i in range(period)]
    per_day = _per_day_stats(hist, forecast_dates, day_window)
    chunks, use_weekly = _chunks(forecast_dates, period)

    def rain_bucket(c):
        vals = [per_day[d]["rain_chance_pct"] for d in c if per_day[d]["rain_chance_pct"] is not None]
        if not vals:
            return None
        pct = round(sum(vals) / len(vals))
        return "low" if pct < RAIN_CHANCE_LOW else ("high" if pct >= RAIN_CHANCE_HIGH else "moderate")

    target_bucket = {"dry": "low", "wet": "high", "moderate": "moderate"}[water_need]
    matches = [
        (group_chunks, bucket) for group_chunks, bucket in _merge_consecutive(chunks, rain_bucket) if bucket == target_bucket
    ]
    matches.sort(key=lambda gb: sum(len(c) for c in gb[0]), reverse=True)

    if matches:
        flat = [d for c in matches[0][0] for d in c]
        label = _label(flat, matches[0][0], use_weekly)
        window_text = f"Best sowing window for a '{water_need}'-preference crop: {label}."
        gwet = _avg([per_day[d]["gwetprof"] for d in flat])
        if gwet is not None:
            soil = "dry -- may need irrigation support for germination" if gwet < GWET_DRY else (
                "saturated -- monitor for waterlogging" if gwet >= GWET_WET else "adequate for germination/root establishment"
            )
            window_text += f" Soil moisture profile expected {soil} (GWETPROF ~{gwet})."
    else:
        window_text = f"No clear '{water_need}'-matching window found in the next {months} month(s) -- conditions stayed mixed throughout."

    def flood_bucket(c):
        # per-chunk span (week-chunk or single day), same rare-event framing as
        # get_weather_forecast's flood highlight -- see _any_event_pct's docstring
        return "risk" if _any_event_pct(hist, c, "PRECTOTCORR", FLOOD_RAIN_MM) >= 10 else "none"

    flood_parts = []
    for gc, b in _merge_consecutive(chunks, flood_bucket):
        if b != "risk":
            continue
        flat = [d for c in gc for d in c]
        flood_parts.append(_label(flat, gc, use_weekly))
    flood_text = ("Flood risk expected " + "; ".join(flood_parts) + " -- avoid sowing then.") if flood_parts else "No flood risk expected in this period."

    def drought_bucket(c):
        vals = [per_day[d]["dry_chance_pct"] for d in c if per_day[d]["dry_chance_pct"] is not None]
        if not vals:
            return None
        return "risk" if round(sum(vals) / len(vals)) >= 80 else "none"

    drought_parts = []
    for gc, b in _merge_consecutive(chunks, drought_bucket):
        if b != "risk":
            continue
        flat = [d for c in gc for d in c]
        drought_parts.append(_label(flat, gc, use_weekly))
    drought_text = ("Extended dry spell risk " + "; ".join(drought_parts) + " -- risky for germination without irrigation.") if drought_parts else "No extended dry-spell risk expected."

    return {"sowing_window": window_text, "flood_warning": flood_text, "drought_warning": drought_text,
            "location_resolved": describe_location(**loc)}


# ---------------------------------------------------------------------------
# tool 4: query_pest_pressure_window -- generic warm+humid pest-favorable windows
# ---------------------------------------------------------------------------

def query_pest_pressure_window(
    lat: float | None = None, lon: float | None = None, pincode: str | None = None,
    district: str | None = None, state: str | None = None,
    start_date: str | None = None, period: int = 30,
    years_history: int = 10, day_window: int = DAY_WINDOW_DEFAULT,
) -> dict:
    """Flags windows where temperature+humidity fall in the general band that favors insect
    pest activity/breeding (T2M 25-35C, RH2M >=70%). This is a GENERIC entomological heuristic,
    not species-specific -- no real pest database backs this (no pest emergence models, no
    per-crop pest profiles). Treat as "conditions worth extra scouting," not a named-pest
    forecast.
    """
    loc = dict(lat=lat, lon=lon, pincode=pincode, district=district, state=state)
    hist = _fetch_history(years_history, **loc)
    start = datetime.date.fromisoformat(start_date) if start_date else datetime.date.today() + datetime.timedelta(days=1)
    forecast_dates = [start + datetime.timedelta(days=i) for i in range(period)]
    per_day = _per_day_stats(hist, forecast_dates, day_window)
    chunks, use_weekly = _chunks(forecast_dates, period)

    def bucket(c):
        vals = [per_day[d]["pest_pct"] for d in c if per_day[d]["pest_pct"] is not None]
        if not vals:
            return "unknown"
        pct = round(sum(vals) / len(vals))
        return "high" if pct >= 60 else ("moderate" if pct >= 35 else "low")

    def desc(flat, gc, b, pd_, wk):
        pct = round(_avg([pd_[d]["pest_pct"] for d in flat]) or 0)
        return f"{_label(flat, gc, wk)}: {b} pest-favorable conditions (~{pct}% of years warm+humid) -- extra scouting recommended"

    text = _build_highlight(chunks, per_day, bucket, desc, {"low", "unknown"},
                             "No notable pest-favorable conditions (warm+humid) expected this period.", use_weekly)
    return {"pest_pressure": text, "caveat": "Generic warm+humid heuristic, not a species-specific pest forecast.",
            "location_resolved": describe_location(**loc)}


# ---------------------------------------------------------------------------
# tool 5: query_crop_suitability -- packages the forecast + a framing note for the LLM to
# reason over (no crop yield model exists -- deliberately NOT a computed suitability score)
# ---------------------------------------------------------------------------

def query_crop_suitability(
    lat: float | None = None, lon: float | None = None, pincode: str | None = None,
    district: str | None = None, state: str | None = None,
    water_need: str = "moderate", heat_sensitive: bool = False, frost_sensitive: bool = False,
    start_date: str | None = None, months: int = 2,
    years_history: int = 10, day_window: int = DAY_WINDOW_DEFAULT,
) -> dict:
    """Returns the weather outlook for the next `months` plus a framing note naming which
    parts of it matter given the crop's stated sensitivities -- for the agent's LLM to turn
    into a suitability assessment, not a computed score. There's no real crop yield/suitability
    model behind this (would need actual FAO/ICAR crop response curves and cultivar data this
    project doesn't have) -- returning raw forecast + framing is the honest scope for now,
    rather than fabricating a number that looks authoritative but isn't backed by real data.
    """
    forecast = get_weather_forecast(
        lat=lat, lon=lon, pincode=pincode, district=district, state=state,
        start_date=start_date, period=months * 30, years_history=years_history, day_window=day_window,
    )
    concerns = []
    if water_need == "dry":
        concerns.append("this crop needs dry conditions -- weigh the rain outlook above as a risk, not a benefit")
    elif water_need == "wet":
        concerns.append("this crop needs consistent moisture -- low rain chance periods above are a yield risk")
    if heat_sensitive:
        concerns.append("this crop is heat-sensitive -- treat the heat_wave/comfort outlook above as a direct risk signal")
    if frost_sensitive:
        concerns.append("this crop is frost-sensitive -- note this forecast has no frost/cold-extreme signal yet (not built)")

    note = (
        f"Weather outlook above covers the next {months} month(s) for this location. "
        + ("Assess suitability considering: " + "; ".join(concerns) + "." if concerns else
           "No specific sensitivities flagged -- assess generally against the outlook above.")
    )
    return {"forecast": forecast, "assessment_note": note,
            # Inherited from the inner get_weather_forecast() call above (same location
            # args, no second lookup) -- top-level copy so the agent sees it without
            # digging into the nested forecast dict.
            "location_resolved": forecast.get("location_resolved", "location unknown")}
