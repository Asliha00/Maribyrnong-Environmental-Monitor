"""
Data API (UC2): meta, sensors, readings, exceedances.

Every parameter is validated before any query runs (SEC-19): enums for variable,
resolution and land use, typed dates, bounded lists. Data queries are audited
(SEC-12 "queries") and rate limited per user (SEC-23).
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Query, Request

from ..errors import AppError
from ..security import Session, client_ip, require_permission
from ..services import audit, data, rate_limit
from ..variables import HEATMAP_MAX_DAYS, HOUR_MAX_DAYS, MAX_SENSOR_IDS, RAW_MAX_DAYS, LandUse, Resolution, Variable

router = APIRouter(tags=["data"])

DATA_PER_USER = rate_limit.Limit("data:user", 120, 60)   # generous; protects the free-tier database
MSG_INVALID_RANGE = "Invalid date range selected."
MSG_NO_DATA = "No data available for the selected filters."

can_view = require_permission("view_data")
can_filter = require_permission("filter_data")

SensorIds = Annotated[list[Annotated[int, Query(ge=1, le=1_000_000)]],
                      Query(max_length=MAX_SENSOR_IDS, description=f"Up to {MAX_SENSOR_IDS} sensor ids")]
LandUses = Annotated[list[LandUse], Query(max_length=5)]


def _limit(tx, session: Session) -> None:
    allowed, retry_after = rate_limit.hit(tx, DATA_PER_USER, str(session.user_id))
    if not allowed:
        raise AppError(429, "rate_limited", "Too many requests. Please wait a moment and try again.",
                       headers={"Retry-After": str(retry_after)})


def _check_range(start: date, end: date, resolution: str | None = None) -> None:
    if start > end:
        raise AppError(400, "invalid_date_range", MSG_INVALID_RANGE)
    days = (end - start).days + 1
    if resolution == "raw" and days > RAW_MAX_DAYS:
        raise AppError(400, "range_too_long",
                       f"Raw readings are available for up to {RAW_MAX_DAYS} days. "
                       "Choose a shorter range or the Hourly or Daily view.")
    if resolution == "heatmap" and days > HEATMAP_MAX_DAYS:
        raise AppError(400, "range_too_long",
                       f"The hour-by-month heat map covers up to {HEATMAP_MAX_DAYS} days. Choose a shorter range.")
    if resolution == "hour" and days > HOUR_MAX_DAYS:
        raise AppError(400, "range_too_long",
                       f"Hourly data is available for up to {HOUR_MAX_DAYS} days at a time. "
                       "Choose a shorter range or the Daily or Monthly view.")


@router.get("/meta")
def get_meta(request: Request, session: Session = Depends(can_view)) -> dict[str, Any]:
    """Filter-panel options: variables (with units), land uses, data range, thresholds."""
    with request.app.state.db.transaction() as tx:
        return data.meta(tx)


@router.get("/sensors")
def get_sensors(request: Request, session: Session = Depends(can_view)) -> dict[str, Any]:
    """All sensors with measured variables, latest reading, completeness and data-quality notes."""
    with request.app.state.db.transaction() as tx:
        _limit(tx, session)
        return {"sensors": data.list_sensors(tx)}


@router.get("/sensors/{sensor_id}")
def get_sensor(request: Request, sensor_id: Annotated[int, Path(ge=1, le=1_000_000)],
               session: Session = Depends(can_view)) -> dict[str, Any]:
    """One sensor: details, latest reading per variable, completeness."""
    with request.app.state.db.transaction() as tx:
        _limit(tx, session)
        found = data.list_sensors(tx, sensor_id=sensor_id)
    if not found:
        raise AppError(404, "sensor_not_found", "Sensor not found.")
    return found[0]


@router.get("/readings")
def get_readings(
    request: Request,
    variable: Variable,
    start: date,
    end: date,
    resolution: Resolution = "day",
    land_use: LandUses = [],      # noqa: B006 - FastAPI copies query defaults per request
    sensor_ids: SensorIds = [],   # noqa: B006
    exclude_flagged: bool = True,
    session: Session = Depends(can_filter),
) -> dict[str, Any]:
    """Series per sensor. hour/day/month read pre-computed aggregates; season is built from
    daily rows; raw is limited to 7 days. `exclude_flagged` (default on) uses the clean
    aggregate variant (DECISIONS.md D-028)."""
    _check_range(start, end, resolution)
    with request.app.state.db.transaction() as tx:
        _limit(tx, session)
        result = data.readings(tx, variable, resolution, start, end, list(land_use), list(sensor_ids), exclude_flagged)
        audit.record(tx, "data_query", user_id=session.user_id, ip=client_ip(request), detail={
            "endpoint": "readings", "variable": variable, "resolution": resolution, "start": start.isoformat(),
            "end": end.isoformat(), "land_use": list(land_use), "sensor_ids": list(sensor_ids),
            "exclude_flagged": exclude_flagged, "series": len(result["series"])})
    if not result["series"]:
        raise AppError(404, "no_data", MSG_NO_DATA)
    return result


@router.get("/exceedances")
def get_exceedances(
    request: Request,
    start: date | None = None,
    end: date | None = None,
    variable: Variable | None = None,
    land_use: LandUses = [],      # noqa: B006
    sensor_ids: SensorIds = [],   # noqa: B006
    sort: Literal["date", "value", "sensor"] = "date",
    order: Literal["asc", "desc"] = "desc",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    session: Session = Depends(can_view),
) -> dict[str, Any]:
    """Threshold exceedance days (from valid daily aggregates, 'all' variant), sortable,
    with the total for the alert badge."""
    if start and end:
        _check_range(start, end)
    with request.app.state.db.transaction() as tx:
        _limit(tx, session)
        result = data.exceedances(tx, start, end, variable, list(land_use), list(sensor_ids), sort, order,
                                  limit, offset)
        audit.record(tx, "data_query", user_id=session.user_id, ip=client_ip(request), detail={
            "endpoint": "exceedances", "variable": variable, "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None, "land_use": list(land_use), "sensor_ids": list(sensor_ids),
            "total": result["total"]})
    return result


@router.get("/heatmap")
def get_heatmap(
    request: Request,
    variable: Variable,
    start: date,
    end: date,
    land_use: LandUses = [],      # noqa: B006
    sensor_ids: SensorIds = [],   # noqa: B006
    exclude_flagged: bool = True,
    session: Session = Depends(can_filter),
) -> dict[str, Any]:
    """Hour-of-day x month grid (UC2 temporal heat map) built from valid hourly aggregates."""
    _check_range(start, end, "heatmap")
    with request.app.state.db.transaction() as tx:
        _limit(tx, session)
        result = data.heatmap(tx, variable, start, end, list(land_use), list(sensor_ids), exclude_flagged)
        audit.record(tx, "data_query", user_id=session.user_id, ip=client_ip(request), detail={
            "endpoint": "heatmap", "variable": variable, "start": start.isoformat(), "end": end.isoformat(),
            "land_use": list(land_use), "sensor_ids": list(sensor_ids), "exclude_flagged": exclude_flagged,
            "cells": len(result["cells"])})
    if not result["cells"]:
        raise AppError(404, "no_data", MSG_NO_DATA)
    return result
