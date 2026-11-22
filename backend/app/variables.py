"""
Allow-lists for the data API (SEC-19): which variables, land uses and resolutions exist.

Column names used in SQL come only from VARIABLES below, never from the request.
Units are read from `sensor_variables` (the pipeline's single source); the units
here are a fallback and are checked against data_pipeline/config.py by a test.
"""
from __future__ import annotations

from typing import Literal

# The nine environmental variables of BUILD_PROMPT §4.2 (AQI and battery voltage are device
# diagnostics, not shown on the dashboard: DECISIONS.md D-029).
VARIABLES: dict[str, dict[str, str]] = {
    "temperature_c": {"label": "Temperature", "unit": "°C"},
    "humidity_pct": {"label": "Relative humidity", "unit": "%"},
    "pm1": {"label": "PM1", "unit": "µg/m³"},
    "pm25": {"label": "PM2.5", "unit": "µg/m³"},
    "pm10": {"label": "PM10", "unit": "µg/m³"},
    "no2_ppb": {"label": "NO₂", "unit": "ppb"},
    "co_ppb": {"label": "CO", "unit": "ppb"},
    "co2_ppm": {"label": "CO₂", "unit": "ppm"},
    "pressure_hpa": {"label": "Air pressure", "unit": "hPa"},
}
Variable = Literal["temperature_c", "humidity_pct", "pm1", "pm25", "pm10", "no2_ppb", "co_ppb", "co2_ppm",
                   "pressure_hpa"]

LAND_USES = ("Residential", "Industrial", "Parkland", "Transport corridor", "Commercial")
LandUse = Literal["Residential", "Industrial", "Parkland", "Transport corridor", "Commercial"]

Resolution = Literal["hour", "day", "month", "season", "raw"]
RAW_MAX_DAYS = 7          # raw readings only for short ranges (BUILD_PROMPT §5)
HOUR_MAX_DAYS = 92        # keeps hourly responses under Vercel's 4.5 MB response limit (D-029)
HEATMAP_MAX_DAYS = 366    # month x hour grid from hourly aggregates; response stays small (<= 13 x 24 cells)
MAX_SENSOR_IDS = 20

SEASON_START_MONTH = {"Summer": 12, "Autumn": 3, "Winter": 6, "Spring": 9}   # southern hemisphere


def flag_hits(flags: str | None, variable: str) -> bool:
    """True if a reading's qc_flags (';'-separated) flag THIS variable. Same rule as the
    pipeline's etl.flag_hits (a test keeps them identical)."""
    if not flags:
        return False
    prefix = variable.split("_")[0] if variable.endswith(("_c", "_pct", "_ppb", "_ppm", "_hpa", "_v")) else variable
    return any(f.startswith(prefix + "_") for f in flags.split(";") if f)

# Device families the pipeline can parse (data_pipeline/config.py COLUMN_MAP; a test keeps them equal)
DEVICE_FAMILIES = ("mcc_aq", "libelium", "lora_r270")
DeviceFamily = Literal["mcc_aq", "libelium", "lora_r270"]

# Maribyrnong municipality, approximate bounding box (BUILD_PROMPT §4.5), decimal degrees
LAT_BOUNDS = (-37.835, -37.760)
LON_BOUNDS = (144.840, 144.925)
