"""UC5 sensor management: register (with the §4.5 validation messages), edit, verify location,
decommission/reactivate, device keys; admin-only with MFA; every action audited."""
import hashlib
import importlib.util
import json

import pytest

from backend.app.config import ROOT
from backend.app.variables import DEVICE_FAMILIES
from backend.tests.conftest import admin_with_mfa, audit_actions, delete, email_of, login, post, put
from backend.tests.test_data_api import data_db  # noqa: F401 - fixture

URL = "/api/admin/sensors"
NEW = {"sensor_code": "NEW-01", "sensor_name": "Yarraville Gardens", "device_family": "mcc_aq",
       "land_use": "Parkland", "latitude": -37.815, "longitude": 144.885}


@pytest.fixture
def admin(client, make_user, db_conn, data_db):  # noqa: F811
    admin_with_mfa(client, make_user, db_conn)
    return client


def test_device_families_match_the_pipeline():
    spec = importlib.util.spec_from_file_location("pipeline_config", ROOT / "data_pipeline" / "config.py")
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
    assert set(DEVICE_FAMILIES) == set(config.COLUMN_MAP)


def test_register_returns_key_once_and_stores_only_its_hash(admin, db_conn):
    r = post(admin, URL, NEW)
    assert r.status_code == 201
    body = r.json()
    assert body["message"] == "Sensor registered successfully"
    key = body["device_key"]
    assert len(key) >= 43                     # 256 bits, URL-safe base64
    sensor = body["sensor"]
    assert sensor["status"] == "Active" and sensor["location_verified"] is False and sensor["has_device_key"]
    assert "auth_key_hash" not in sensor and key not in admin.get(URL).text
    stored = db_conn.execute("SELECT auth_key_hash FROM sensors WHERE sensor_code = 'NEW-01'").fetchone()[0]
    assert stored == "sha256$" + hashlib.sha256(key.encode()).hexdigest()
    entry = audit_actions(db_conn, "sensor_registered")[0]
    assert entry["sensor_code"] == "NEW-01" and key not in str(entry)


def test_new_sensor_appears_on_the_map_list(admin):
    post(admin, URL, NEW)
    codes = [s["sensor_code"] for s in admin.get("/api/sensors").json()["sensors"]]
    assert "NEW-01" in codes


@pytest.mark.parametrize("name", ["Bravo", "bravo", "  BRAVO  "])
def test_duplicate_name_has_the_uc5_message(admin, name):
    r = post(admin, URL, {**NEW, "sensor_name": name})
    assert r.status_code == 409
    assert r.json()["error"]["message"] == "A sensor with this name already exists. Please use a unique name."


def test_duplicate_code_rejected(admin):
    assert post(admin, URL, {**NEW, "sensor_code": "A-01"}).json()["error"]["code"] == "duplicate_sensor_code"


@pytest.mark.parametrize(("lat", "lon"), [(-37.70, 144.88), (-37.90, 144.88), (-37.80, 144.80), (-37.80, 145.0),
                                          (37.80, 144.88), (-37.80, -144.88)])
def test_coordinates_outside_maribyrnong_rejected(admin, db_conn, lat, lon):
    r = post(admin, URL, {**NEW, "latitude": lat, "longitude": lon})
    assert r.status_code == 422
    error = r.json()["error"]
    assert error["code"] == "invalid_coordinates"
    assert error["message"] == "Please enter valid GPS coordinates within the municipality boundary."
    assert db_conn.execute("SELECT COUNT(*) FROM sensors WHERE sensor_code = 'NEW-01'").fetchone()[0] == 0


@pytest.mark.parametrize("change", [{"latitude": "abc"}, {"latitude": float("nan")}, {"land_use": "Moon"},
                                    {"device_family": "toaster"}, {"sensor_code": "bad code"},
                                    {"sensor_code": "../../x"}, {"sensor_name": "ab"},
                                    {"sensor_name": "x\u0000y"}, {"sensor_name": "x" * 81},
                                    {"auth_key_hash": "sha256$0"}, {"status": "Inactive"}])
def test_invalid_registration_rejected(admin, change):
    body = json.dumps({**NEW, **change}, allow_nan=True)    # NaN must be refused, not stored
    r = admin.post(URL, content=body, headers={"Content-Type": "application/json",
                                               "X-CSRF-Token": admin.cookies.get("mem_csrf")})
    assert r.status_code == 422


def test_edit_verify_location_and_audit_diff(admin, db_conn):
    r = put(admin, f"{URL}/2", {"location_verified": True, "latitude": -37.7930, "notes": "Confirmed on site"})
    assert r.status_code == 200
    s = r.json()["sensor"]
    assert s["location_verified"] is True and s["latitude"] == -37.793 and s["sensor_name"] == "Bravo"
    diff = audit_actions(db_conn, "sensor_updated")[0]["changes"]
    assert diff["location_verified"] == {"from": 0, "to": 1}
    assert diff["latitude"]["to"] == -37.793 and "sensor_name" not in diff
    public = next(x for x in admin.get("/api/sensors").json()["sensors"] if x["sensor_id"] == 2)
    assert public["location_verified"] is True


def test_rename_to_an_existing_name_rejected(admin):
    assert put(admin, f"{URL}/2", {"sensor_name": "alpha"}).status_code == 409
    assert put(admin, f"{URL}/2", {"sensor_name": "Bravo"}).status_code == 200   # its own name is fine


def test_edit_validation(admin):
    assert put(admin, f"{URL}/2", {}).status_code == 422
    assert put(admin, f"{URL}/2", {"sensor_name": None}).status_code == 422
    assert put(admin, f"{URL}/2", {"longitude": 150.0}).json()["error"]["code"] == "invalid_coordinates"
    assert put(admin, f"{URL}/999", {"notes": "x"}).status_code == 404
    assert put(admin, f"{URL}/2", {"sensor_code": "X-1"}).status_code == 422   # the code never changes


def test_decommission_is_soft_and_reversible(admin, db_conn):
    readings_before = db_conn.execute("SELECT COUNT(*) FROM readings WHERE sensor_id = 1").fetchone()[0]
    r = delete(admin, f"{URL}/1")
    assert r.status_code == 200 and r.json()["sensor"]["status"] == "Inactive"
    assert db_conn.execute("SELECT COUNT(*) FROM readings WHERE sensor_id = 1").fetchone()[0] == readings_before
    assert delete(admin, f"{URL}/1").status_code == 409
    assert put(admin, f"{URL}/1", {"status": "Active"}).json()["sensor"]["status"] == "Active"
    assert [a["sensor_code"] for a in audit_actions(db_conn, "sensor_decommissioned")] == ["A-01"]


def test_device_key_rotation(admin, db_conn):
    first = post(admin, URL, NEW).json()["device_key"]
    sid = db_conn.execute("SELECT sensor_id FROM sensors WHERE sensor_code = 'NEW-01'").fetchone()[0]
    second = post(admin, f"{URL}/{sid}/device-key").json()["device_key"]
    assert second != first
    stored = db_conn.execute("SELECT auth_key_hash FROM sensors WHERE sensor_id = ?", (sid,)).fetchone()[0]
    assert stored.endswith(hashlib.sha256(second.encode()).hexdigest())
    assert audit_actions(db_conn, "sensor_device_key_issued")[0]["replaced_existing"] is True


def test_admin_without_mfa_and_other_roles_are_refused(client, make_user, db_conn, data_db):  # noqa: F811
    for role in ("analyst", "admin"):      # this admin has not passed MFA
        client.cookies.clear()
        login(client, email_of(db_conn, make_user(role=role)))
        assert client.get(URL).status_code == 403
        assert post(client, URL, NEW).status_code == 403
        assert put(client, f"{URL}/1", {"notes": "x"}).status_code == 403
        assert delete(client, f"{URL}/1").status_code == 403
    assert db_conn.execute("SELECT status FROM sensors WHERE sensor_id = 1").fetchone()[0] == "Active"


def test_list_includes_inactive_sensors(admin):
    delete(admin, f"{URL}/1")
    sensors = admin.get(URL).json()["sensors"]
    assert {s["sensor_code"]: s["status"] for s in sensors} == {"A-01": "Inactive", "B-02": "Active"}


def test_sensitive_receptor_can_be_set_and_is_public(admin, db_conn):
    r = post(admin, URL, {**NEW, "sensitive_receptor": True})
    assert r.status_code == 201 and r.json()["sensor"]["sensitive_receptor"] is True
    assert put(admin, f"{URL}/2", {"sensitive_receptor": True}).json()["sensor"]["sensitive_receptor"] is True
    assert put(admin, f"{URL}/2", {"sensitive_receptor": None}).status_code == 422
    public = {s["sensor_code"]: s["sensitive_receptor"] for s in admin.get("/api/sensors").json()["sensors"]}
    assert public == {"A-01": False, "B-02": True, "NEW-01": True}
    assert audit_actions(db_conn, "sensor_updated")[0]["changes"]["sensitive_receptor"] == {"from": 0, "to": 1}
