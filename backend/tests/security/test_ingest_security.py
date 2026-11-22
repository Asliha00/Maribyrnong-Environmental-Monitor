"""SEC-03 authenticated, replay-resistant device ingestion (POST /api/ingest)."""
import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from backend.app.services import live
from backend.tests.conftest import admin_with_mfa, audit_actions, post
from backend.tests.test_data_api import data_db  # noqa: F401 - fixture

URL = "/api/ingest"
KEY = "k" * 43


def now_iso(delta: timedelta = timedelta(0)) -> str:
    return (datetime.now(UTC) + delta).isoformat()


@pytest.fixture
def device(client, db_conn, data_db):  # noqa: F811
    db_conn.execute("UPDATE sensors SET auth_key_hash = ? WHERE sensor_id = 1", (live.key_hash(KEY),))
    db_conn.commit()
    return client


def send(client, body=None, device_id="A-01", key=KEY, **headers):
    body = body if body is not None else {"timestamp": now_iso(), "temperature": 21.5, "pm25": 6.0}
    return client.post(URL, json=body, headers={"X-Device-Id": device_id, "X-Device-Key": key, **headers})


def readings(db_conn, sensor_id=1):
    return db_conn.execute("SELECT COUNT(*) FROM readings WHERE sensor_id = ?", (sensor_id,)).fetchone()[0]


def test_bad_key_401_and_logged_with_ip(device, db_conn):
    before = readings(db_conn)
    for device_id, key in (("A-01", "wrong-key"), ("A-01", ""), ("NOPE-9", KEY), ("", KEY), ("B-02", KEY)):
        r = send(device, device_id=device_id, key=key)
        assert r.status_code == 401 and r.json()["error"]["message"] == "Invalid device credentials."
    assert readings(db_conn) == before
    rows = db_conn.execute("SELECT ip_address, detail_json FROM audit_log WHERE action = 'ingest_rejected'").fetchall()
    assert len(rows) == 5 and all(r["ip_address"] for r in rows)       # source IP recorded
    assert all(KEY not in r["detail_json"] for r in rows)              # the key is never logged


def test_repeated_failures_from_one_address_are_slowed(device, monkeypatch):
    from backend.app.routers import ingest as ingest_router

    monkeypatch.setattr(ingest_router, "FAILURES_PER_IP", ingest_router.rate_limit.Limit("ingest-fail:ip", 3, 60))
    codes = [send(device, key="guess").status_code for _ in range(5)]
    assert codes == [401, 401, 401, 429, 429]


def test_stale_timestamp_rejected(device, db_conn):
    before = readings(db_conn)
    for delta in (timedelta(minutes=-6), timedelta(minutes=6), timedelta(days=-400)):
        r = send(device, {"timestamp": now_iso(delta), "temperature": 20.0})
        assert r.status_code == 400 and r.json()["error"]["code"] == "stale_timestamp"
    assert send(device, {"timestamp": now_iso(timedelta(minutes=-4)), "temperature": 20.0}).status_code == 200
    assert readings(db_conn) == before + 1
    assert [a["reason"] for a in audit_actions(db_conn, "ingest_rejected")] == ["stale_timestamp"] * 3


def test_replayed_payload_is_duplicate(device, db_conn):
    body = {"timestamp": now_iso(), "temperature": 21.5, "pm25": 6.0}
    first, second = send(device, body), send(device, body)
    assert first.status_code == 200 and first.json()["status"] == "stored"
    assert second.status_code == 200 and second.json()["status"] == "duplicate"
    assert readings(db_conn) == 1 + 2                                   # fixture had 2 for A-01
    assert db_conn.execute("SELECT COUNT(*) FROM error_log WHERE error_type = 'duplicate'").fetchone()[0] == 1


def test_decommissioned_sensor_rejected(device, db_conn):
    db_conn.execute("UPDATE sensors SET status = 'Inactive' WHERE sensor_id = 1")
    db_conn.commit()
    before = readings(db_conn)
    r = send(device)
    assert r.status_code == 403 and r.json()["error"]["code"] == "sensor_inactive"
    assert readings(db_conn) == before
    assert audit_actions(db_conn, "ingest_rejected")[0]["reason"] == "sensor_inactive"


def test_key_not_stored_in_plaintext(client, make_user, db_conn, data_db, monkeypatch):  # noqa: F811
    admin_with_mfa(client, make_user, db_conn)
    r = post(client, "/api/admin/sensors", {"sensor_code": "SIM-01", "sensor_name": "Simulator", "device_family":
                                            "mcc_aq", "land_use": "Parkland", "latitude": -37.8, "longitude": 144.89})
    key = r.json()["device_key"]
    stored = db_conn.execute("SELECT auth_key_hash FROM sensors WHERE sensor_code = 'SIM-01'").fetchone()[0]
    assert key not in stored and stored == "sha256$" + hashlib.sha256(key.encode()).hexdigest()
    dump = "\n".join(str(tuple(r)) for t in ("sensors", "audit_log") for r in db_conn.execute(f"SELECT * FROM {t}"))  # noqa: S608
    assert key not in dump
    # constant-time comparison, also for unknown devices (no timing difference to probe)
    calls = []
    monkeypatch.setattr(live.hmac, "compare_digest", lambda a, b: calls.append((a, b)) or False)
    assert live.key_matches(None, key) is False and live.key_matches(stored, "x") is False
    assert len(calls) == 2
    client.cookies.clear()
    assert send(client, device_id="SIM-01", key=key).status_code == 401   # compare_digest patched to False


@pytest.mark.parametrize(("body", "code"), [
    ({"timestamp": "2026-01-01T10:00:00", "temperature": 20}, "invalid_timestamp"),        # no offset
    ({"timestamp": "yesterday", "temperature": 20}, "invalid_timestamp"),
    ({"temperature": 20}, "invalid_timestamp"),
    ({"timestamp": "NOW", "temperature": 20}, "invalid_timestamp"),
    ({"timestamp": None, "temperature": 20}, "invalid_timestamp"),
])
def test_bad_timestamps_rejected(device, body, code):
    r = send(device, body)
    assert r.status_code == 422 and r.json()["error"]["code"] == code


def test_hostile_bodies_rejected(device, db_conn):
    before = readings(db_conn)
    cases = [({"timestamp": now_iso(), "temperature": "21; DROP TABLE readings"}, 422),
             ({"timestamp": now_iso(), "temperature_c": 21}, 422),          # canonical name is not a device field
             ({"timestamp": now_iso(), "' OR 1=1--": 1}, 422),
             ({"timestamp": now_iso(), "temperature": True}, 422),
             ({"timestamp": now_iso()}, 422),
             ({"timestamp": now_iso(), "temperature": None}, 422),
             ([1, 2, 3], 422)]
    for body, status in cases:
        assert send(device, body).status_code == status, body
    big = {"timestamp": now_iso(), "temperature": 20, "pm25": 1.0}
    r = device.post(URL, content=str(big).ljust(5000).encode(),
                    headers={"X-Device-Id": "A-01", "X-Device-Key": KEY, "Content-Type": "application/json"})
    assert r.status_code == 413
    r = device.post(URL, content=b"{not json", headers={"X-Device-Id": "A-01", "X-Device-Key": KEY})
    assert r.status_code == 422
    assert readings(db_conn) == before
