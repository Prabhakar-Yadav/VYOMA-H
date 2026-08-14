# Data dictionary — `weather_data/state=<STATE>/data.parquet` / `.csv`

One row per `(grid cell, date)`. Every unit/definition below is copied verbatim from NASA
POWER's own metadata endpoint (`GET /api/system/manager/parameters?community=AG&temporal=daily`)
— queried live, not taken from memory or a docs page — so it reflects exactly what the `point`
API hands back for `community=AG`.

## Key / label columns

| Column | Type | Meaning |
|---|---|---|
| `grid_lat`, `grid_lon` | float | Center of the NASA POWER grid cell this row belongs to (~0.5° × 0.625°, ~50-60km). This is the real join key — see [README.md](README.md#resolving-a-farmers-pincode-to-weather) for joining a farmer's pincode to it via `pincode_grid_mapping.parquet`. |
| `state`, `district` | string | The *most common* label among the real pincodes that fall in this cell (from `grid_cells.csv`). Informational/logging only — a handful of border cells carry an imprecise or mislabeled district; don't treat as authoritative. Not present in `pincode_grid_mapping.parquet`, which has India Post's actual per-pincode `StateName`/`District`. |
| `date` | date | Calendar day, UTC. |

## Core weather columns

These 13 were the original selection, chosen directly against a named tool in the tool table.

| Column | Unit | POWER's definition | Tool(s) it backs | Notes |
|---|---|---|---|---|
| `PRECTOTCORR` | mm/day | "The average MERRA-2 bias corrected total precipitation at the surface of the earth." | `query_rainfall_anomaly`, `query_dry_spell_risk`, `query_spray_window`, `query_sowing_window`, `calculate_crop_water_need` | The bias-corrected variant — prefer this over plain `PRECTOT` (not fetched), which POWER's own catalog flags as a coarser, uncorrected series. |
| `T2M` | °C | "The average air (dry bulb) temperature at 2 meters above the surface of the earth." | `calculate_crop_water_need`, general climatology | Daily mean. |
| `T2M_MAX` | °C | "The maximum hourly air (dry bulb) temperature at 2 meters ... in the period of interest." | `query_heat_frost_risk` | Daily max — heat-stress side. |
| `T2M_MIN` | °C | "The minimum hourly air (dry bulb) temperature at 2 meters ... in the period of interest." | `query_heat_frost_risk` | Daily min — frost side (frost risk rises as this approaches/crosses 0°C). |
| `RH2M` | % | "The ratio of vapor pressure to the saturation vapor pressure ..., expressed in percent." | `query_disease_pressure_forecast` | Sustained high RH (~>80-85%) is the standard proxy for fungal/blight-favorable conditions. |
| `WS2M` | m/s | "The average of wind speed at 2 meters above the surface of the earth." | `query_spray_window` | Daily mean — steady drift risk. |
| `WS2M_MAX` | m/s | "The maximum hourly wind speed at 2 meters ... in the period of interest." | `query_spray_window` | Daily peak — catches a gusty afternoon a calm daily average would hide; more decision-relevant than `WS2M` alone for "can I spray today." |
| `ALLSKY_SFC_SW_DWN` | **MJ/m²/day** | "The total solar irradiance incident (direct plus diffuse) on a horizontal plane ... under all sky conditions" (a.k.a. Global Horizontal Irradiance / GHI). | `query_solar_drying_days` | ⚠️ Corrected value — an earlier version of this README mislabeled the unit as kWh/m²/day. It's MJ/m²/day. To convert: `kWh/m²/day = MJ/m²/day / 3.6`. Typical India daily values run ~14-25 MJ/m²/day (~4-7 kWh/m²/day); anything in the high teens/twenties MJ is a good sun-drying day, single digits means overcast. |
| `T2MDEW` | °C | "The dew/frost point temperature at 2 meters above the surface of the earth." | `query_disease_pressure_forecast`, `query_heat_frost_risk` | How close `T2M_MIN` sits to `T2MDEW` at night is the standard leaf-wetness / dew-formation proxy (disease pressure), and dew point <0°C alongside low `T2M_MIN` is the frost mechanism itself (frost forms when the surface cools to the dew/frost point and both are below freezing — see `FROST_DAYS`). |
| `FROST_DAYS` | days (0 or 1 per day) | "A frost day occurs when the 2m temperature cools to the dew point temperature and both are less than 0 C or 32 F." | `query_heat_frost_risk` | POWER's own direct frost flag — more reliable than inferring frost purely from a `T2M_MIN < threshold` rule of thumb, since it also requires the dew-point condition. |
| `GWETTOP` | 0–1 (fraction) | "The amount of water and water vapor present in the soil. Top indicates the upper 5 cm of soil. ... 0 for completely dry ... 1 for completely saturated." | `query_dry_spell_risk`, `query_sowing_window` | Topsoil moisture — what actually governs seed germination and early dry-spell stress, closer to the ground than rainfall totals alone. |
| `GWETROOT` | 0–1 (fraction) | "The amount of water ... available to plants in the root zone, generally ... the upper 1 m of soil ... 0 for completely dry ... 1 for completely saturated." | `calculate_crop_water_need`, `query_dry_spell_risk` | Root-zone moisture — the standard signal for "does this crop need irrigation now," complements rainfall-based water-need estimates. |
| `EVPTRNS` | MJ/m²/day | "The evapotranspiration energy flux at the surface of the earth." | `calculate_crop_water_need` | An *energy flux*, not a depth — convert to a water-equivalent ET in mm/day by dividing by the latent heat of vaporization of water (~2.45 MJ/kg): `ET_mm_per_day ≈ EVPTRNS / 2.45`. This is actual (not reference/ET0) evapotranspiration; treat it as a starting point for crop water balance, not a drop-in Penman-Monteith ET0 replacement. |

## Extended columns

Grabbed alongside the core set above so this pipeline's one full historical pull covers
everything agriculture-plausibly-relevant up front — going back for one more column later
means a second ~987-cell re-fetch, so the marginal cost of including these now (an extra
batched request per cell, not an extra full pass) is worth it. None of these back a named tool
in the current tool table yet; they're here for whichever future tool needs them.

| Column | Unit | POWER's definition | Notes |
|---|---|---|---|
| `GWETPROF` | 0–1 | "... the amount of water and water vapor present in the soil. Profile indicates the layer from the surface down to the bedrock ..." | Deep-drainage / long-cycle crop water modeling — `GWETROOT` is the more directly useful one for most annual crops. |
| `T2MWET` | °C | "The adiabatic saturation temperature ... measured by a thermometer covered in a water-soaked cloth ... at 2 meters." | Combined heat+humidity stress index (relevant to livestock/heat-stress tools, not in the current tool table). |
| `QV2M` | g/kg | "The ratio of the mass of water vapor to the total mass of air at 2 meters." | Largely redundant with `RH2M` + `T2M` for agronomic purposes; useful mainly if an ET0 formula wants specific humidity directly. |
| `WD2M` | degrees | "The average of the wind direction at 2 meters above the surface of the earth." | Only matters if a future spray-drift tool needs direction, not just speed (e.g. "wind blowing toward the neighboring field"). |
| `WD10M` | degrees | "The average of the wind direction at 10 meters above the surface of the earth." | Same as `WD2M`, above canopy height. |
| `ALLSKY_SFC_PAR_TOT` | MJ/m²/day | "The total (direct plus diffuse) Photosynthetically Active Radiation (PAR) incident on a horizontal plane ... under all sky conditions." | A more crop-growth-specific radiation signal than total `ALLSKY_SFC_SW_DWN` (PAR is the ~400-700nm slice plants actually use) — relevant if a future tool models biomass/yield rather than just drying conditions. |
| `CLRSKY_SFC_SW_DWN` | MJ/m²/day | "... solar irradiance ... under clear sky conditions." (a.k.a. clear-sky GHI) | `ALLSKY_SFC_SW_DWN / CLRSKY_SFC_SW_DWN` gives a cloudiness ratio — a cleaner "how sunny was it really" signal than `ALLSKY` alone for `query_solar_drying_days`. |
| `TSOIL1`…`TSOIL6` | °C | "The estimate of soil temperatures at layer N" — depths 0.018-0.099m, 0.099-0.294m, 0.294-0.680m, 0.680-1.443m, 1.443-2.949m, 2.949-10.0m respectively. | Germination-temperature thresholds for specific crops, if `query_sowing_window` ever wants soil temp rather than air temp. |
| `PRECSNO` | mm/day | "The snow precipitation at the surface of the earth." | Irrelevant for the plains/coastal districts most of the current 17-state seed covers; would matter only for hill-agriculture tools in Himachal/J&K/Uttarakhand's higher elevations. |
| `WS10M`, `WS10M_MAX`, `WS10M_MIN`, `WS10M_RANGE` | m/s | Wind speed at 10m — mean, max, min, range (POWER's own hourly-derived daily stats). | Only relevant if a tool ever needs above-canopy wind (e.g. wind-erosion risk); `WS2M`/`WS2M_MAX` already covers spray drift at crop height. |
| `WS50M`, `WS50M_MAX`, `WS50M_MIN`, `WS50M_RANGE` | m/s | Wind speed at 50m — mean, max, min, range. | Same, at turbine/mast height — not agriculture-relevant today, included for completeness/no-second-fetch reasons only. |

## Missing data

POWER fills unavailable cells with `-999` instead of a JSON `null`. `nasa_power_client.fetch_point_daily()` converts every `-999` to `NaN` before it ever reaches the saved parquet/csv — you will never see a literal `-999` in `weather_data/`. Observed NaN rates in testing were ~0.3-0.5%, concentrated in the most recent few days per cell (provisional/not-yet-finalized data lags a bit behind "today").

## Parameters that exist but still aren't fetched

The 40 columns above (5 key/label columns + 35 weather parameters) don't exhaust POWER's
catalog — 152 total parameters exist for `community=AG`/daily. What's excluded now is excluded on
purpose: things like cloud-top/bottom temperature, air mass, precipitable water, and
renewable-energy-oriented radiation variants that have no plausible path to any tool in the
current tool table. Full catalog, if a genuinely new need comes up:
`GET https://power.larc.nasa.gov/api/system/manager/parameters?community=AG&temporal=daily`
