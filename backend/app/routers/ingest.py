"""
POST /api/ingest: live readings from field devices (UC4, BUILD_PROMPT §4.6; SEC-03).

A device sends `X-Device-Id` (its sensor code) and `X-Device-Key` (the 256-bit key shown once
when an administrator registered it) with a JSON body
`{"timestamp": "<ISO-8601 with offset>", "<field>": <number>, ...}` using the device's own
field names (e.g. temperature, humidity, pm25).

- Wrong or unknown device/key -> 401, audited with the source IP; repeated failures from one
  address are rate limited (429).
- Decommissioned sensor -> 403. Timestamp more than 5 minutes from server time -> 400 (replay).
- Unknown fields, non-numbers or a body over 4 KB -> 422/413.
- A reading for a time already stored -> ignored, logged, 200 "duplicate" (no retry loops).
- Out-of-range values -> logged in error_log, the rest stored, 200 (no alert loops).
"""
from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from ..errors import AppError
from ..security import client_ip
from ..services import audit, ingest, live, rate_limit

router = APIRouter(tags=["ingest"])

MAX_BODY_BYTES = 4096
MAX_CLOCK_SKEW = timedelta(minutes=5)
READINGS_PER_DEVICE = rate_limit.Limit("ingest:device", 60, 60)   # 1 per second at most, on average
FAILURES_PER_IP = rate_limit.Limit("ingest-fail:ip", 10, 60)        # slows key guessing
MSG_AUTH = "Invalid device credentials."


def _reject(request: Request, reason: str, device_id: str, status: int, code: str, message: str,
            headers: dict[str, str] | None = None) -> AppError:
    with request.app.state.db.transaction() as tx:
        audit.record(tx, "ingest_rejected", ip=client_ip(request),
                     detail={"reason": reason, "device_id": device_id[:40]})
    return AppError(status, code, message, headers=headers)


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise AppError(422, "invalid_timestamp", "timestamp must be an ISO-8601 date-time with a UTC offset.")
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AppError(422, "invalid_timestamp", "timestamp must be an ISO-8601 date-time with a UTC offset.") \
            from exc
    if ts.tzinfo is None:
        raise AppError(422, "invalid_timestamp", "timestamp must include a UTC offset (for example +11:00 or Z).")
    return ts.astimezone(UTC)


@router.post("/ingest")
async def ingest_reading(request: Request) -> dict[str, Any]:
    """Store one reading from an authenticated device and update its aggregates."""
    body = await request.body()
    # Database work is blocking: run it in a worker thread, not on the event loop
    return await run_in_threadpool(_handle, request, body)


def _handle(request: Request, body: bytes) -> dict[str, Any]:
    ip = client_ip(request)
    device_id = request.headers.get("x-device-id", "")[:64]
    key = request.headers.get("x-device-key", "")[:128]
    with request.app.state.db.transaction() as tx:
        sensor = live.find_sensor(tx, device_id) if device_id else None
        ok = live.key_matches(sensor["auth_key_hash"] if sensor else None, key)
        allowed, retry = (True, 0) if ok else rate_limit.hit(tx, FAILURES_PER_IP, ip)
    if not ok:
        if not allowed:   # many failures from this address: slow it down (still audited)
            raise _reject(request, "too_many_failures", device_id, 429, "rate_limited",
                          "Too many failed attempts. Please wait and try again.", {"Retry-After": str(retry)})
        raise _reject(request, "bad_credentials", device_id, 401, "invalid_device", MSG_AUTH)
    if sensor["status"] != "Active":
        raise _reject(request, "sensor_inactive", device_id, 403, "sensor_inactive",
                      "This sensor is decommissioned and cannot send data.")

    if len(body) > MAX_BODY_BYTES:
        raise AppError(413, "payload_too_large", "One reading at a time, at most 4 KB.")
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise AppError(422, "invalid_json", "The body must be a JSON object.") from exc
    if not isinstance(payload, dict):
        raise AppError(422, "invalid_json", "The body must be a JSON object.")
    ts = _parse_timestamp(payload.get("timestamp"))
    config, _, _ = ingest.pipeline()
    allowed_fields = set(config.COLUMN_MAP[sensor["device_family"]])
    unknown = sorted(k for k in payload if k != "timestamp" and k not in allowed_fields)
    if unknown:
        raise AppError(422, "unknown_fields", f"Unknown fields for a {sensor['device_family']} device: "
                                              f"{', '.join(unknown[:5])[:200]}.")
    values: dict[str, float | None] = {}
    for name in allowed_fields & set(payload):
        v = payload[name]
        if v is not None and (isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v)):
            raise AppError(422, "invalid_value", f"{name} must be a number or null.")
        values[name] = v
    if not any(v is not None for v in values.values()):
        raise AppError(422, "no_values", "The reading has no measurement values.")
    if live.clock_skew(ts) > MAX_CLOCK_SKEW:
        raise _reject(request, "stale_timestamp", device_id, 400, "stale_timestamp",
                      "The timestamp is more than 5 minutes from server time. Check the device clock.")

    with request.app.state.db.transaction() as tx:
        allowed, retry = rate_limit.hit(tx, READINGS_PER_DEVICE, str(sensor["sensor_id"]))
        if not allowed:
            raise AppError(429, "rate_limited", "Too many readings. Please slow down.",
                           headers={"Retry-After": str(retry)})
        result = live.store_reading(tx, sensor, values, ts)
    return {"sensor_code": sensor["sensor_code"], **result}
