"""SEC-19 injection prevention: hostile input in every data-API parameter is rejected
(400/404/422, never 500) and the database is left unchanged."""
from urllib.parse import quote

import pytest

from backend.tests.conftest import admin_with_mfa, email_of, login, post, put
from backend.tests.test_data_api import data_db  # noqa: F401 - reuse the fixture database

PAYLOADS = [
    "' OR 1=1--",
    "pm25; DROP TABLE readings",
    "pm25' UNION SELECT password_hash FROM users--",
    "1; DELETE FROM users",
    "1 OR 1=1",
    "../../etc/passwd",
    "<script>alert(1)</script>",
    "pm25\u0000",                 # NUL byte
    "ｐｍ２５",                     # full-width look-alike of "pm25"
    "pm25​",                 # zero-width space
    "temperature_c--",
    "%27%20OR%201%3D1",
    "2025-07-01' OR '1'='1",
    "9" * 400,                     # oversized
]
# Tables a rejected request may legitimately touch: the shared rate-limit counter.
LEGITIMATE_WRITES = {"rate_limits"}

ENDPOINTS = {
    "/api/readings": {"variable": "pm25", "start": "2025-07-01", "end": "2025-07-07", "resolution": "day",
                      "land_use": "Parkland", "sensor_ids": "1", "exclude_flagged": "true"},
    "/api/exceedances": {"start": "2025-07-01", "end": "2025-07-07", "variable": "pm25", "land_use": "Parkland",
                         "sensor_ids": "1", "sort": "date", "order": "desc", "limit": "10", "offset": "0"},
    "/api/heatmap": {"variable": "pm25", "start": "2025-07-01", "end": "2025-07-07", "land_use": "Parkland",
                     "sensor_ids": "1", "exclude_flagged": "true"},
    "/api/auth/check": {"permission": "view_data"},
    "/api/quality/completeness": {"variable": "pm25", "start": "2025-07-01", "end": "2025-07-07"},
    "/api/quality/errors": {"sensor_id": "1", "error_type": "out_of_range", "variable": "pm25",
                            "start": "2025-07-01", "end": "2025-07-07", "limit": "10", "offset": "0"},
    "/api/quality/runs": {"limit": "10"},
    "/api/analysis/summary": {"start": "2025-07-01", "end": "2025-07-07"},
    "/api/analysis/disparities": {"start": "2025-07-01", "end": "2025-07-07"},
}


def _snapshot(conn):
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    schema = [tuple(r) for r in conn.execute("SELECT type, name, sql FROM sqlite_master ORDER BY name")]
    counts = {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]  # noqa: S608 - names from sqlite_master
              for t in tables if t not in LEGITIMATE_WRITES and t != "sqlite_sequence"}
    return schema, counts


@pytest.fixture
def analyst(client, make_user, db_conn, data_db):  # noqa: F811
    login(client, email_of(db_conn, make_user(role="analyst")))
    return client


CASES = [(url, param, payload) for url, params in ENDPOINTS.items() for param in params for payload in PAYLOADS]


@pytest.mark.parametrize(("url", "param", "payload"), CASES, ids=[f"{u}:{p}:{i}" for i, (u, p, _) in enumerate(CASES)])
def test_hostile_parameter_is_rejected(analyst, db_conn, url, param, payload):
    before = _snapshot(db_conn)
    params = dict(ENDPOINTS[url])
    params[param] = payload
    response = analyst.get(url, params=params)
    assert response.status_code in (400, 404, 422), (param, payload, response.status_code, response.text[:200])
    assert "Traceback" not in response.text and "sqlite" not in response.text.lower()
    assert _snapshot(db_conn) == before, "database changed after a rejected request"


@pytest.mark.parametrize("payload", PAYLOADS)
def test_hostile_path_parameter(analyst, db_conn, payload):
    before = _snapshot(db_conn)
    # percent-encoded, as an attacker would send it (raw NUL cannot even be put in a URL)
    response = analyst.get(f"/api/sensors/{quote(payload, safe='')}")
    assert response.status_code in (400, 404, 422)
    assert _snapshot(db_conn) == before


def test_hostile_login_fields_rejected_or_treated_as_data(client, db_conn):
    """Login takes free text; it must be treated as data, never as SQL."""
    before = _snapshot(db_conn)
    for payload in PAYLOADS:
        r = client.post("/api/auth/login", json={"email": f"{payload}@example.org", "password": payload})
        assert r.status_code in (401, 422, 429)
    after_schema, after_counts = _snapshot(db_conn)
    assert after_schema == before[0]
    assert {k: v for k, v in after_counts.items() if k != "audit_log"} == \
        {k: v for k, v in before[1].items() if k != "audit_log"}   # only failed-login audit rows were added


def test_too_many_sensor_ids_rejected(analyst):
    params = [("variable", "pm25"), ("start", "2025-07-01"), ("end", "2025-07-07")] + [("sensor_ids", str(i))
                                                                                     for i in range(1, 22)]
    assert analyst.get("/api/readings", params=params).status_code == 422


EXPORT_BODY = {"format": "csv", "variable": "pm25", "resolution": "day", "start": "2025-07-01", "end": "2025-07-07",
               "land_use": ["Parkland"], "sensor_ids": [1], "exclude_flagged": True}
EXPORT_CASES = [(field, payload) for field in EXPORT_BODY for payload in PAYLOADS]


@pytest.mark.parametrize(("field", "payload"), EXPORT_CASES,
                         ids=[f"export:{f}:{i}" for i, (f, _) in enumerate(EXPORT_CASES)])
def test_hostile_export_field_is_rejected(analyst, db_conn, field, payload):
    """POST /api/reports/export: a hostile value in any JSON field (or inside a list) is
    rejected before any query or log write."""
    before = _snapshot(db_conn)
    body = dict(EXPORT_BODY)
    body[field] = [payload] if isinstance(body[field], list) else payload
    response = post(analyst, "/api/reports/export", body)
    assert response.status_code in (400, 404, 422), (field, payload, response.status_code, response.text[:200])
    assert "Traceback" not in response.text and "sqlite" not in response.text.lower()
    assert _snapshot(db_conn) == before, "database changed after a rejected export"



# ---------- administration bodies (Phase 5): hostile text is refused or stored as plain data ----------
ADMIN_BODIES = {
    ("POST", "/api/admin/sensors"): {"sensor_code": "INJ-01", "sensor_name": "Injection Probe",
                                     "device_family": "mcc_aq", "land_use": "Parkland", "latitude": -37.80,
                                     "longitude": 144.89, "notes": "x"},
    ("PUT", "/api/admin/sensors/1"): {"sensor_name": "Alpha", "notes": "x"},
    ("POST", "/api/admin/users"): {"username": "inj.probe", "email": "inj.probe@example.org", "role_id": 2},
    ("PUT", "/api/admin/thresholds/1"): {"value": 30, "reason": "A valid reason for the probe."},
    ("POST", "/api/admin/ingest-upload"): {"pathname": "uploads/x-0123456789abcdef0123456789abcdef.csv",
                                           "sensor_id": 1},
}
ADMIN_CASES = [(m, u, field, payload) for (m, u), body in ADMIN_BODIES.items() for field in body
               for payload in PAYLOADS]
TEXT_FIELDS = {"sensor_name", "notes", "reason", "username"}   # stored literally if otherwise valid


@pytest.fixture
def admin(client, make_user, db_conn, data_db):  # noqa: F811
    admin_with_mfa(client, make_user, db_conn)
    return client


@pytest.mark.parametrize(("method", "url", "field", "payload"), ADMIN_CASES,
                         ids=[f"{m}:{u}:{f}:{i}" for i, (m, u, f, _) in enumerate(ADMIN_CASES)])
def test_hostile_admin_field(admin, db_conn, method, url, field, payload):
    tables = ("users", "roles", "readings", "aggregates")
    before = {t: db_conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}  # noqa: S608
    body = {**ADMIN_BODIES[(method, url)], field: payload}
    r = post(admin, url, body) if method == "POST" else put(admin, url, body)
    assert r.status_code != 500 and "Traceback" not in r.text and "sqlite" not in r.text.lower()
    if r.status_code in (200, 201):
        assert field in TEXT_FIELDS, (field, payload, r.status_code)
        stored = r.json().get("sensor", {}).get(field) or r.json().get("user", {}).get(field) or next(
            (h["reason"] for h in r.json().get("history", []) if field == "reason"), None)
        assert stored == payload.strip()                       # kept as plain text, not interpreted
    else:
        assert r.status_code in (400, 404, 409, 422), (field, payload, r.status_code)
    after = {t: db_conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}  # noqa: S608
    assert after["roles"] == before["roles"] and after["readings"] == before["readings"]
    assert after["users"] in (before["users"], before["users"] + 1)
