"""
Threshold management (BUILD_PROMPT §4.5, proposal risk R24): edit a threshold's value with a
required reason, keep the change log (append-only `threshold_history`), and recompute that
threshold's exceedances. `manage_thresholds` (administrators with MFA) only.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request

from ..db import Transaction, to_datetime
from ..errors import AppError
from ..schemas import ThresholdUpdate
from ..security import Session, require_permission
from ..variables import VARIABLES
from . import admin_common

router = APIRouter(prefix="/admin/thresholds", tags=["admin"])
can_manage = require_permission("manage_thresholds")
ThresholdId = Annotated[int, Path(ge=1, le=1_000_000)]

# Exceedances from VALID daily aggregates ('all' variant), the same rule as the pipeline
# (data_pipeline/etl.py build_aggregates). One fixed statement per statistic and operator:
# nothing from the request or the database is put into SQL text.
RECOMPUTE_SQL = {
    ("day", ">"): """INSERT INTO exceedances (sensor_id, threshold_id, date_local, observed_value, completeness_pct)
                     SELECT sensor_id, ?, bucket_start_local, mean, completeness_pct FROM aggregates
                     WHERE period = 'day' AND qc_mode = 'all' AND variable = ? AND is_valid = 1 AND mean > ?""",
    ("day", ">="): """INSERT INTO exceedances (sensor_id, threshold_id, date_local, observed_value, completeness_pct)
                      SELECT sensor_id, ?, bucket_start_local, mean, completeness_pct FROM aggregates
                      WHERE period = 'day' AND qc_mode = 'all' AND variable = ? AND is_valid = 1 AND mean >= ?""",
    ("day_max", ">"): """INSERT INTO exceedances (sensor_id, threshold_id, date_local, observed_value, completeness_pct)
                         SELECT sensor_id, ?, bucket_start_local, max, completeness_pct FROM aggregates
                         WHERE period = 'day' AND qc_mode = 'all' AND variable = ? AND is_valid = 1 AND max > ?""",
    ("day_max", ">="): """INSERT INTO exceedances (sensor_id, threshold_id, date_local, observed_value,
                                                   completeness_pct)
                          SELECT sensor_id, ?, bucket_start_local, max, completeness_pct FROM aggregates
                          WHERE period = 'day' AND qc_mode = 'all' AND variable = ? AND is_valid = 1
                            AND max >= ?""",
}
SQL_THRESHOLDS = """SELECT threshold_id, variable, period, operator, value, label, source, updated_by, updated_at
                    FROM thresholds ORDER BY variable, period, value"""
SQL_HISTORY = """SELECT h.history_id, h.threshold_id, h.old_value, h.new_value, h.reason, h.changed_at,
                        u.username AS changed_by
                 FROM threshold_history h LEFT JOIN users u ON u.user_id = h.changed_by
                 ORDER BY h.changed_at DESC, h.history_id DESC"""


def recompute_exceedances(tx: Transaction, threshold: dict[str, Any]) -> int:
    """Replace one threshold's exceedances. Returns the new count."""
    sql = RECOMPUTE_SQL.get((threshold["period"], threshold["operator"]))
    if sql is None:   # unknown statistic/operator: refuse rather than guess
        raise AppError(500, "threshold_rule_unknown", "This threshold cannot be recalculated.")
    tx.execute("DELETE FROM exceedances WHERE threshold_id = ?", (threshold["threshold_id"],))
    tx.execute(sql, (threshold["threshold_id"], threshold["variable"], threshold["value"]))
    return tx.fetch_one("SELECT COUNT(*) AS n FROM exceedances WHERE threshold_id = ?",
                        (threshold["threshold_id"],))["n"]


def _iso(value: Any) -> str | None:
    moment = to_datetime(value)
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if moment else None


def _out(row: dict[str, Any], counts: dict[int, int]) -> dict[str, Any]:
    return {"threshold_id": row["threshold_id"], "variable": row["variable"],
            "variable_label": VARIABLES.get(row["variable"], {}).get("label", row["variable"]),
            "unit": VARIABLES.get(row["variable"], {}).get("unit", ""),
            "statistic": "daily mean" if row["period"] == "day" else "daily maximum",
            "period": row["period"], "operator": row["operator"], "value": row["value"], "label": row["label"],
            "source": row["source"], "updated_at": _iso(row["updated_at"]),
            "exceedance_days": counts.get(row["threshold_id"], 0)}


def _listing(tx: Transaction) -> dict[str, Any]:
    counts = {r["threshold_id"]: r["n"] for r in tx.fetch_all(
        "SELECT threshold_id, COUNT(*) AS n FROM exceedances GROUP BY threshold_id")}
    history = [{**h, "changed_at": _iso(h["changed_at"])} for h in tx.fetch_all(SQL_HISTORY)]
    return {"thresholds": [_out(r, counts) for r in tx.fetch_all(SQL_THRESHOLDS)], "history": history}


@router.get("")
def list_thresholds(request: Request, session: Session = Depends(can_manage)) -> dict[str, Any]:
    """Every threshold with its exceedance count, and the full change log (newest first)."""
    with request.app.state.db.transaction() as tx:
        admin_common.limit(tx, session)
        return _listing(tx)


@router.put("/{threshold_id}")
def update_threshold(request: Request, threshold_id: ThresholdId, body: ThresholdUpdate,
                     session: Session = Depends(can_manage)) -> dict[str, Any]:
    """Change the value; log old/new/reason/who/when; recompute this threshold's exceedances."""
    with request.app.state.db.transaction() as tx:
        admin_common.limit(tx, session)
        before = next((r for r in tx.fetch_all(SQL_THRESHOLDS) if r["threshold_id"] == threshold_id), None)
        if before is None:
            raise AppError(404, "threshold_not_found", "Threshold not found.")
        if float(before["value"]) == body.value:
            raise AppError(422, "nothing_to_change", "The new value is the same as the current value.")
        clash = tx.fetch_one("SELECT threshold_id FROM thresholds WHERE variable = ? AND period = ? AND value = ? "
                             "AND threshold_id <> ?", (before["variable"], before["period"], body.value, threshold_id))
        if clash:
            raise AppError(409, "duplicate_threshold", "Another threshold for this variable already uses this value.")
        old_count = tx.fetch_one("SELECT COUNT(*) AS n FROM exceedances WHERE threshold_id = ?", (threshold_id,))["n"]
        tx.execute("UPDATE thresholds SET value = ?, updated_by = ?, updated_at = ? WHERE threshold_id = ?",
                   (body.value, session.user_id, datetime.now(UTC), threshold_id))
        tx.execute("INSERT INTO threshold_history (threshold_id, old_value, new_value, reason, changed_by) "
                   "VALUES (?, ?, ?, ?, ?)", (threshold_id, before["value"], body.value, body.reason, session.user_id))
        new_count = recompute_exceedances(tx, {**before, "value": body.value})
        admin_common.record(tx, request, session, "threshold_updated", {
            "threshold_id": threshold_id, "label": before["label"], "old_value": before["value"],
            "new_value": body.value, "reason": body.reason, "exceedance_days_before": old_count,
            "exceedance_days_after": new_count})
        listing = _listing(tx)
    return {"message": f"Threshold updated. Exceedances recalculated: {new_count} days now exceed it "
                       f"(was {old_count}).", **listing}
