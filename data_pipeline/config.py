"""
Central configuration for the Maribyrnong environmental data pipeline.

Everything that is a *decision* (which columns to keep, what units they are in,
what counts as a valid reading, which health thresholds apply) lives here so it
can be reviewed, justified in the Technical Implementation Document, and changed
without touching pipeline logic.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
SQLITE_PATH = PROCESSED_DIR / "environment.db"
SENSORS_CSV = Path(__file__).resolve().parent / "config" / "sensors.csv"
SCHEMA_SQLITE = Path(__file__).resolve().parent / "schema_sqlite.sql"
SCHEMA_POSTGRES = ROOT / "database" / "01_schema.sql"


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=value lines). Real environment variables take precedence."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")

# Neon connection for the pipeline: pipeline_user role on the DIRECT (non-pooler)
# host, sslmode=require. If unset, the pipeline uses a local SQLite file instead.
DATABASE_URL = os.environ.get("PIPELINE_DATABASE_URL") or f"sqlite:///{SQLITE_PATH}"

# Private Vercel Blob store holding the original council CSVs (SEC-15).
# The SDK reads BLOB_READ_WRITE_TOKEN from the environment outside Vercel; on
# Vercel it uses short-lived OIDC tokens automatically. Server-side only.
BLOB_READ_WRITE_TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN", "")
RAW_PREFIX = os.environ.get("RAW_BLOB_PREFIX", "raw/")

LOCAL_TZ = "Australia/Melbourne"  # Maribyrnong; same offsets as the export's Australia/Sydney column

# Canonical variables stored in the readings table (column name -> unit shown in UI)
CANONICAL_UNITS = {
    "temperature_c": "°C",
    "humidity_pct": "%",
    "pm1": "µg/m³",
    "pm25": "µg/m³",
    "pm10": "µg/m³",
    "no2_ppb": "ppb",
    "co_ppb": "ppb",
    "co2_ppm": "ppm",
    "pressure_hpa": "hPa",
    "aqi": "index",
    "battery_v": "V",
}

# Per device family: raw column -> (canonical column, multiplier to canonical unit)
# The Ubidots export repeats created_at_<var>/context_<var> for every variable; those are
# ingestion metadata (context is always "{}") and are dropped. *lasthour columns are the
# device's own rolling averages - we drop them and compute our own hourly aggregates so
# every sensor is averaged the same way.
COLUMN_MAP = {
    "mcc_aq": {
        "temperature": ("temperature_c", 1),
        "humidity": ("humidity_pct", 1),
        "pm1": ("pm1", 1),
        "pm25": ("pm25", 1),
        "pm10": ("pm10", 1),
        "no2": ("no2_ppb", 1),      # assumed ppb (integer steps of 10) - confirm with council
        "co": ("co_ppb", 1),        # assumed ppb - confirm with council
        "co2": ("co2_ppm", 1),
        "aqi": ("aqi", 1),
    },
    "libelium": {
        "temperature": ("temperature_c", 1),
        "humidity": ("humidity_pct", 1),
        "pm1": ("pm1", 1),
        "pm25": ("pm25", 1),
        "pm10": ("pm10", 1),
        "no2": ("no2_ppb", 1000),   # Libelium reports ppm (values ~0.04); x1000 -> ppb
        "co2": ("co2_ppm", 1),
        "pressure": ("pressure_hpa", 0.01),  # Pa -> hPa
        "batteryvoltage": ("battery_v", 1),
    },
    "lora_r270": {
        "temperature": ("temperature_c", 1),
        "pressure": ("pressure_hpa", 1),     # already hPa
        "battery": ("battery_v", 1),
    },
}

# Plausible physical ranges (inclusive), applied AFTER unit conversion.
# temperature / pm25 / pm10 / humidity ranges come straight from the proposal's
# Algorithm 1 so the implementation matches the documented design.
VALID_RANGES = {
    "temperature_c": (-20, 60),
    "humidity_pct": (0, 100),
    "pm1": (0, 500),
    "pm25": (0, 500),
    "pm10": (0, 600),
    "no2_ppb": (0, 2000),
    "co_ppb": (0, 50000),
    "co2_ppm": (250, 5000),   # below ~250 ppm is physically impossible outdoors -> sensor absent/faulty
    "pressure_hpa": (900, 1100),
    "aqi": (0, 500),
    "battery_v": (0, 5),
}

# Quality-control rules that FLAG (keep) rather than reject
FLATLINE_MIN_RUN = 12            # identical temperature for >= 12 consecutive readings (2-3 h)
HUMIDITY_SATURATION = 100.0      # Libelium units sit at 100% for long periods (condensation)
SPIKE_FACTOR = 10                # value > 10x local rolling median AND > SPIKE_FLOOR
SPIKE_FLOOR = {"pm1": 50, "pm25": 50, "pm10": 80}
SPIKE_WINDOW = 7                 # readings in centred rolling window

# A sensor whose column is >95% zero is treated as "not fitted" and the whole column nulled
NOT_FITTED_ZERO_SHARE = 0.95

# Aggregation completeness: a daily mean is only "valid" for compliance comparisons
# if >= 75% of expected readings are present (standard air-monitoring data-capture rule).
MIN_COMPLETENESS_PCT = 75.0
EXPECTED_INTERVAL_MIN = {"mcc_aq": 10, "libelium": 15, "lora_r270": 15}

# Health / heat thresholds used for exceedance flags. Stored in the DB `thresholds`
# table so admins can change them later (proposal risk R24). VERIFY against current
# NEPM (Ambient Air Quality) and EPA Victoria guidance before final submission.
THRESHOLDS = [
    # variable, period, operator, value, label, source
    ("pm25", "day", ">", 25.0, "PM2.5 24-hour standard", "NEPM (Ambient Air Quality) 24-hr PM2.5"),
    ("pm10", "day", ">", 50.0, "PM10 24-hour standard", "NEPM (Ambient Air Quality) 24-hr PM10"),
    ("temperature_c", "day_max", ">=", 35.0, "Hot day (max >= 35°C)", "Common heat-health trigger - confirm with BoM/DH Victoria"),
    ("temperature_c", "day_max", ">=", 40.0, "Extreme heat day (max >= 40°C)", "Common heat-health trigger - confirm"),
]
