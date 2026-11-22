"""
POST /api/admin/ingest-upload (BUILD_PROMPT §4.5 step 3): load a CSV that the browser has
already uploaded to the private Blob store. `manage_sensors` (administrators with MFA) only,
rate limited, audited. The file checks and loading are in services/ingest.py (SEC-20).
"""
from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ..errors import AppError
from ..security import Session, require_permission
from ..services import ingest, rate_limit
from . import admin_common
from .admin_sensors import SQL_ADMIN_SENSORS

logger = logging.getLogger("backend.security")
router = APIRouter(prefix="/admin", tags=["admin"])
can_manage = require_permission("manage_sensors")

UPLOADS_PER_ADMIN = rate_limit.Limit("upload:user", 5, 600)   # each one may run for minutes
MSG_FAILED = "The file could not be loaded. Please try again or contact your administrator."


class IngestUploadRequest(BaseModel):
    model_config = {"extra": "forbid"}

    pathname: str = Field(max_length=200)
    sensor_id: Annotated[int, Field(ge=1, le=1_000_000)]
    force: bool = False   # 'Load again': re-process a file whose hash was already loaded


@router.post("/ingest-upload")
def ingest_upload(request: Request, body: IngestUploadRequest, session: Session = Depends(can_manage)) -> dict:
    """Validate, archive and ingest an uploaded CSV for one sensor, then rebuild that sensor's
    aggregates. Returns the run summary."""
    with request.app.state.db.transaction() as tx:
        admin_common.limit(tx, session, UPLOADS_PER_ADMIN)
        sensor = next((r for r in tx.fetch_all(SQL_ADMIN_SENSORS) if r["sensor_id"] == body.sensor_id), None)
    if sensor is None:
        raise AppError(404, "sensor_not_found", "Sensor not found.")
    if sensor["status"] != "Active":
        raise AppError(409, "sensor_inactive", "This sensor is decommissioned. Reactivate it before loading data.")
    target = {k: sensor[k] for k in ("sensor_id", "sensor_code", "sensor_name", "device_family")}
    detail: dict[str, Any] = {"sensor_id": body.sensor_id, "sensor_code": sensor["sensor_code"],
                              "file": ingest.original_name(body.pathname)[:160], "force": body.force}
    try:
        summary = ingest.ingest_upload(request.app.state.settings, body.pathname, target, body.force,
                                       request.headers.get("x-vercel-oidc-token"))
    except ingest.UploadRejected as exc:
        _audit(request, session, "upload_rejected", {**detail, "reason": str(exc)})
        raise AppError(400, "upload_rejected", str(exc)) from exc
    except Exception as exc:
        logger.exception("upload_failed for sensor %s", sensor["sensor_code"])   # server log only (SEC-24)
        _audit(request, session, "upload_failed", {**detail, "error": type(exc).__name__})
        raise AppError(500, "upload_failed", MSG_FAILED) from exc
    _audit(request, session, "upload_ingested", {**detail, **summary})
    return {"message": f"File loaded for {sensor['sensor_code']}: {summary['rows_inserted']:,} new readings.",
            "summary": summary}


def _audit(request: Request, session: Session, action: str, detail: dict[str, Any]) -> None:
    with request.app.state.db.transaction() as tx:
        admin_common.record(tx, request, session, action, detail)
