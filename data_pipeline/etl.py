"""
Maribyrnong Environmental Data Pipeline (Extract -> Transform/Validate -> Load -> Aggregate)

Turns the raw Ubidots CSV exports supplied by Maribyrnong City Council into a
structured relational database the website's API reads from.

Database target:
    PIPELINE_DATABASE_URL in .env set  -> Neon PostgreSQL (shared team database; use the DIRECT host)
    not set                            -> local SQLite file data/processed/environment.db

Usage:
    python data_pipeline/etl.py                  # ingest everything in data/raw
    python data_pipeline/etl.py --upload-raw     # also archive original CSVs in the private Vercel Blob store
    python data_pipeline/etl.py --from-storage   # download + hash-verify archived CSVs, then ingest
    python data_pipeline/etl.py --rebuild        # clear pipeline data and start fresh
    python data_pipeline/etl.py --export-csv     # also write clean CSVs to data/processed
    python data_pipeline/etl.py --file path.csv  # ingest one file (e.g. a new monthly export)
    python data_pipeline/etl.py --sqlite         # force local SQLite even if Neon is configured

Design principles (see README for justification):
  * Never silently discard data: every rejected value is written to error_log.
  * Reject individual bad VALUES, not whole rows (a bad pressure reading should
    not throw away a good temperature reading taken at the same moment).
  * Flag suspicious-but-possible values (spikes, saturation, flatlines) instead of
    deleting them, so real pollution events (e.g. smoke) remain visible (risk R10).
  * Idempotent: re-running on the same file inserts nothing new.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C  # noqa: E402
from db import Database, df_to_rows, redact  # noqa: E402

VALUE_COLS = list(C.CANONICAL_UNITS.keys())


# --------------------------------------------------------------------------- helpers
def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def season_of(month: int) -> str:
    return {12: "Summer", 1: "Summer", 2: "Summer",
            3: "Autumn", 4: "Autumn", 5: "Autumn",
            6: "Winter", 7: "Winter", 8: "Winter"}.get(month, "Spring")


def connect(url: str = None) -> Database:
    """Open the target database. SQLite schema is created automatically; the Neon
    schema is created once by the project owner (database/01_schema.sql + 02_security.sql)."""
    db = Database(url or C.DATABASE_URL)
    if db.dialect == "sqlite":
        db.apply_schema(C.SCHEMA_SQLITE)
        migrate_sqlite(db)
    return db


# Columns added after the first release, for SQLite files created before them (SQLite has
# no ADD COLUMN IF NOT EXISTS). Fixed literals only. Postgres: 01_schema.sql has the ALTERs.
SQLITE_ADDED_COLUMNS = {
    ("sensors", "sensitive_receptor"):
        "ALTER TABLE sensors ADD COLUMN sensitive_receptor INTEGER NOT NULL DEFAULT 0",
}


def migrate_sqlite(db: Database) -> None:
    for (table, column), statement in SQLITE_ADDED_COLUMNS.items():
        existing = {r[1] for r in db.conn.execute(f"PRAGMA table_info({table})").fetchall()}  # noqa: S608
        if column not in existing:
            db.conn.execute(statement)
    db.commit()


PIPELINE_TABLES = ["exceedances", "aggregates", "error_log", "readings", "sensor_variables", "ingestion_runs"]


def clear_pipeline_data(db: Database):
    """--rebuild: remove pipeline-generated data. Never touches users, roles, audit_log or reports."""
    for t in PIPELINE_TABLES:
        db.execute(f"DELETE FROM {t}")
    db.commit()


# --------------------------------------------------------------------------- sensors
def sync_sensor_registry(conn: Database) -> pd.DataFrame:
    """Upsert config/sensors.csv into the sensors table. Returns registry with sensor_id."""
    reg = pd.read_csv(C.SENSORS_CSV, dtype=str).fillna("")
    for _, r in reg.iterrows():
        conn.execute(
            """INSERT INTO sensors (sensor_code, sensor_name, device_family, latitude, longitude,
                   location_verified, land_use, installation_date, status, notes, sensitive_receptor)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(sensor_code) DO UPDATE SET
                   sensor_name=excluded.sensor_name, device_family=excluded.device_family,
                   latitude=excluded.latitude, longitude=excluded.longitude,
                   location_verified=excluded.location_verified, land_use=excluded.land_use,
                   notes=excluded.notes, sensitive_receptor=excluded.sensitive_receptor""",
            (r.sensor_code, r.sensor_name, r.device_family,
             float(r.latitude) if r.latitude else None,
             float(r.longitude) if r.longitude else None,
             int(r.location_verified or 0), r.land_use,
             r.installation_date or None, r.status or "Active", r.notes,
             int(r.get("sensitive_receptor") or 0)),
        )
    conn.commit()
    ids = conn.query_df("SELECT sensor_id, sensor_code FROM sensors")
    return reg.merge(ids, on="sensor_code")


def match_sensor(filename: str, registry: pd.DataFrame) -> pd.Series | None:
    hits = registry[registry.file_match.apply(lambda m: m and m in filename)]
    return hits.iloc[0] if len(hits) == 1 else None


# --------------------------------------------------------------------------- shared rules
# Used by the batch `transform` (CSV files) and by `transform_live` (one device reading,
# POST /api/ingest), so files and live devices follow ONE rule set (BUILD_PROMPT §4.6).
def reject_out_of_range(df: pd.DataFrame, variables: list[str], sensor_id: int, ts_str: pd.Series,
                        errors: list[dict]) -> int:
    """Null values outside VALID_RANGES and log each one. Returns how many were rejected."""
    rejected = 0
    for canon in variables:
        lo, hi = C.VALID_RANGES[canon]
        s = df[canon]
        bad = s.notna() & ((s < lo) | (s > hi))
        rejected += int(bad.sum())
        for i in df.index[bad]:
            errors.append(dict(sensor_id=sensor_id, ts_utc=ts_str[i], error_type="out_of_range",
                               variable=canon, raw_value=repr(float(s[i])),
                               description=f"Outside plausible range [{lo}, {hi}] {C.CANONICAL_UNITS[canon]}"))
        df.loc[bad, canon] = np.nan
    return rejected


def quality_flags(df: pd.DataFrame, variables: set[str]) -> tuple[pd.Series, int]:
    """qc_flags per row (';'-joined, None if clean) and the number of flagged values.
    Rows must be in time order; flatline and spike rules look at neighbouring readings."""
    flag_cols: dict[str, pd.Series] = {}
    if "humidity_pct" in variables:
        flag_cols["humidity_saturated"] = df.humidity_pct >= C.HUMIDITY_SATURATION
    if "temperature_c" in variables:
        t = df.temperature_c
        run_len = t.groupby((t != t.shift()).cumsum()).transform("size")
        flag_cols["temperature_flatline"] = (run_len >= C.FLATLINE_MIN_RUN) & t.notna()
    for canon, floor in C.SPIKE_FLOOR.items():
        if canon in variables:
            s = df[canon]
            med = s.rolling(C.SPIKE_WINDOW, center=True, min_periods=3).median()
            flag_cols[f"{canon}_spike"] = (s > floor) & (s > C.SPIKE_FACTOR * med.clip(lower=0.1))
    if not flag_cols:
        return pd.Series([None] * len(df), index=df.index, dtype=object), 0
    fdf = pd.DataFrame(flag_cols).fillna(False).astype(bool)
    labels = fdf.apply(lambda col: np.where(col, col.name + ";", ""))
    return labels.sum(axis=1).str.rstrip(";").replace("", None), int(fdf.values.sum())


# --------------------------------------------------------------------------- transform
def transform(raw: pd.DataFrame, family: str, sensor_id: int):
    """
    Returns (clean_df, errors_df, stats) where clean_df has ts_utc, ts_local,
    canonical value columns and qc_flags.
    """
    errors: list[dict] = []
    stats = {"rows_read": len(raw), "values_rejected": 0, "values_flagged": 0,
             "rows_duplicate": 0, "variables": {}}

    # 1. Timestamps: epoch ms (device measurement time) -> UTC. created_at_* is upload
    #    time (lags up to ~20 min on MCC units) so it is NOT used as the reading time.
    ts = pd.to_datetime(pd.to_numeric(raw["timestamp"], errors="coerce"), unit="ms", utc=True)
    bad_ts = ts.isna()
    for i in raw.index[bad_ts]:
        errors.append(dict(sensor_id=sensor_id, ts_utc=None, error_type="invalid_timestamp",
                           variable="timestamp", raw_value=str(raw.at[i, "timestamp"]),
                           description="Timestamp missing or not parseable"))
    df = pd.DataFrame({"ts": ts.dt.floor("s")})[~bad_ts]
    raw = raw[~bad_ts]

    # 2. Map raw -> canonical columns with unit conversion
    mapping = C.COLUMN_MAP[family]
    for raw_col, (canon, mult) in mapping.items():
        if raw_col in raw.columns:
            df[canon] = pd.to_numeric(raw[raw_col], errors="coerce") * mult
            stats["variables"][canon] = raw_col
    for col in VALUE_COLS:
        if col not in df.columns:
            df[col] = np.nan

    # 3. Duplicates on (sensor, second)
    df = df.sort_values("ts")
    dup = df.ts.duplicated(keep="first")
    stats["rows_duplicate"] = int(dup.sum())
    for t in df.ts[dup]:
        errors.append(dict(sensor_id=sensor_id, ts_utc=t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                           error_type="duplicate", variable=None, raw_value=None,
                           description="Duplicate sensor_id + timestamp; first record kept"))
    df = df[~dup].reset_index(drop=True)

    # 4. "Not fitted" detection: a column that is ~always zero is a missing sensor module,
    #    not clean air. Null the whole column and log ONE summary error.
    for canon in list(stats["variables"]):
        s = df[canon]
        if s.notna().any() and (s == 0).mean() >= C.NOT_FITTED_ZERO_SHARE:
            errors.append(dict(sensor_id=sensor_id, ts_utc=None, error_type="not_fitted",
                               variable=canon, raw_value=f"{int((s == 0).sum())} zero values",
                               description=f"{(s == 0).mean():.1%} of readings are 0; treated as sensor not fitted"))
            stats["values_rejected"] += int(s.notna().sum())
            df[canon] = np.nan
            stats["variables"].pop(canon)

    # 5. Range validation - reject individual values, log each one
    ts_str = df.ts.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    stats["values_rejected"] += reject_out_of_range(df, list(stats["variables"]), sensor_id, ts_str, errors)

    # 6. Quality flags (value kept, but marked)
    df["qc_flags"], stats["values_flagged"] = quality_flags(df, set(stats["variables"]))
    df["ts_utc"] = ts_str
    df["ts_local"] = df.ts.dt.tz_convert(C.LOCAL_TZ).dt.strftime("%Y-%m-%dT%H:%M:%S%z")
    return df, pd.DataFrame(errors), stats


# --------------------------------------------------------------------------- load
def ingest_file(conn: Database, path: Path, registry: pd.DataFrame, force=False, upload_raw=False,
                sensor: pd.Series | None = None) -> dict | None:
    """Load one CSV. The sensor is found by file name in the registry, unless the caller
    names it (`sensor`: the admin upload chooses it explicitly, D-033)."""
    sensor = sensor if sensor is not None else match_sensor(path.name, registry)
    if sensor is None:
        conn.execute("INSERT INTO error_log (error_type, raw_value, description) VALUES (?,?,?)",
                     ("unknown_sensor", path.name, "File does not match any sensor in config/sensors.csv"))
        conn.commit()
        print(f"  !! {path.name}: no matching sensor in registry - logged and skipped")
        return None
    sid = int(sensor.sensor_id)
    digest = sha256(path)
    if not force and conn.scalar("SELECT 1 FROM ingestion_runs WHERE file_sha256=? AND finished_at IS NOT NULL",
                                 (digest,)):
        print(f"  -- {sensor.sensor_code}: file already ingested (sha256 match), skipping")
        return None

    storage_path = None
    if upload_raw:
        import storage
        storage_path = storage.upload_raw(path, digest)
        print(f"     archived original -> blob:{storage_path}")

    run_id = conn.scalar(
        "INSERT INTO ingestion_runs (source_file, file_sha256, sensor_id, storage_path, started_at) "
        "VALUES (?,?,?,?,?) RETURNING run_id", (path.name, digest, sid, storage_path, now_iso()))

    raw = pd.read_csv(path, low_memory=False)
    if "deviceid" in raw.columns and raw.deviceid.notna().any():
        conn.execute("UPDATE sensors SET hardware_id=? WHERE sensor_id=?",
                     (str(int(raw.deviceid.dropna().iloc[0])), sid))

    clean, errors, stats = transform(raw, sensor.device_family, sid)

    cols = ["sensor_id", "ts_utc", "ts_local", *VALUE_COLS, "qc_flags", "ingestion_run_id"]
    rows = df_to_rows(clean.assign(sensor_id=sid, ingestion_run_id=run_id)[cols])
    inserted = conn.bulk_insert("readings", cols, rows, conflict_cols=["sensor_id", "ts_utc"])
    stats["rows_kept"] = len(rows)   # rows offered to the database; kept - inserted = already stored

    if len(errors):
        ecols = ["sensor_id", "ts_utc", "error_type", "variable", "raw_value", "description", "ingestion_run_id"]
        conn.bulk_insert("error_log", ecols, df_to_rows(errors.assign(ingestion_run_id=run_id)[ecols]))

    for canon, raw_col in stats["variables"].items():
        conn.execute("""INSERT INTO sensor_variables (sensor_id, variable, unit, raw_column) VALUES (?,?,?,?)
                        ON CONFLICT (sensor_id, variable) DO UPDATE SET unit=excluded.unit, raw_column=excluded.raw_column""",
                     (sid, canon, C.CANONICAL_UNITS[canon], raw_col))

    conn.execute("""UPDATE sensors SET
                      first_reading_utc=(SELECT MIN(ts_utc) FROM readings WHERE sensor_id=?),
                      last_reading_utc =(SELECT MAX(ts_utc) FROM readings WHERE sensor_id=?)
                    WHERE sensor_id=?""", (sid, sid, sid))
    conn.execute("""UPDATE ingestion_runs SET rows_read=?, rows_inserted=?, rows_duplicate=?,
                    values_rejected=?, values_flagged=?, finished_at=? WHERE run_id=?""",
                 (stats["rows_read"], inserted, stats["rows_duplicate"], stats["values_rejected"],
                  stats["values_flagged"], now_iso(), run_id))
    conn.commit()
    print(f"  ok {sensor.sensor_code:8s} read={stats['rows_read']:>6} inserted={inserted:>6} "
          f"rejected_values={stats['values_rejected']:>6} flagged_values={stats['values_flagged']:>6}")
    return stats


# --------------------------------------------------------------------------- aggregate
def flag_hits(flags: str, variable: str) -> bool:
    """True if a reading's qc_flags (';'-separated) flag THIS variable, e.g.
    'pm25_spike' -> pm25, 'temperature_flatline' -> temperature_c, 'humidity_saturated' -> humidity_pct."""
    prefix = variable.split("_")[0] if variable.endswith(("_c", "_pct", "_ppb", "_ppm", "_hpa", "_v")) else variable
    return any(f.startswith(prefix + "_") for f in flags.split(";") if f)


def _clean_differences(all_rows: list[tuple], clean_rows: list[tuple]) -> list[tuple]:
    """Clean rows that differ from their 'all' row, plus an explicit empty clean row
    (n=0, no values, invalid) for every bucket whose values were ALL flagged."""
    key = lambda r: (r[1], r[2], r[4])          # (period, bucket_start_local, variable)
    stats = lambda r: (r[5], r[6], r[7], r[8])  # (mean, min, max, n)
    clean_by_key = {key(r): r for r in clean_rows}
    out = []
    for r in all_rows:
        c = clean_by_key.get(key(r))
        if c is None:
            out.append(r[:5] + (None, None, None, 0, 0.0, 0, "clean"))
        elif stats(c) != stats(r):
            out.append(c)
    return out


def _aggregate_rows(df: pd.DataFrame, vars_: list[str], sensor_id: int, interval: int, qc_mode: str) -> list[tuple]:
    """Hourly/daily/monthly mean/min/max/count and completeness for one sensor."""
    rows: list[tuple] = []
    long = df.melt(id_vars=["ts"], value_vars=vars_, var_name="variable", value_name="value").dropna()
    local = long.ts.dt.tz_localize(None)
    for period, pfreq, fmt in (("hour", "h", "%Y-%m-%d %H:00"), ("day", "D", "%Y-%m-%d"), ("month", "M", "%Y-%m")):
        long["bucket"] = local.dt.to_period(pfreq)
        g = long.groupby(["bucket", "variable"], observed=True).value.agg(["mean", "min", "max", "count"]).reset_index()
        starts = g.bucket.dt.start_time
        if period == "hour":
            expected = 60 / interval
        elif period == "day":
            expected = 1440 / interval
        else:
            expected = g.bucket.dt.days_in_month * 1440 / interval
        comp = (100 * g["count"] / expected).clip(upper=100).round(1)
        block = pd.DataFrame({
            "sensor_id": sensor_id, "period": period,
            "bucket_start_local": starts.dt.strftime(fmt),
            "season": starts.dt.month.map(season_of), "variable": g.variable,
            "mean": g["mean"].round(3), "min": g["min"], "max": g["max"],
            "n": g["count"].astype(int), "completeness_pct": comp,
            "is_valid": (comp >= C.MIN_COMPLETENESS_PCT).astype(int), "qc_mode": qc_mode})
        rows.extend(df_to_rows(block))
    return rows


def seed_thresholds(conn: Database) -> None:
    """Insert the configured thresholds once. Admins may edit a value afterwards, so an
    existing threshold is recognised by (variable, period, label), not by its value; otherwise
    a rebuild would add the original back next to the edited one; one with the same value
    (the table's unique key) also counts as existing (DECISIONS.md D-033)."""
    for var, per, op, val, label, src in C.THRESHOLDS:
        conn.execute("INSERT INTO thresholds (variable, period, operator, value, label, source) "
                     "SELECT CAST(? AS TEXT), CAST(? AS TEXT), CAST(? AS TEXT), CAST(? AS DOUBLE PRECISION), "
                     "CAST(? AS TEXT), CAST(? AS TEXT) WHERE NOT EXISTS "
                     "(SELECT 1 FROM thresholds WHERE variable = ? AND period = ? AND (label = ? OR value = ?))",
                     (var, per, op, val, label, src, var, per, label, val))


def sensor_aggregate_rows(df: pd.DataFrame, vars_: list[str], sensor_id: int, family: str) -> list[tuple]:
    """Hourly/daily/monthly aggregate rows ('all' + sparse 'clean') for one sensor's readings
    (columns ts_utc, qc_flags and the variables). Used by full rebuilds and by live ingestion,
    which passes only the month around a new reading."""
    for v in vars_:
        df[v] = pd.to_numeric(df[v], errors="coerce")
    if df.empty:
        return []
    df["ts"] = pd.to_datetime(df.ts_utc, utc=True).dt.tz_convert(C.LOCAL_TZ)
    # Saturated humidity is excluded from averages (kept in raw readings for inspection)
    flags = df.qc_flags.fillna("")
    if "humidity_pct" in df:
        df.loc[flags.str.contains("humidity_saturated"), "humidity_pct"] = np.nan
    interval = C.EXPECTED_INTERVAL_MIN[family]

    # "all": every kept value (spikes may be real pollution events, risk R10).
    # "clean": additionally leave out each value whose OWN variable is QC-flagged,
    # for the dashboard's "Exclude flagged readings" toggle (DECISIONS.md D-028).
    # Clean rows are stored only where they differ from "all" (sparse): readers
    # use the clean row when present and fall back to the "all" row otherwise.
    clean = df.copy()
    for v in vars_:
        clean.loc[flags.apply(lambda f, v=v: flag_hits(f, v)), v] = np.nan
    all_rows = _aggregate_rows(df, vars_, sensor_id, interval, "all")
    return all_rows + _clean_differences(all_rows, _aggregate_rows(clean, vars_, sensor_id, interval, "clean"))


def transform_live(values: dict[str, float | None], ts: pd.Timestamp, family: str, sensor_id: int,
                   recent: pd.DataFrame) -> tuple[dict, list[dict], dict]:
    """One device reading (UC4), with the SAME rules as file loads: unit conversion, range
    checks and quality flags. `values` uses the device's own field names (COLUMN_MAP);
    `recent` holds the sensor's previous readings (ts_utc + canonical columns, oldest first)
    so the flatline and spike rules see the same neighbours a file load would.
    "Not fitted" detection needs a whole file and is not applied to single readings."""
    errors: list[dict] = []
    row = {"ts": ts.floor("s")}
    variables = []
    for raw_name, (canon, mult) in C.COLUMN_MAP[family].items():
        if values.get(raw_name) is not None:
            row[canon] = float(values[raw_name]) * mult
            variables.append(canon)
    df = pd.DataFrame([row])
    for col in VALUE_COLS:
        if col not in df.columns:
            df[col] = np.nan
    ts_str = df.ts.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    rejected = reject_out_of_range(df, variables, sensor_id, ts_str, errors)

    context = recent.copy()
    for col in VALUE_COLS:
        context[col] = pd.to_numeric(context[col], errors="coerce") if col in context else np.nan
    window = pd.concat([context[VALUE_COLS], df[VALUE_COLS]], ignore_index=True)
    flags, _ = quality_flags(window, {v for v in variables if df[v].notna().iloc[0]})
    qc = flags.iloc[-1] if isinstance(flags.iloc[-1], str) and flags.iloc[-1] else None
    clean = df.iloc[0]
    out = {c: (None if pd.isna(clean[c]) else float(clean[c])) for c in VALUE_COLS}
    out.update(ts_utc=ts_str.iloc[0], ts_local=ts.tz_convert(C.LOCAL_TZ).strftime("%Y-%m-%dT%H:%M:%S%z"),
               qc_flags=qc)
    stats = {"variables": variables, "values_rejected": rejected,
             "flags": qc.split(";") if qc else []}
    return out, errors, stats


def build_aggregates(conn: Database, sensor_id: int | None = None):
    """Rebuild hourly/daily/monthly aggregates + exceedances for all sensors, or for one
    sensor only (`sensor_id`: after an admin upload, BUILD_PROMPT §4.5, D-033)."""
    if sensor_id is None:
        conn.execute("DELETE FROM aggregates")
        conn.execute("DELETE FROM exceedances")
        sensors = conn.query_df("SELECT sensor_id, device_family FROM sensors")
    else:
        conn.execute("DELETE FROM aggregates WHERE sensor_id = ?", (int(sensor_id),))
        conn.execute("DELETE FROM exceedances WHERE sensor_id = ?", (int(sensor_id),))
        sensors = conn.query_df("SELECT sensor_id, device_family FROM sensors WHERE sensor_id = ?", (int(sensor_id),))
    variables = conn.query_df("SELECT sensor_id, variable FROM sensor_variables")

    out = []
    for _, s in sensors.iterrows():
        vars_ = variables[variables.sensor_id == s.sensor_id].variable.tolist()
        if not vars_:
            continue
        df = conn.query_df(f"SELECT ts_utc, qc_flags, {', '.join(vars_)} FROM readings WHERE sensor_id=?",
                           (int(s.sensor_id),))
        out.extend(sensor_aggregate_rows(df, vars_, int(s.sensor_id), s.device_family))
    conn.bulk_insert("aggregates", ["sensor_id", "period", "bucket_start_local", "season", "variable", "mean",
                                    "min", "max", "n", "completeness_pct", "is_valid", "qc_mode"], out)

    if sensor_id is None:   # a one-sensor rebuild (admin upload) leaves thresholds alone
        seed_thresholds(conn)
    # Exceedances computed from VALID daily aggregates only
    for th_id, var, per, op, val in conn.execute(
            "SELECT threshold_id, variable, period, operator, value FROM thresholds").fetchall():
        col = "mean" if per == "day" else "max"
        if op not in (">", ">="):  # operator is interpolated into SQL, so allow-list it
            raise ValueError(f"Invalid threshold operator {op!r}")
        conn.execute(f"""INSERT INTO exceedances (sensor_id, threshold_id, date_local, observed_value, completeness_pct)
                         SELECT sensor_id, CAST(? AS INTEGER), bucket_start_local, {col}, completeness_pct
                         FROM aggregates WHERE period='day' AND qc_mode='all' AND variable=? AND is_valid=1
                           AND {col} {op} ? AND (CAST(? AS INTEGER) IS NULL OR sensor_id = ?)""",
                     (th_id, var, val, sensor_id, sensor_id))
    conn.commit()
    print(f"  aggregates: {len(out):,} rows | exceedances: "
          f"{conn.scalar('SELECT COUNT(*) FROM exceedances'):,}")


# --------------------------------------------------------------------------- reporting
def write_quality_report(conn: Database, path: Path):
    q = conn.query_df
    runs = q("""SELECT s.sensor_code, s.sensor_name, r.rows_read, r.rows_inserted, r.rows_duplicate,
                       r.values_rejected, r.values_flagged
                FROM ingestion_runs r JOIN sensors s USING(sensor_id) WHERE r.finished_at IS NOT NULL
                ORDER BY s.sensor_code""")
    cover = q("""SELECT sensor_code, first_reading_utc, last_reading_utc, land_use,
                        CASE location_verified WHEN 1 THEN 'yes' ELSE 'NO - confirm' END AS location_verified
                 FROM sensors ORDER BY sensor_code""")
    errs = q("""SELECT s.sensor_code, e.error_type, e.variable, COUNT(*) AS n
                FROM error_log e LEFT JOIN sensors s USING(sensor_id)
                GROUP BY 1,2,3 ORDER BY 1,4 DESC""")
    flags = q("""SELECT s.sensor_code, r.qc_flags FROM readings r JOIN sensors s USING(sensor_id)
                 WHERE r.qc_flags IS NOT NULL""")
    flag_counts = (flags.assign(flag=flags.qc_flags.str.split(";")).explode("flag")
                   .groupby(["sensor_code", "flag"]).size().reset_index(name="n")) if len(flags) else flags
    daycomp = q("""SELECT s.sensor_code, ROUND(CAST(AVG(a.completeness_pct) AS NUMERIC), 1) AS avg_daily_completeness_pct,
                          SUM(a.is_valid) AS valid_days, COUNT(*) AS days_with_data
                   FROM aggregates a JOIN sensors s USING(sensor_id)
                   WHERE a.period='day' AND a.qc_mode='all' AND a.variable='temperature_c'
                   GROUP BY 1 ORDER BY 1""")
    exc = q("""SELECT s.sensor_code, t.label, COUNT(*) AS days
               FROM exceedances e JOIN sensors s USING(sensor_id) JOIN thresholds t USING(threshold_id)
               GROUP BY 1,2 ORDER BY 1,2""")

    md = ["# Data Quality Report", f"_Generated {now_iso()} by data_pipeline/etl.py_", "",
          "## Ingestion summary", runs.to_markdown(index=False), "",
          "## Coverage and metadata", cover.to_markdown(index=False), "",
          "## Daily completeness (temperature)", daycomp.to_markdown(index=False), "",
          "## Rejected values (error_log)", errs.to_markdown(index=False), "",
          "## Flagged values (kept, marked in qc_flags)",
          flag_counts.to_markdown(index=False) if len(flag_counts) else "_none_", "",
          "## Threshold exceedance days", exc.to_markdown(index=False) if len(exc) else "_none_", ""]
    path.write_text("\n".join(md), encoding="utf-8")
    print(f"  quality report -> {path.relative_to(C.ROOT)}")


def export_csv(conn: Database):
    out = C.PROCESSED_DIR
    out.mkdir(parents=True, exist_ok=True)
    conn.query_df("SELECT * FROM sensors").to_csv(out / "sensors.csv", index=False)
    conn.query_df("""SELECT s.sensor_code, r.* FROM readings r JOIN sensors s USING(sensor_id)
                     ORDER BY sensor_code, ts_utc""").to_csv(out / "readings_clean.csv", index=False)
    conn.query_df("""SELECT s.sensor_code, a.* FROM aggregates a JOIN sensors s USING(sensor_id)
                     WHERE period IN ('day','month') AND qc_mode='all'""").to_csv(out / "aggregates_daily_monthly.csv", index=False)
    print(f"  CSV exports -> {out.relative_to(C.ROOT)}/")


# --------------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rebuild", action="store_true", help="clear pipeline tables and rebuild from scratch")
    ap.add_argument("--file", type=Path, help="ingest a single CSV file")
    ap.add_argument("--force", action="store_true", help="re-ingest files already seen (duplicates still ignored)")
    ap.add_argument("--export-csv", action="store_true", help="also write clean CSVs")
    ap.add_argument("--upload-raw", action="store_true", help="archive original CSVs in the private Vercel Blob store")
    ap.add_argument("--from-storage", action="store_true", help="download and hash-verify archived CSVs from Vercel Blob first")
    ap.add_argument("--sqlite", action="store_true", help="use local SQLite even if Neon is configured")
    ap.add_argument("--database-url", help="override PIPELINE_DATABASE_URL")
    args = ap.parse_args(argv)

    url = f"sqlite:///{C.SQLITE_PATH}" if args.sqlite else (args.database_url or C.DATABASE_URL)
    if args.rebuild and url.startswith("sqlite") and C.SQLITE_PATH.exists() and url.endswith(str(C.SQLITE_PATH)):
        C.SQLITE_PATH.unlink()
    conn = connect(url)
    print(f"Database: {conn.dialect} ({redact(url)})")
    if args.rebuild and conn.dialect == "postgres":
        clear_pipeline_data(conn)
    registry = sync_sensor_registry(conn)

    if args.from_storage:
        import storage
        for name in storage.list_raw():
            print(f"  downloaded + verified {storage.download_raw(name, C.RAW_DIR).name}")

    files = [args.file] if args.file else sorted(C.RAW_DIR.glob("*.csv"))
    if not files:
        print(f"No CSV files found in {C.RAW_DIR}")
        return 1
    print(f"Ingesting {len(files)} file(s)")
    for f in files:
        ingest_file(conn, f, registry, force=args.force, upload_raw=args.upload_raw)

    print("Building aggregates...")
    build_aggregates(conn)
    C.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    write_quality_report(conn, C.PROCESSED_DIR / "data_quality_report.md")
    if args.export_csv:
        export_csv(conn)
    conn.close()
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
