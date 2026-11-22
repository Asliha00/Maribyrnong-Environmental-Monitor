"""
Data-quality page (BUILD_PROMPT §4.5): per-sensor completeness calendar, error_log browser,
ingestion-run history and flag counts (`view_quality`: analysts and administrators), plus the
suspicious-login entries (SEC-27; `manage_users`: administrators only).

Queries follow `write_quality_report` in data_pipeline/etl.py. Optional filters use the
parameterised `(CAST(? AS ...) IS NULL OR column = ?)` form, so no SQL is assembled.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request

from ..db import to_datetime
from ..errors import AppError
from ..security import Session, require_permission
from ..services import data
from ..variables import HEATMAP_MAX_DAYS, VARIABLES, Variable
from . import admin_common

router = APIRouter(prefix="/quality", tags=["quality"])
can_view = require_permission("view_quality")
can_see_security = require_permission("manage_users")

ErrorType = Literal["out_of_range", "not_fitted", "duplicate", "invalid_timestamp", "unknown_sensor",
                    "ingest_rejected"]
FLAG_LABELS = {"spike": "Sudden spike (kept, flagged)", "flatline": "Value frozen for hours (kept, flagged)",
               "saturated": "Humidity saturated at 100% (kept, flagged)"}

SQL_DAY_COMPLETENESS = """SELECT sensor_id, bucket_start_local, completeness_pct, is_valid FROM aggregates
                          WHERE period = 'day' AND qc_mode = 'all' AND variable = ?
                            AND bucket_start_local >= ? AND bucket_start_local <= ?"""
SQL_ERRORS = """SELECT e.error_id, e.sensor_id, s.sensor_code, e.ts_utc, e.error_type, e.variable, e.raw_value,
                       e.description, e.ingestion_run_id, e.logged_at
                FROM error_log e LEFT JOIN sensors s ON s.sensor_id = e.sensor_id
                WHERE (CAST(? AS INTEGER) IS NULL OR e.sensor_id = ?)
                  AND (CAST(? AS TEXT) IS NULL OR e.error_type = ?)
                  AND (CAST(? AS TEXT) IS NULL OR e.variable = ?)
                  AND (CAST(? AS TIMESTAMP) IS NULL OR e.ts_utc >= ?)
                  AND (CAST(? AS TIMESTAMP) IS NULL OR e.ts_utc < ?)
                ORDER BY e.error_id DESC"""
SQL_RUNS = """SELECT r.run_id, r.source_file, r.file_sha256, r.sensor_id, s.sensor_code, r.rows_read,
                     r.rows_inserted, r.rows_duplicate, r.values_rejected, r.values_flagged, r.storage_path,
                     r.started_at, r.finished_at
              FROM ingestion_runs r LEFT JOIN sensors s ON s.sensor_id = r.sensor_id
              ORDER BY r.run_id DESC"""
SQL_FLAGS = """SELECT sensor_id, qc_flags, COUNT(*) AS n FROM readings WHERE qc_flags IS NOT NULL
               GROUP BY sensor_id, qc_flags"""
SQL_SUSPICIOUS = """SELECT audit_id, created_at, ip_address, detail_json FROM audit_log
                    WHERE action = 'suspicious_login_activity' ORDER BY audit_id DESC"""


def _iso(value: Any) -> str | None:
    moment = to_datetime(value)
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if moment else None


def _sensor_codes(tx) -> dict[int, dict[str, Any]]:
    return {s["sensor_id"]: s for s in tx.fetch_all(data.SQL_SENSORS)}


@router.get("/completeness")
def completeness(request: Request, variable: Variable, start: date, end: date,
                 session: Session = Depends(can_view)) -> dict[str, Any]:
    """Calendar: one cell per sensor per day (completeness %, valid or not); days with no
    data at all are listed as 0% so gaps are visible, not hidden."""
    if start > end:
        raise AppError(400, "invalid_date_range", "Invalid date range selected.")
    if (end - start).days + 1 > HEATMAP_MAX_DAYS:
        raise AppError(400, "range_too_long", f"The calendar covers up to {HEATMAP_MAX_DAYS} days at a time.")
    with request.app.state.db.transaction() as tx:
        admin_common.limit(tx, session)
        sensors = _sensor_codes(tx)
        measuring = {s["sensor_id"] for s in data.selected_sensors(tx, variable, [], [])}
        rows = tx.fetch_all(SQL_DAY_COMPLETENESS, (variable, start.isoformat(), end.isoformat()))
    by_sensor: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
    for r in rows:
        by_sensor[r["sensor_id"]][r["bucket_start_local"]] = r
    days = [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
    out = []
    for sid in sorted(measuring, key=lambda i: sensors[i]["sensor_code"]):
        cells = [{"date": d, "pct": round(float(by_sensor[sid][d]["completeness_pct"]), 1) if d in by_sensor[sid]
                  else 0.0, "valid": bool(by_sensor[sid][d]["is_valid"]) if d in by_sensor[sid] else False}
                 for d in days]
        valid = sum(c["valid"] for c in cells)
        out.append({"sensor_id": sid, "sensor_code": sensors[sid]["sensor_code"],
                    "sensor_name": sensors[sid]["sensor_name"], "status": sensors[sid]["status"],
                    "valid_days": valid, "days": len(days),
                    "avg_pct": round(sum(c["pct"] for c in cells) / len(cells), 1), "cells": cells})
    return {"variable": variable, "label": VARIABLES[variable]["label"], "start": start.isoformat(),
            "end": end.isoformat(), "min_valid_pct": data.MIN_COMPLETENESS_PCT, "sensors": out}


@router.get("/errors")
def errors(request: Request,
           sensor_id: Annotated[int | None, Query(ge=1, le=1_000_000)] = None,
           error_type: ErrorType | None = None,
           variable: Annotated[str | None, Query(pattern=r"^[a-z0-9_]{2,20}$")] = None,
           start: date | None = None, end: date | None = None,
           limit: Annotated[int, Query(ge=1, le=200)] = 50,
           offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
           session: Session = Depends(can_view)) -> dict[str, Any]:
    """Rejected values and file problems from error_log, newest first, filterable and paged."""
    if start and end and start > end:
        raise AppError(400, "invalid_date_range", "Invalid date range selected.")
    lo = datetime.combine(start, time(0), data.LOCAL_TZ).astimezone(UTC) if start else None
    hi = datetime.combine(end + timedelta(days=1), time(0), data.LOCAL_TZ).astimezone(UTC) if end else None
    with request.app.state.db.transaction() as tx:
        admin_common.limit(tx, session)
        rows = tx.fetch_all(SQL_ERRORS, (sensor_id, sensor_id, error_type, error_type, variable, variable,
                                         lo, lo, hi, hi))
        types = tx.fetch_all("SELECT error_type, COUNT(*) AS n FROM error_log GROUP BY error_type")
    items = [{**r, "ts_utc": _iso(r["ts_utc"]), "logged_at": _iso(r["logged_at"])}
             for r in rows[offset:offset + limit]]
    return {"total": len(rows), "items": items,
            "by_type": {t["error_type"]: t["n"] for t in sorted(types, key=lambda t: -t["n"])}}


@router.get("/runs")
def runs(request: Request, limit: Annotated[int, Query(ge=1, le=200)] = 100,
         session: Session = Depends(can_view)) -> dict[str, Any]:
    """Ingestion runs (files loaded), newest first. A run without finished_at did not complete."""
    with request.app.state.db.transaction() as tx:
        admin_common.limit(tx, session)
        rows = tx.fetch_all(SQL_RUNS)
    return {"total": len(rows), "items": [
        {**r, "file_sha256": r["file_sha256"][:12], "started_at": _iso(r["started_at"]),
         "finished_at": _iso(r["finished_at"]), "completed": r["finished_at"] is not None,
         "archived": bool(r["storage_path"]), "storage_path": None} for r in rows[:limit]]}


@router.get("/flags")
def flags(request: Request, session: Session = Depends(can_view)) -> dict[str, Any]:
    """Flagged (kept, marked) values per sensor and flag type."""
    with request.app.state.db.transaction() as tx:
        admin_common.limit(tx, session)
        sensors = _sensor_codes(tx)
        rows = tx.fetch_all(SQL_FLAGS)
    counts: Counter[tuple[int, str]] = Counter()
    for r in rows:
        for flag in filter(None, r["qc_flags"].split(";")):
            counts[(r["sensor_id"], flag)] += int(r["n"])
    items = [{"sensor_id": sid, "sensor_code": sensors.get(sid, {}).get("sensor_code", f"#{sid}"), "flag": flag,
              "description": FLAG_LABELS.get(flag.rsplit("_", 1)[-1], flag), "readings": n}
             for (sid, flag), n in sorted(counts.items(), key=lambda kv: (sensors.get(kv[0][0], {})
                                                                           .get("sensor_code", ""), -kv[1]))]
    return {"items": items, "total": sum(counts.values())}


@router.get("/security")
def security_events(request: Request, session: Session = Depends(can_see_security)) -> dict[str, Any]:
    """Suspicious-login entries (more than 20 failed logins in 10 minutes; SEC-27), newest first."""
    import json

    with request.app.state.db.transaction() as tx:
        admin_common.limit(tx, session)
        rows = tx.fetch_all(SQL_SUSPICIOUS)
    return {"items": [{"audit_id": r["audit_id"], "created_at": _iso(r["created_at"]), "ip_address": r["ip_address"],
                       **json.loads(r["detail_json"] or "{}")} for r in rows[:100]]}
