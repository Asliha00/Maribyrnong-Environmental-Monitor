"""
Export (UC3, Algorithm 2): POST /api/reports/export -> a CSV or PDF download.

The filters are validated exactly like GET /api/readings (SEC-19). Each export is logged
to `reports` and `audit_log` (user, time, filters, format), failures too, and is rate
limited per user because building a PDF costs far more than a JSON query (SEC-23).
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Request, Response

from ..errors import AppError
from ..schemas import ExportRequest
from ..security import Session, client_ip, require_permission
from ..services import audit, export, rate_limit
from .data import MSG_NO_DATA, _check_range

router = APIRouter(prefix="/reports", tags=["reports"])

EXPORTS_PER_USER = rate_limit.Limit("export:user", 10, 60)
MSG_LARGE = "This export contains a large amount of data and may take a moment to prepare."
MSG_FAILED = "Export failed. Please try again or contact your administrator."
MSG_TOO_BIG = ("This export is too large to download as one file. Choose a shorter date range, fewer sensors "
               "or a coarser resolution.")
MEDIA_TYPES = {"csv": "text/csv; charset=utf-8", "pdf": "application/pdf"}

can_export = require_permission("export_data")


def _filters(body: ExportRequest) -> dict[str, Any]:
    return {"variable": body.variable, "resolution": body.resolution, "start": body.start.isoformat(),
            "end": body.end.isoformat(), "land_use": list(body.land_use), "sensor_ids": list(body.sensor_ids),
            "exclude_flagged": body.exclude_flagged}


def _log(request: Request, session: Session, body: ExportRequest, rows: int, ok: bool, size: int = 0) -> None:
    """One `reports` row per delivered file; every attempt in the audit log."""
    filters = _filters(body)
    with request.app.state.db.transaction() as tx:
        if ok:
            tx.execute("INSERT INTO reports (user_id, report_type, format, filter_json, row_count) "
                       "VALUES (?, ?, ?, ?, ?)",
                       (session.user_id, "readings", body.format, json.dumps(filters, sort_keys=True), rows))
        audit.record(tx, "report_export" if ok else "report_export_failed", user_id=session.user_id,
                     ip=client_ip(request), detail={**filters, "format": body.format, "rows": rows, "bytes": size})


@router.post("/export", response_class=Response,
             responses={200: {"content": {"text/csv": {}, "application/pdf": {}},
                              "description": "The export file (attachment)"},
                        409: {"description": "More than 50,000 rows: resend with confirm_large=true"}})
def export_report(request: Request, body: ExportRequest, session: Session = Depends(can_export)) -> Response:
    """Build the filtered, aggregated data as CSV (metadata block + rows, units in headers) or
    PDF (summary table by mean descending with status, chart, exceedances, data quality)."""
    _check_range(body.start, body.end, body.resolution)
    land_uses, sensor_ids = list(body.land_use), list(body.sensor_ids)
    with request.app.state.db.transaction() as tx:
        allowed, retry_after = rate_limit.hit(tx, EXPORTS_PER_USER, str(session.user_id))
        if not allowed:
            raise AppError(429, "rate_limited", "Too many exports. Please wait a moment and try again.",
                           headers={"Retry-After": str(retry_after)})
        gathered = export.gather(tx, body.variable, body.resolution, body.start, body.end, land_uses, sensor_ids,
                                 body.exclude_flagged)
        rows = export.row_count(gathered.result)
        if not gathered.result["series"]:
            raise AppError(404, "no_data", MSG_NO_DATA)
        if rows > export.LARGE_EXPORT_ROWS and not body.confirm_large:
            raise AppError(409, "large_export", MSG_LARGE, headers={"X-Export-Rows": str(rows)})

    try:
        content = export.render(body.format, gathered)
    except Exception as exc:
        _log(request, session, body, rows, ok=False)
        raise AppError(500, "export_failed", MSG_FAILED) from exc
    if len(content) > export.MAX_EXPORT_BYTES:
        _log(request, session, body, rows, ok=False, size=len(content))
        raise AppError(413, "export_too_large", MSG_TOO_BIG)
    _log(request, session, body, rows, ok=True, size=len(content))
    return Response(content, media_type=MEDIA_TYPES[body.format], headers={
        "Content-Disposition": f'attachment; filename="{export.file_name(gathered.result, body.format)}"',
        "Cache-Control": "no-store",
        "X-Export-Rows": str(rows),
    })
