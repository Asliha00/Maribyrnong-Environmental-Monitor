"""
Insights API (BUILD_PROMPT §4.3, §5): /api/analysis/{summary, trends, diurnal,
green-infrastructure, disparities, recommendations}. Any signed-in user (`view_data`).

All six read one computation (`analysis.build_insights`, cached until the data changes), so
the numbers on the page always agree with each other. Optional `start`/`end` (local dates);
the default is the whole data range.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Request

from ..errors import AppError
from ..security import Session, require_permission
from ..services import analysis, data
from .data import _limit

router = APIRouter(prefix="/analysis", tags=["analysis"])
can_view = require_permission("view_data")
MAX_DAYS = 800


def _insights(request: Request, session: Session, start: date | None, end: date | None) -> dict[str, Any]:
    with request.app.state.db.transaction() as tx:
        _limit(tx, session)
        rng = data.meta(tx)["data_range"]
        if not rng["first_day"]:
            raise AppError(404, "no_data", "No data available for the selected filters.")
        start = start or date.fromisoformat(rng["first_day"])
        end = end or date.fromisoformat(rng["last_day"])
        if start > end:
            raise AppError(400, "invalid_date_range", "Invalid date range selected.")
        if (end - start).days + 1 > MAX_DAYS:
            raise AppError(400, "range_too_long", f"Insights cover up to {MAX_DAYS} days at a time.")
        return analysis.build_insights(tx, start, end)


def _frame(r: dict[str, Any]) -> dict[str, Any]:
    return {"start": r["start"], "end": r["end"], "days": r["days"], "months": r["months"],
            "thresholds": r["thresholds"]}


@router.get("/summary")
def summary(request: Request, start: date | None = None, end: date | None = None,
            session: Session = Depends(can_view)) -> dict[str, Any]:
    """Headline numbers for the top of the Insights page."""
    r = _insights(request, session, start, end)
    sites = {s["sensor_code"]: s for s in r["sites"]}
    pick = lambda key: sites[r["rankings"][key][0]] if r["rankings"][key] else None  # noqa: E731
    warm, pm = pick("temperature"), pick("pm25")
    return {**_frame(r),
            "sensors": len(r["sites"]),
            "warmest_site": warm and {"sensor_code": warm["sensor_code"], "sensor_name": warm["sensor_name"],
                                      **warm["temperature_vs_others"]},
            "highest_pm25_site": pm and {"sensor_code": pm["sensor_code"], "sensor_name": pm["sensor_name"],
                                         **pm["pm25_vs_others"]},
            "park_effect": r["green_infrastructure"]["all_hours"],
            "park_effect_hot_afternoons": r["green_infrastructure"]["hot_afternoons"],
            "hot_days": r["green_infrastructure"]["hot_days"],
            "recommendations": len(r["recommendations"])}


@router.get("/trends")
def trends(request: Request, start: date | None = None, end: date | None = None,
           session: Session = Depends(can_view)) -> dict[str, Any]:
    """Aim 1: monthly means and the slope per sensor, absolute and relative to the network."""
    r = _insights(request, session, start, end)
    return {**_frame(r), "trends": r["trends"]}


@router.get("/diurnal")
def diurnal(request: Request, start: date | None = None, end: date | None = None,
            session: Session = Depends(can_view)) -> dict[str, Any]:
    """Aim 3: average day (hour-of-day means) and seasonal means per sensor."""
    r = _insights(request, session, start, end)
    return {**_frame(r), "diurnal": r["diurnal"], "seasonal": r["seasonal"]}


@router.get("/green-infrastructure")
def green_infrastructure(request: Request, start: date | None = None, end: date | None = None,
                         session: Session = Depends(can_view)) -> dict[str, Any]:
    """Aim 4: parks versus other sites on matched hours, all hours and hot afternoons."""
    r = _insights(request, session, start, end)
    return {**_frame(r), **r["green_infrastructure"]}


@router.get("/disparities")
def disparities(request: Request, start: date | None = None, end: date | None = None,
                session: Session = Depends(can_view)) -> dict[str, Any]:
    """Aims 2 and 5: sites compared on the same days, by land use, and sensitive sites."""
    r = _insights(request, session, start, end)
    return {**_frame(r), "sites": r["sites"], "rankings": r["rankings"], "by_land_use": r["by_land_use"],
            "equity": r["equity"]}


@router.get("/recommendations")
def recommendations(request: Request, start: date | None = None, end: date | None = None,
                    session: Session = Depends(can_view)) -> dict[str, Any]:
    """Aims 6 and 7: sensor-network gaps and rule-based recommendations with their evidence."""
    r = _insights(request, session, start, end)
    return {**_frame(r), "network": r["network"], "recommendations": r["recommendations"]}
