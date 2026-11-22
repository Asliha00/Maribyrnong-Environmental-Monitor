"""
Live device ingestion (UC4, BUILD_PROMPT §4.6; SEC-03): store one reading and update the
aggregates it touches, with the pipeline's own rules (`etl.transform_live`,
`etl.sensor_aggregate_rows`), all inside the caller's transaction.
"""
from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd

from ..db import Transaction
from . import ingest

DUMMY_HASH = "sha256$" + "0" * 64   # compared against when the device id is unknown (equal timing)
CONTEXT_READINGS = 12               # previous readings the flatline/spike rules look at

SQL_SENSOR = """SELECT sensor_id, sensor_code, device_family, status, auth_key_hash, first_reading_utc
                FROM sensors WHERE sensor_code = ?"""
SQL_RECENT = """SELECT ts_utc, temperature_c, humidity_pct, pm1, pm25, pm10, no2_ppb, co_ppb, co2_ppm,
                       pressure_hpa, aqi, battery_v
                FROM readings WHERE sensor_id = ? AND ts_utc < ? ORDER BY ts_utc DESC LIMIT ?"""
SQL_INSERT = """INSERT INTO readings (sensor_id, ts_utc, ts_local, temperature_c, humidity_pct, pm1, pm25, pm10,
                                      no2_ppb, co_ppb, co2_ppm, pressure_hpa, aqi, battery_v, qc_flags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (sensor_id, ts_utc) DO NOTHING"""
SQL_MONTH = """SELECT ts_utc, qc_flags, temperature_c, humidity_pct, pm1, pm25, pm10, no2_ppb, co_ppb, co2_ppm,
                      pressure_hpa, aqi, battery_v
               FROM readings WHERE sensor_id = ? AND ts_utc >= ? AND ts_utc < ?"""
SQL_DELETE_BUCKET = "DELETE FROM aggregates WHERE sensor_id = ? AND period = ? AND bucket_start_local = ?"
SQL_INSERT_AGG = """INSERT INTO aggregates (sensor_id, period, bucket_start_local, season, variable, mean, min, max,
                                            n, completeness_pct, is_valid, qc_mode)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
VALUE_COLUMNS = ["temperature_c", "humidity_pct", "pm1", "pm25", "pm10", "no2_ppb", "co_ppb", "co2_ppm",
                 "pressure_hpa", "aqi", "battery_v"]


def key_hash(key: str) -> str:
    return "sha256$" + hashlib.sha256(key.encode()).hexdigest()


def key_matches(stored: str | None, key: str) -> bool:
    """Constant-time comparison of the presented key's hash with the stored one (SEC-03)."""
    return hmac.compare_digest((stored or DUMMY_HASH).encode(), key_hash(key).encode()) and stored is not None


def find_sensor(tx: Transaction, device_id: str) -> dict[str, Any] | None:
    return tx.fetch_one(SQL_SENSOR, (device_id,))


def _month_bounds_utc(ts: pd.Timestamp, tz) -> tuple[datetime, datetime, pd.Timestamp]:
    local = ts.tz_convert(tz)
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (start + pd.offsets.MonthBegin(1))
    return start.tz_convert(UTC).to_pydatetime(), end.tz_convert(UTC).to_pydatetime(), local


def store_reading(tx: Transaction, sensor: dict[str, Any], values: dict[str, float | None],
                  ts: datetime) -> dict[str, Any]:
    """Validate, store and aggregate one reading. Returns what happened (for the response)."""
    config, etl, _ = ingest.pipeline()
    sid = int(sensor["sensor_id"])
    stamp = pd.Timestamp(ts).tz_convert(UTC)
    recent = pd.DataFrame(tx.fetch_all(SQL_RECENT, (sid, stamp.to_pydatetime(), CONTEXT_READINGS)))
    recent = recent.iloc[::-1].reset_index(drop=True) if len(recent) else pd.DataFrame(columns=["ts_utc"])
    row, errors, stats = etl.transform_live(values, stamp, sensor["device_family"], sid, recent)

    inserted = tx.execute(SQL_INSERT, (sid, row["ts_utc"], row["ts_local"], *[row[c] for c in VALUE_COLUMNS],
                                       row["qc_flags"]))
    if not inserted:   # same sensor + second already stored: a replay or a retry (SEC-03)
        tx.execute("INSERT INTO error_log (sensor_id, ts_utc, error_type, description) VALUES (?, ?, ?, ?)",
                   (sid, row["ts_utc"], "duplicate", "Live reading for a time already stored; ignored"))
        return {"status": "duplicate", "ts_utc": row["ts_utc"]}
    for e in errors:
        tx.execute("INSERT INTO error_log (sensor_id, ts_utc, error_type, variable, raw_value, description) "
                   "VALUES (?, ?, ?, ?, ?, ?)",
                   (sid, e["ts_utc"], e["error_type"], e["variable"], e["raw_value"], e["description"]))
    stored_vars = [v for v in stats["variables"] if row[v] is not None]
    for v in stored_vars:   # a new sensor's first reading registers what it measures
        tx.execute("INSERT INTO sensor_variables (sensor_id, variable, unit, raw_column) VALUES (?, ?, ?, ?) "
                   "ON CONFLICT (sensor_id, variable) DO NOTHING",
                   (sid, v, config.CANONICAL_UNITS[v], _raw_name(config, sensor["device_family"], v)))
    tx.execute("UPDATE sensors SET last_reading_utc = ? WHERE sensor_id = ? "
               "AND (last_reading_utc IS NULL OR last_reading_utc < ?)", (row["ts_utc"], sid, row["ts_utc"]))
    tx.execute("UPDATE sensors SET first_reading_utc = ? WHERE sensor_id = ? AND first_reading_utc IS NULL",
               (row["ts_utc"], sid))

    buckets = update_aggregates(tx, sensor, stamp, config, etl)
    exceeded = update_exceedances(tx, sid, buckets["day"])
    return {"status": "stored", "ts_utc": row["ts_utc"], "flags": stats["flags"],
            "rejected": [e["variable"] for e in errors], "buckets": buckets, "exceedances": exceeded}


def _raw_name(config, family: str, canon: str) -> str:
    return next((raw for raw, (c, _) in config.COLUMN_MAP[family].items() if c == canon), canon)


def update_aggregates(tx: Transaction, sensor: dict[str, Any], stamp: pd.Timestamp, config, etl) -> dict[str, str]:
    """Recompute the hour, day and month buckets containing `stamp` (both 'all' and the sparse
    'clean' rows) from the month's readings, using the pipeline's aggregation."""
    sid = int(sensor["sensor_id"])
    lo, hi, local = _month_bounds_utc(stamp, config.LOCAL_TZ)
    variables = [r["variable"] for r in tx.fetch_all("SELECT variable FROM sensor_variables WHERE sensor_id = ?",
                                                    (sid,)) if r["variable"] in VALUE_COLUMNS]
    month = pd.DataFrame(tx.fetch_all(SQL_MONTH, (sid, lo, hi)))
    buckets = {"hour": local.strftime("%Y-%m-%d %H:00"), "day": local.strftime("%Y-%m-%d"),
               "month": local.strftime("%Y-%m")}
    rows = etl.sensor_aggregate_rows(month[["ts_utc", "qc_flags", *variables]], variables, sid,
                                     sensor["device_family"]) if variables and len(month) else []
    for period, bucket in buckets.items():
        tx.execute(SQL_DELETE_BUCKET, (sid, period, bucket))
    for r in rows:
        if buckets.get(r[1]) == r[2]:
            tx.execute(SQL_INSERT_AGG, tuple(None if pd.isna(x) else (x.item() if hasattr(x, "item") else x)
                                             for x in r))
    return buckets


def update_exceedances(tx: Transaction, sensor_id: int, day: str) -> int:
    """Re-evaluate every threshold for this sensor and day from its valid daily 'all' row."""
    tx.execute("DELETE FROM exceedances WHERE sensor_id = ? AND date_local = ?", (sensor_id, day))
    count = 0
    for t in tx.fetch_all("SELECT threshold_id, variable, period, operator, value FROM thresholds"):
        agg = tx.fetch_one("SELECT mean, max, completeness_pct FROM aggregates WHERE sensor_id = ? AND period = 'day' "
                           "AND bucket_start_local = ? AND variable = ? AND qc_mode = 'all' AND is_valid = 1",
                           (sensor_id, day, t["variable"]))
        if agg is None:
            continue
        observed = agg["mean"] if t["period"] == "day" else agg["max"]
        if observed is None:
            continue
        over = observed > t["value"] if t["operator"] == ">" else observed >= t["value"]
        if over:
            tx.execute("INSERT INTO exceedances (sensor_id, threshold_id, date_local, observed_value, "
                       "completeness_pct) VALUES (?, ?, ?, ?, ?)",
                       (sensor_id, t["threshold_id"], day, observed, agg["completeness_pct"]))
            count += 1
    return count


def clock_skew(ts: datetime, now: datetime | None = None) -> timedelta:
    return abs((now or datetime.now(UTC)) - ts)
