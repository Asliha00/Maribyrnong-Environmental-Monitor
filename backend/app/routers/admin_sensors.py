"""
Sensor management (UC5, BUILD_PROMPT §4.5): list, register, edit, decommission, reactivate,
verify location, and issue a device key. `manage_sensors` (administrators with MFA) only.

The device key a live sensor uses for POST /api/ingest (Phase 6) is shown ONCE and stored
only as a SHA-256 hash: it is 256 random bits, so unlike a password it cannot be guessed and
needs no slow hash (DECISIONS.md D-033).
"""
from __future__ import annotations

import hashlib
import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request

from ..db import Transaction
from ..errors import AppError
from ..schemas import SensorCreate, SensorUpdate
from ..security import Session, require_permission
from ..services import data
from ..variables import LAT_BOUNDS, LON_BOUNDS
from . import admin_common

router = APIRouter(prefix="/admin/sensors", tags=["admin"])
can_manage = require_permission("manage_sensors")

MSG_DUPLICATE_NAME = "A sensor with this name already exists. Please use a unique name."
MSG_DUPLICATE_CODE = "A sensor with this code already exists. Please use a unique code."
MSG_BAD_COORDINATES = "Please enter valid GPS coordinates within the municipality boundary."
MSG_REGISTERED = "Sensor registered successfully"
SensorId = Annotated[int, Path(ge=1, le=1_000_000)]

SQL_ADMIN_SENSORS = """SELECT sensor_id, sensor_code, sensor_name, device_family, hardware_id, latitude, longitude,
                              location_verified, land_use, installation_date, status, notes, first_reading_utc,
                              last_reading_utc, auth_key_hash, sensitive_receptor
                       FROM sensors ORDER BY sensor_code"""


def new_device_key() -> tuple[str, str]:
    """(key shown once to the administrator, value stored in sensors.auth_key_hash)."""
    key = secrets.token_urlsafe(32)
    return key, "sha256$" + hashlib.sha256(key.encode()).hexdigest()


def _out(row: dict[str, Any]) -> dict[str, Any]:
    """A sensor as the admin page sees it: never the key hash, only whether a key exists."""
    return {
        "sensor_id": row["sensor_id"], "sensor_code": row["sensor_code"], "sensor_name": row["sensor_name"],
        "device_family": row["device_family"], "hardware_id": row["hardware_id"],
        "latitude": row["latitude"], "longitude": row["longitude"],
        "location_verified": bool(row["location_verified"]), "land_use": row["land_use"],
        "sensitive_receptor": bool(row["sensitive_receptor"]),
        "installation_date": str(row["installation_date"]) if row["installation_date"] else None,
        "status": row["status"], "notes": row["notes"], "has_device_key": bool(row["auth_key_hash"]),
        "first_reading_utc": data._iso_utc(row["first_reading_utc"]),
        "last_reading_utc": data._iso_utc(row["last_reading_utc"]),
    }


def _find(tx: Transaction, sensor_id: int) -> dict[str, Any]:
    row = next((r for r in tx.fetch_all(SQL_ADMIN_SENSORS) if r["sensor_id"] == sensor_id), None)
    if row is None:
        raise AppError(404, "sensor_not_found", "Sensor not found.")
    return row


def _check_coordinates(latitude: float | None, longitude: float | None) -> None:
    ok_lat = latitude is None or LAT_BOUNDS[0] <= latitude <= LAT_BOUNDS[1]
    ok_lon = longitude is None or LON_BOUNDS[0] <= longitude <= LON_BOUNDS[1]
    if not (ok_lat and ok_lon):
        raise AppError(422, "invalid_coordinates", MSG_BAD_COORDINATES)


def _check_unique(tx: Transaction, name: str | None, code: str | None, except_id: int | None = None) -> None:
    for row in tx.fetch_all("SELECT sensor_id, sensor_code, sensor_name FROM sensors"):
        if row["sensor_id"] == except_id:
            continue
        if name is not None and row["sensor_name"].casefold() == name.casefold():
            raise AppError(409, "duplicate_sensor_name", MSG_DUPLICATE_NAME)
        if code is not None and row["sensor_code"].casefold() == code.casefold():
            raise AppError(409, "duplicate_sensor_code", MSG_DUPLICATE_CODE)


@router.get("")
def list_sensors(request: Request, session: Session = Depends(can_manage)) -> dict[str, Any]:
    """Every sensor, including decommissioned ones."""
    with request.app.state.db.transaction() as tx:
        admin_common.limit(tx, session)
        return {"sensors": [_out(r) for r in tx.fetch_all(SQL_ADMIN_SENSORS)]}


@router.post("", status_code=201)
def register_sensor(request: Request, body: SensorCreate, session: Session = Depends(can_manage)) -> dict[str, Any]:
    """Register a sensor and return its device key (shown once)."""
    _check_coordinates(body.latitude, body.longitude)
    key, key_hash = new_device_key()
    with request.app.state.db.transaction() as tx:
        admin_common.limit(tx, session)
        _check_unique(tx, body.sensor_name, body.sensor_code)
        tx.execute("""INSERT INTO sensors (sensor_code, sensor_name, device_family, latitude, longitude,
                                           location_verified, land_use, installation_date, status, auth_key_hash,
                                           notes, sensitive_receptor)
                      VALUES (?, ?, ?, ?, ?, 0, ?, ?, 'Active', ?, ?, ?)""",
                   (body.sensor_code, body.sensor_name, body.device_family, body.latitude, body.longitude,
                    body.land_use, body.installation_date.isoformat() if body.installation_date else None,
                    key_hash, body.notes, int(body.sensitive_receptor)))
        row = next(r for r in tx.fetch_all(SQL_ADMIN_SENSORS) if r["sensor_code"] == body.sensor_code)
        admin_common.record(tx, request, session, "sensor_registered", {
            "sensor_id": row["sensor_id"], "sensor_code": body.sensor_code, "sensor_name": body.sensor_name,
            "device_family": body.device_family, "land_use": body.land_use,
            "latitude": body.latitude, "longitude": body.longitude})
    return {"message": MSG_REGISTERED, "sensor": _out(row), "device_key": key}


@router.put("/{sensor_id}")
def update_sensor(request: Request, sensor_id: SensorId, body: SensorUpdate,
                  session: Session = Depends(can_manage)) -> dict[str, Any]:
    """Edit name, land use, coordinates, notes, installation date, location-verified flag,
    or reactivate (status 'Active')."""
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise AppError(422, "nothing_to_change", "Nothing to change.")
    cleared = [k for k in ("sensor_name", "land_use", "latitude", "longitude", "location_verified", "status",
                           "sensitive_receptor")
               if k in changes and changes[k] is None]
    if cleared:
        raise AppError(422, "validation_error", f"Invalid request: check {', '.join(cleared)}.")
    if changes.get("installation_date") is not None:
        changes["installation_date"] = changes["installation_date"].isoformat()
    _check_coordinates(changes.get("latitude"), changes.get("longitude"))
    with request.app.state.db.transaction() as tx:
        admin_common.limit(tx, session)
        before = _find(tx, sensor_id)
        if "sensor_name" in changes:
            _check_unique(tx, changes["sensor_name"], None, except_id=sensor_id)
        # One fixed statement: unchanged fields are written back with their current values
        merged = {k: changes.get(k, before[k]) for k in ("sensor_name", "land_use", "latitude", "longitude",
                                                          "location_verified", "installation_date", "notes",
                                                          "status", "sensitive_receptor")}
        tx.execute("""UPDATE sensors SET sensor_name = ?, land_use = ?, latitude = ?, longitude = ?,
                                         location_verified = ?, installation_date = ?, notes = ?, status = ?,
                                         sensitive_receptor = ?
                      WHERE sensor_id = ?""",
                   (merged["sensor_name"], merged["land_use"], merged["latitude"], merged["longitude"],
                    int(bool(merged["location_verified"])), merged["installation_date"], merged["notes"],
                    merged["status"], int(bool(merged["sensitive_receptor"])), sensor_id))
        after = _find(tx, sensor_id)
        diff = {k: {"from": _plain(before[k]), "to": _plain(after[k])} for k in merged
                if _plain(before[k]) != _plain(after[k])}
        admin_common.record(tx, request, session, "sensor_updated",
                            {"sensor_id": sensor_id, "sensor_code": before["sensor_code"], "changes": diff})
    return {"message": "Sensor updated.", "sensor": _out(after)}


def _plain(value: Any) -> Any:
    """Comparable, JSON-safe form for the audit diff (dates and 0/1 flags)."""
    if isinstance(value, bool):
        return int(value)
    return str(value) if value is not None and not isinstance(value, int | float | str) else value


@router.delete("/{sensor_id}")
def decommission_sensor(request: Request, sensor_id: SensorId, session: Session = Depends(can_manage)) -> dict:
    """Soft decommission: status 'Inactive'. Readings, aggregates and history are kept."""
    with request.app.state.db.transaction() as tx:
        admin_common.limit(tx, session)
        before = _find(tx, sensor_id)
        if before["status"] == "Inactive":
            raise AppError(409, "already_inactive", "This sensor is already decommissioned.")
        tx.execute("UPDATE sensors SET status = 'Inactive' WHERE sensor_id = ?", (sensor_id,))
        admin_common.record(tx, request, session, "sensor_decommissioned",
                            {"sensor_id": sensor_id, "sensor_code": before["sensor_code"]})
        after = _find(tx, sensor_id)
    return {"message": "Sensor decommissioned. Its data and history are kept.", "sensor": _out(after)}


@router.post("/{sensor_id}/device-key")
def rotate_device_key(request: Request, sensor_id: SensorId, session: Session = Depends(can_manage)) -> dict:
    """Issue a new device key (shown once); the old key stops working immediately."""
    key, key_hash = new_device_key()
    with request.app.state.db.transaction() as tx:
        admin_common.limit(tx, session)
        before = _find(tx, sensor_id)
        tx.execute("UPDATE sensors SET auth_key_hash = ? WHERE sensor_id = ?", (key_hash, sensor_id))
        admin_common.record(tx, request, session, "sensor_device_key_issued",
                            {"sensor_id": sensor_id, "sensor_code": before["sensor_code"],
                             "replaced_existing": bool(before["auth_key_hash"])})
    return {"message": "New device key issued. Copy it now: it will not be shown again.", "device_key": key}
