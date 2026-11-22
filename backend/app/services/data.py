"""
Queries behind the data API (UC2; SEC-19).

Every SQL statement here is a fixed literal with `?` parameters. Column names come
from the VARIABLES allow-list, never from a request, and sensor or land-use filters are
applied in Python after one bounded query, so no SQL is assembled from user input.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..db import Transaction, to_datetime
from ..variables import LAND_USES, SEASON_START_MONTH, VARIABLES, flag_hits

LOCAL_TZ = ZoneInfo("Australia/Melbourne")
MIN_COMPLETENESS_PCT = 75.0
LIBELIUM = "libelium"

HUMIDITY_NOTE = ("Humidity from the Libelium sensors (Footscray Park and Saltwater Childcare) is unreliable: "
                 "they report 100% for long periods because of condensation. Those saturated readings are "
                 "left out of averages. Use the MCC units for humidity analysis.")
LOCATION_NOTE = "Sensor locations are approximate placeholders and have not yet been verified with the council."
FLAGGED_NOTE = ("Flagged readings (sensor spikes and frozen-temperature runs) are excluded. Turn off "
                "'Exclude flagged readings' to include them; some spikes may be real pollution events.")

READING_COLUMNS = list(VARIABLES)

# --------------------------------------------------------------------------- fixed SQL
SQL_SENSORS = """SELECT sensor_id, sensor_code, sensor_name, device_family, latitude, longitude, location_verified,
                        land_use, installation_date, status, notes, first_reading_utc, last_reading_utc,
                        sensitive_receptor
                 FROM sensors ORDER BY sensor_code"""
SQL_SENSOR_VARIABLES = "SELECT sensor_id, variable, unit FROM sensor_variables"
SQL_LATEST = """SELECT ts_utc, ts_local, qc_flags, temperature_c, humidity_pct, pm1, pm25, pm10, no2_ppb, co_ppb,
                       co2_ppm, pressure_hpa
                FROM readings WHERE sensor_id = ? ORDER BY ts_utc DESC LIMIT 1"""
SQL_COMPLETENESS = """SELECT sensor_id, variable, AVG(completeness_pct) AS avg_pct, SUM(is_valid) AS valid_days,
                             COUNT(*) AS days
                      FROM aggregates WHERE period = 'day' AND qc_mode = 'all'
                      GROUP BY sensor_id, variable"""
SQL_DATA_RANGE = """SELECT MIN(bucket_start_local) AS first_day, MAX(bucket_start_local) AS last_day
                    FROM aggregates WHERE period = 'day' AND qc_mode = 'all'"""
SQL_THRESHOLDS = """SELECT threshold_id, variable, period, operator, value, label, source
                    FROM thresholds ORDER BY threshold_id"""
SQL_AGG_ALL = """SELECT sensor_id, bucket_start_local, qc_mode, mean, min, max, n, completeness_pct, is_valid
                 FROM aggregates
                 WHERE period = ? AND variable = ? AND qc_mode = 'all'
                   AND bucket_start_local >= ? AND bucket_start_local <= ?"""
SQL_AGG_BOTH = """SELECT sensor_id, bucket_start_local, qc_mode, mean, min, max, n, completeness_pct, is_valid
                  FROM aggregates
                  WHERE period = ? AND variable = ? AND qc_mode IN ('all', 'clean')
                    AND bucket_start_local >= ? AND bucket_start_local <= ?"""
SQL_RAW = """SELECT sensor_id, ts_utc, ts_local, qc_flags, temperature_c, humidity_pct, pm1, pm25, pm10, no2_ppb,
                    co_ppb, co2_ppm, pressure_hpa
             FROM readings WHERE ts_utc >= ? AND ts_utc < ? ORDER BY sensor_id, ts_utc"""
SQL_EXCEEDANCES = """SELECT e.sensor_id, e.threshold_id, e.date_local, e.observed_value, e.completeness_pct,
                            t.variable, t.period, t.operator, t.value AS threshold_value, t.label,
                            s.sensor_code, s.sensor_name, s.land_use
                     FROM exceedances e
                     JOIN thresholds t ON t.threshold_id = e.threshold_id
                     JOIN sensors s ON s.sensor_id = e.sensor_id
                     WHERE e.date_local >= ? AND e.date_local <= ?"""


def _iso_utc(value: Any) -> str | None:
    moment = to_datetime(value)
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if moment else None


def _round(value: Any, places: int = 3) -> float | None:
    return None if value is None else round(float(value), places)


# --------------------------------------------------------------------------- sensors
def _sensor_variables(tx: Transaction) -> dict[int, list[dict[str, str]]]:
    out: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in tx.fetch_all(SQL_SENSOR_VARIABLES):
        if row["variable"] in VARIABLES:   # never expose a variable the sensor does not measure
            out[row["sensor_id"]].append({"variable": row["variable"], "label": VARIABLES[row["variable"]]["label"],
                                          "unit": row["unit"]})
    for items in out.values():
        items.sort(key=lambda v: list(VARIABLES).index(v["variable"]))
    return out


def _quality_notes(sensor: dict[str, Any], variables: list[dict[str, str]]) -> list[str]:
    notes = []
    if not sensor["location_verified"]:
        notes.append(LOCATION_NOTE)
    if sensor["device_family"] == LIBELIUM and any(v["variable"] == "humidity_pct" for v in variables):
        notes.append(HUMIDITY_NOTE)
    return notes


def list_sensors(tx: Transaction, sensor_id: int | None = None) -> list[dict[str, Any]]:
    """Sensors with measured variables, latest reading and completeness per variable."""
    variables = _sensor_variables(tx)
    completeness: dict[tuple[int, str], dict[str, Any]] = {
        (r["sensor_id"], r["variable"]): r for r in tx.fetch_all(SQL_COMPLETENESS)}
    out = []
    for s in tx.fetch_all(SQL_SENSORS):
        if sensor_id is not None and s["sensor_id"] != sensor_id:
            continue
        sv = variables.get(s["sensor_id"], [])
        latest = tx.fetch_one(SQL_LATEST, (s["sensor_id"],))
        latest_out = None
        if latest:
            latest_out = {"ts_utc": _iso_utc(latest["ts_utc"]), "ts_local": latest["ts_local"],
                          "values": {v["variable"]: _round(latest[v["variable"]]) for v in sv}}
        comp = {}
        for v in sv:
            row = completeness.get((s["sensor_id"], v["variable"]))
            comp[v["variable"]] = None if row is None else {
                "avg_daily_pct": _round(row["avg_pct"], 1), "valid_days": int(row["valid_days"] or 0),
                "days_with_data": int(row["days"])}
        out.append({
            "sensor_id": s["sensor_id"], "sensor_code": s["sensor_code"], "sensor_name": s["sensor_name"],
            "device_family": s["device_family"], "land_use": s["land_use"], "status": s["status"],
            "latitude": s["latitude"], "longitude": s["longitude"],
            "location_verified": bool(s["location_verified"]),
            "sensitive_receptor": bool(s["sensitive_receptor"]),
            "variables": sv, "latest": latest_out, "completeness": comp,
            "first_reading_utc": _iso_utc(s["first_reading_utc"]),
            "last_reading_utc": _iso_utc(s["last_reading_utc"]),
            "quality_notes": _quality_notes(s, sv),
        })
    return out


# --------------------------------------------------------------------------- meta
def meta(tx: Transaction) -> dict[str, Any]:
    """Options for the filter panel: variables (measured somewhere), land uses, data range."""
    counts: dict[str, int] = defaultdict(int)
    units: dict[str, str] = {}
    for items in _sensor_variables(tx).values():
        for v in items:
            counts[v["variable"]] += 1
            units[v["variable"]] = v["unit"]
    rng = tx.fetch_one(SQL_DATA_RANGE) or {}
    return {
        "variables": [{"variable": k, "label": m["label"], "unit": units.get(k, m["unit"]), "sensor_count": counts[k]}
                      for k, m in VARIABLES.items() if counts[k]],
        "land_uses": list(LAND_USES),
        "resolutions": ["hour", "day", "month", "season", "raw"],
        "data_range": {"first_day": rng.get("first_day"), "last_day": rng.get("last_day")},
        "thresholds": [dict(t) for t in tx.fetch_all(SQL_THRESHOLDS)],
        "limits": {"raw_max_days": 7, "hour_max_days": 92, "max_sensor_ids": 20},
    }


# --------------------------------------------------------------------------- readings
def selected_sensors(tx: Transaction, variable: str, land_uses: list[str], sensor_ids: list[int]) -> list[dict]:
    """Sensors that MEASURE the variable and match the filters (empty filter = all)."""
    measuring = {sid for sid, items in _sensor_variables(tx).items() if any(v["variable"] == variable for v in items)}
    sensors = [s for s in tx.fetch_all(SQL_SENSORS) if s["sensor_id"] in measuring]
    if land_uses:
        sensors = [s for s in sensors if s["land_use"] in land_uses]
    if sensor_ids:
        sensors = [s for s in sensors if s["sensor_id"] in set(sensor_ids)]
    return sensors


def _point(bucket: str, row: dict[str, Any]) -> dict[str, Any]:
    has_data = row["n"] and row["mean"] is not None
    return {"t": bucket, "mean": _round(row["mean"]) if has_data else None,
            "min": _round(row["min"]) if has_data else None, "max": _round(row["max"]) if has_data else None,
            "n": int(row["n"]), "completeness_pct": _round(row["completeness_pct"], 1),
            "valid": bool(row["is_valid"]), "flagged": False}


def _aggregate_points(tx: Transaction, period: str, variable: str, lo: str, hi: str,
                      exclude_flagged: bool) -> dict[int, dict[str, dict[str, Any]]]:
    """sensor_id -> bucket -> row. With exclude_flagged, a sparse 'clean' row replaces its
    'all' row (DECISIONS.md D-028)."""
    sql = SQL_AGG_BOTH if exclude_flagged else SQL_AGG_ALL
    by_sensor: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
    rows = tx.fetch_all(sql, (period, variable, lo, hi))
    for row in rows:   # 'all' first, then 'clean' overrides
        if row["qc_mode"] == "all":
            by_sensor[row["sensor_id"]][row["bucket_start_local"]] = row
    for row in rows:
        if row["qc_mode"] == "clean":
            by_sensor[row["sensor_id"]][row["bucket_start_local"]] = row
    return by_sensor


def _season_key(day: date) -> tuple[str, int]:
    season = {12: "Summer", 1: "Summer", 2: "Summer", 3: "Autumn", 4: "Autumn", 5: "Autumn",
              6: "Winter", 7: "Winter", 8: "Winter"}.get(day.month, "Spring")
    start_year = day.year - 1 if day.month in (1, 2) else day.year
    return season, start_year


def _season_label(season: str, start_year: int) -> str:
    return f"Summer {start_year}–{str(start_year + 1)[2:]}" if season == "Summer" else f"{season} {start_year}"


def _season_points(daily: dict[str, dict[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
    """Seasons from daily rows: n-weighted mean, overall min/max, completeness = mean daily
    completeness over every calendar day of the season inside the range (missing days = 0)."""
    groups: dict[tuple[str, int], list[date]] = defaultdict(list)
    day = start
    while day <= end:
        groups[_season_key(day)].append(day)
        day += timedelta(days=1)
    points = []
    # chronological: a season starts in (start_year, start_month); Summer starts in December
    for (season, year), days in sorted(groups.items(), key=lambda kv: (kv[0][1], SEASON_START_MONTH[kv[0][0]])):
        rows = [daily[d.isoformat()] for d in days if d.isoformat() in daily]
        with_data = [r for r in rows if r["n"] and r["mean"] is not None]
        n = sum(int(r["n"]) for r in with_data)
        comp = sum(float(r["completeness_pct"] or 0) for r in rows) / len(days)
        points.append({
            "t": _season_label(season, year),
            "mean": _round(sum(float(r["mean"]) * int(r["n"]) for r in with_data) / n) if n else None,
            "min": _round(min(float(r["min"]) for r in with_data)) if with_data else None,
            "max": _round(max(float(r["max"]) for r in with_data)) if with_data else None,
            "n": n, "completeness_pct": round(comp, 1), "valid": comp >= MIN_COMPLETENESS_PCT, "flagged": False,
        })
    return points


def _raw_points(tx: Transaction, variable: str, start: date, end: date,
                exclude_flagged: bool) -> dict[int, list[dict[str, Any]]]:
    lo = datetime.combine(start, time(0), LOCAL_TZ).astimezone(UTC)
    hi = datetime.combine(end + timedelta(days=1), time(0), LOCAL_TZ).astimezone(UTC)
    out: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in tx.fetch_all(SQL_RAW, (lo, hi)):
        value = row[variable]
        if value is None:
            continue
        flagged = flag_hits(row["qc_flags"], variable)
        if flagged and exclude_flagged:
            continue
        v = _round(value)
        out[row["sensor_id"]].append({"t": row["ts_local"], "mean": v, "min": v, "max": v, "n": 1,
                                      "completeness_pct": None, "valid": True, "flagged": flagged})
    return out


def _summary(points: list[dict[str, Any]]) -> dict[str, Any]:
    with_data = [p for p in points if p["mean"] is not None and p["n"]]
    n = sum(p["n"] for p in with_data)
    comps = [p["completeness_pct"] for p in points if p["completeness_pct"] is not None]
    return {
        "mean": _round(sum(p["mean"] * p["n"] for p in with_data) / n) if n else None,
        "min": min((p["min"] for p in with_data), default=None),
        "max": max((p["max"] for p in with_data), default=None),
        "n": n,
        "completeness_pct": round(sum(comps) / len(comps), 1) if comps else None,
        "valid_buckets": sum(1 for p in points if p["valid"]), "buckets": len(points),
    }


def readings(tx: Transaction, variable: str, resolution: str, start: date, end: date, land_uses: list[str],
             sensor_ids: list[int], exclude_flagged: bool) -> dict[str, Any]:
    """One series per selected sensor at the requested resolution."""
    sensors = selected_sensors(tx, variable, land_uses, sensor_ids)
    series_points: dict[int, list[dict[str, Any]]] = {}
    if resolution == "raw":
        raw = _raw_points(tx, variable, start, end, exclude_flagged)
        series_points = {s["sensor_id"]: raw.get(s["sensor_id"], []) for s in sensors}
    elif resolution == "season":
        daily = _aggregate_points(tx, "day", variable, start.isoformat(), end.isoformat(), exclude_flagged)
        series_points = {s["sensor_id"]: _season_points(daily.get(s["sensor_id"], {}), start, end)
                         for s in sensors if daily.get(s["sensor_id"])}
    else:
        bounds = {"hour": (f"{start.isoformat()} 00:00", f"{end.isoformat()} 23:00"),
                  "day": (start.isoformat(), end.isoformat()),
                  "month": (start.isoformat()[:7], end.isoformat()[:7])}[resolution]
        agg = _aggregate_points(tx, resolution, variable, *bounds, exclude_flagged)
        series_points = {sid: [_point(b, row) for b, row in sorted(buckets.items())] for sid, buckets in agg.items()}

    series = []
    for s in sensors:
        points = series_points.get(s["sensor_id"], [])
        if not points:
            continue
        series.append({"sensor_id": s["sensor_id"], "sensor_code": s["sensor_code"], "sensor_name": s["sensor_name"],
                       "land_use": s["land_use"], "location_verified": bool(s["location_verified"]),
                       "points": points, "summary": _summary(points)})

    notes = []
    if exclude_flagged:
        notes.append(FLAGGED_NOTE)
    if variable == "humidity_pct" and any(s["device_family"] == LIBELIUM for s in sensors
                                          if s["sensor_id"] in {x["sensor_id"] for x in series}):
        notes.append(HUMIDITY_NOTE)
    if any(not x["location_verified"] for x in series):
        notes.append(LOCATION_NOTE)
    all_points = [p for x in series for p in x["points"]]
    return {
        "variable": variable, "label": VARIABLES[variable]["label"], "unit": VARIABLES[variable]["unit"],
        "resolution": resolution, "start": start.isoformat(), "end": end.isoformat(),
        "exclude_flagged": exclude_flagged, "series": series, "summary": _summary(all_points),
        "thresholds": [dict(t) for t in tx.fetch_all(SQL_THRESHOLDS) if t["variable"] == variable],
        "notes": notes,
    }


# --------------------------------------------------------------------------- exceedances
def exceedances(tx: Transaction, start: date | None, end: date | None, variable: str | None,
                land_uses: list[str], sensor_ids: list[int], sort: str, order: str,
                limit: int, offset: int) -> dict[str, Any]:
    lo = start.isoformat() if start else "0000-01-01"
    hi = end.isoformat() if end else "9999-12-31"
    rows = tx.fetch_all(SQL_EXCEEDANCES, (lo, hi))
    if variable:
        rows = [r for r in rows if r["variable"] == variable]
    if land_uses:
        rows = [r for r in rows if r["land_use"] in land_uses]
    if sensor_ids:
        rows = [r for r in rows if r["sensor_id"] in set(sensor_ids)]
    keys = {"date": lambda r: (r["date_local"], r["sensor_code"]),
            "value": lambda r: (float(r["observed_value"]), r["date_local"]),
            "sensor": lambda r: (r["sensor_code"], r["date_local"])}
    rows.sort(key=keys[sort], reverse=order == "desc")
    items = [{
        "date_local": r["date_local"], "sensor_id": r["sensor_id"], "sensor_code": r["sensor_code"],
        "sensor_name": r["sensor_name"], "land_use": r["land_use"], "threshold_id": r["threshold_id"],
        "label": r["label"], "variable": r["variable"], "unit": VARIABLES.get(r["variable"], {}).get("unit", ""),
        "statistic": "daily mean" if r["period"] == "day" else "daily maximum",
        "observed_value": _round(r["observed_value"]), "threshold_value": _round(r["threshold_value"]),
        "operator": r["operator"], "completeness_pct": _round(r["completeness_pct"], 1),
    } for r in rows]
    return {"total": len(items), "items": items[offset:offset + limit]}


# --------------------------------------------------------------------------- temporal heat map
def heatmap(tx: Transaction, variable: str, start: date, end: date, land_uses: list[str],
            sensor_ids: list[int], exclude_flagged: bool) -> dict[str, Any]:
    """Hour-of-day x month grid (UC2 visualisation 3) from VALID hourly aggregates of the
    selected sensors: each cell is the reading-count-weighted mean of every valid hour that
    falls on that hour of day in that month. Invalid (<75% complete) hours are left out."""
    sensors = selected_sensors(tx, variable, land_uses, sensor_ids)
    wanted = {s["sensor_id"] for s in sensors}
    hourly = _aggregate_points(tx, "hour", variable, f"{start.isoformat()} 00:00", f"{end.isoformat()} 23:00",
                               exclude_flagged)
    sums: dict[tuple[str, int], list[float]] = defaultdict(lambda: [0.0, 0, 0])   # weighted sum, n, hours
    used: set[int] = set()
    for sid, buckets in hourly.items():
        if sid not in wanted:
            continue
        for bucket, row in buckets.items():
            if not row["is_valid"] or not row["n"] or row["mean"] is None:
                continue
            cell = sums[(bucket[:7], int(bucket[11:13]))]
            cell[0] += float(row["mean"]) * int(row["n"])
            cell[1] += int(row["n"])
            cell[2] += 1
            used.add(sid)
    months = sorted({m for m, _ in sums})
    cells = [{"month": m, "hour": h, "mean": _round(s / n), "n": n, "hours": hrs}
             for (m, h), (s, n, hrs) in sorted(sums.items())]
    notes = []
    if exclude_flagged:
        notes.append(FLAGGED_NOTE)
    notes.append("Each cell averages every valid hour (at least 75% of expected readings) of the selected "
                 "sensors at that time of day in that month. Hours below 75% are left out.")
    if variable == "humidity_pct" and any(s["device_family"] == LIBELIUM and s["sensor_id"] in used for s in sensors):
        notes.append(HUMIDITY_NOTE)
    return {
        "variable": variable, "label": VARIABLES[variable]["label"], "unit": VARIABLES[variable]["unit"],
        "start": start.isoformat(), "end": end.isoformat(), "exclude_flagged": exclude_flagged,
        "months": months, "hours": list(range(24)), "cells": cells,
        "sensors": [s["sensor_code"] for s in sensors if s["sensor_id"] in used],
        "summary": {"min": min((c["mean"] for c in cells), default=None),
                    "max": max((c["mean"] for c in cells), default=None)},
        "notes": notes,
    }
