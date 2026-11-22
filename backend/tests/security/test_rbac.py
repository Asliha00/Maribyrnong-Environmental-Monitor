"""SEC-10 deny by default, SEC-11 role x endpoint permission matrix (proposal R19).

Keep docs/security/permission_matrix.md in sync with MATRIX below.
"""
import pyotp
import pytest
from fastapi.routing import APIRoute

from backend.app.security import AUTHENTICATED, require_permission
from backend.tests.conftest import email_of, login, post
from backend.tests.test_data_api import data_db  # noqa: F401 - fixture

# Routes that are deliberately public. Everything else MUST declare require_permission.
PUBLIC_ROUTES = {
    ("GET", "/api/health"),           # uptime check
    ("POST", "/api/auth/login"),      # no session yet
    ("POST", "/api/auth/refresh"),    # authenticated by the refresh-token cookie itself
    ("POST", "/api/auth/logout"),     # must work with an expired access token; only revokes
    ("POST", "/api/ingest"),          # devices, authenticated by their own key (SEC-03), not a user session
}
DOCS_PATHS = {"/api/docs", "/api/openapi.json", "/api/docs/static"}   # API documentation only


def api_routes(app):
    """(method, path, dependant) for every API route, including routes inside included
    routers (FastAPI 0.16x keeps those as nested objects in app.routes)."""
    found = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            found += [(m, route.path, route.dependant) for m in route.methods]
        elif hasattr(route, "effective_route_contexts"):
            for ctx in route.effective_route_contexts():
                found += [(m, ctx.path, ctx.dependant) for m in ctx.methods]
        else:
            assert route.path in DOCS_PATHS, f"unexpected non-API route {route.path}"
    return found


def _guards(dependant):
    found = []
    for dep in dependant.dependencies:
        if hasattr(dep.call, "required_permission"):
            found.append(dep.call.required_permission)
        found.extend(_guards(dep))
    return found


def test_route_enumeration_is_complete(client):
    """Guard against the test silently seeing no routes: everything in the OpenAPI
    schema must be enumerated by api_routes()."""
    seen = {(m.lower(), path) for m, path, _ in api_routes(client.app)}
    published = {(m, path) for path, ops in client.app.openapi()["paths"].items() for m in ops}
    assert published and published <= seen, f"not enumerated: {published - seen}"


def unprotected_routes(app) -> list[str]:
    return [f"{m} {path}" for m, path, dependant in api_routes(app)
            if (m, path) not in PUBLIC_ROUTES and not _guards(dependant)]


def test_every_route_is_protected(client):
    unprotected = unprotected_routes(client.app)
    assert not unprotected, f"routes without require_permission: {unprotected}"


def test_check_detects_an_unprotected_route(client):
    """Negative test: the check must fail when someone adds a route without a guard."""
    from fastapi import APIRouter

    leaky = APIRouter()

    @leaky.get("/admin/leak")
    def leak():
        return {"secret": "data"}

    client.app.include_router(leaky, prefix="/api")
    assert unprotected_routes(client.app) == ["GET /api/admin/leak"]


def test_unknown_permission_cannot_be_declared():
    with pytest.raises(ValueError):
        require_permission("manage_everything")


def test_public_routes_still_exist(client):
    paths = {(m, path) for m, path, _ in api_routes(client.app)}
    assert PUBLIC_ROUTES <= paths, "allow-list names a route that no longer exists"


# role -> endpoint -> expected status. "admin+mfa" is an administrator whose session passed TOTP.
CHECK = "/api/auth/check?permission="
MATRIX = {
    "/api/me":                         {"anonymous": 401, "analyst": 200, "admin": 200, "admin+mfa": 200},
    CHECK + "view_data":               {"anonymous": 401, "analyst": 200, "admin": 200, "admin+mfa": 200},
    CHECK + "export_data":             {"anonymous": 401, "analyst": 200, "admin": 200, "admin+mfa": 200},
    CHECK + "view_quality":            {"anonymous": 401, "analyst": 200, "admin": 200, "admin+mfa": 200},
    CHECK + "manage_sensors":          {"anonymous": 401, "analyst": 403, "admin": 403, "admin+mfa": 200},
    CHECK + "manage_users":            {"anonymous": 401, "analyst": 403, "admin": 403, "admin+mfa": 200},
    CHECK + "manage_thresholds":       {"anonymous": 401, "analyst": 403, "admin": 403, "admin+mfa": 200},
    # Phase 2 data API: view_data / filter_data (both roles hold both)
    "/api/meta":                       {"anonymous": 401, "analyst": 200, "admin": 200, "admin+mfa": 200},
    "/api/sensors":                    {"anonymous": 401, "analyst": 200, "admin": 200, "admin+mfa": 200},
    "/api/sensors/1":                  {"anonymous": 401, "analyst": 200, "admin": 200, "admin+mfa": 200},
    "/api/readings?variable=pm25&start=2025-07-01&end=2025-07-07":
                                       {"anonymous": 401, "analyst": 200, "admin": 200, "admin+mfa": 200},
    "/api/exceedances":                {"anonymous": 401, "analyst": 200, "admin": 200, "admin+mfa": 200},
    # Phase 3: temporal heat map (filter_data)
    "/api/heatmap?variable=temperature_c&start=2025-07-01&end=2025-07-07":
                                       {"anonymous": 401, "analyst": 200, "admin": 200, "admin+mfa": 200},
    # Phase 5: administration (manage_*, MFA required) and the data-quality page (view_quality)
    "/api/admin/sensors":              {"anonymous": 401, "analyst": 403, "admin": 403, "admin+mfa": 200},
    "/api/admin/users":                {"anonymous": 401, "analyst": 403, "admin": 403, "admin+mfa": 200},
    "/api/admin/thresholds":           {"anonymous": 401, "analyst": 403, "admin": 403, "admin+mfa": 200},
    "/api/quality/completeness?variable=pm25&start=2025-07-01&end=2025-07-07":
                                       {"anonymous": 401, "analyst": 200, "admin": 200, "admin+mfa": 200},
    "/api/quality/errors":             {"anonymous": 401, "analyst": 200, "admin": 200, "admin+mfa": 200},
    "/api/quality/runs":               {"anonymous": 401, "analyst": 200, "admin": 200, "admin+mfa": 200},
    "/api/quality/flags":              {"anonymous": 401, "analyst": 200, "admin": 200, "admin+mfa": 200},
    "/api/quality/security":           {"anonymous": 401, "analyst": 403, "admin": 403, "admin+mfa": 200},
    # Phase 6: Insights (view_data). 200 with data; the matrix fixture has 2 sensors on 7 days.
    "/api/analysis/summary":           {"anonymous": 401, "analyst": 200, "admin": 200, "admin+mfa": 200},
    "/api/analysis/trends":            {"anonymous": 401, "analyst": 200, "admin": 200, "admin+mfa": 200},
    "/api/analysis/diurnal":           {"anonymous": 401, "analyst": 200, "admin": 200, "admin+mfa": 200},
    "/api/analysis/green-infrastructure":
                                       {"anonymous": 401, "analyst": 200, "admin": 200, "admin+mfa": 200},
    "/api/analysis/disparities":       {"anonymous": 401, "analyst": 200, "admin": 200, "admin+mfa": 200},
    "/api/analysis/recommendations":   {"anonymous": 401, "analyst": 200, "admin": 200, "admin+mfa": 200},
}

# State-changing admin routes: tested with a request that would succeed for an admin with MFA,
# so the status shows the guard's decision (CSRF header included, as the frontend sends it).
WRITE_MATRIX = [
    ("POST", "/api/admin/sensors", {"sensor_code": "NEW-9", "sensor_name": "Matrix Probe", "device_family": "mcc_aq",
                                    "land_use": "Parkland", "latitude": -37.80, "longitude": 144.89}),
    ("PUT", "/api/admin/sensors/1", {"notes": "matrix probe"}),
    ("DELETE", "/api/admin/sensors/2", None),
    ("POST", "/api/admin/sensors/1/device-key", None),
    ("POST", "/api/admin/users", {"username": "matrix.probe", "email": "matrix.probe@example.org", "role_id": 2}),
    ("PUT", "/api/admin/thresholds/1", {"value": 30, "reason": "Permission matrix probe change."}),
    ("POST", "/api/admin/ingest-upload", {"pathname": "uploads/x-0123456789abcdef0123456789abcdef.csv",
                                          "sensor_id": 1}),
]
WRITE_EXPECTED = {"anonymous": 401, "analyst": 403, "admin": 403}
# Two roles (D-035): Analyst and Administrator; an administrator is tested with and without MFA.
ROLES = ["anonymous", "analyst", "admin", "admin+mfa"]


def _session_for(client, make_user, db_conn, who):
    if who == "anonymous":
        return
    role = "admin" if who.startswith("admin") else who
    login(client, email_of(db_conn, make_user(role=role)))
    if who == "admin+mfa":
        key = post(client, "/api/auth/mfa/setup").json()["manual_entry_key"]
        assert post(client, "/api/auth/mfa/verify", {"code": pyotp.TOTP(key).now()}).status_code == 200


@pytest.mark.parametrize("who", ROLES)
def test_permission_matrix(client, make_user, db_conn, data_db, who):  # noqa: F811
    _session_for(client, make_user, db_conn, who)
    got = {url: client.get(url).status_code for url in MATRIX}
    expected = {url: row[who] for url, row in MATRIX.items()}
    assert got == expected


def test_authenticated_pseudo_permission_is_distinct():
    assert AUTHENTICATED not in {"view_data", "manage_users"}



@pytest.mark.parametrize("who", ["anonymous", "analyst", "admin"])
def test_admin_writes_are_refused_below_admin_with_mfa(client, make_user, db_conn, data_db, who):  # noqa: F811
    """Every state-changing admin route refuses everyone except an administrator with MFA,
    and nothing changes in the database."""
    _session_for(client, make_user, db_conn, who)
    headers = {"X-CSRF-Token": client.cookies.get("mem_csrf") or "x"}
    if who == "anonymous":
        client.cookies.set("mem_csrf", "x")
    before = [tuple(r) for r in db_conn.execute("SELECT * FROM sensors ORDER BY sensor_id")]
    users_before = db_conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    got = {f"{m} {u}": client.request(m, u, json=b, headers=headers).status_code for m, u, b in WRITE_MATRIX}
    assert got == {f"{m} {u}": WRITE_EXPECTED[who] for m, u, _ in WRITE_MATRIX}
    assert [tuple(r) for r in db_conn.execute("SELECT * FROM sensors ORDER BY sensor_id")] == before
    assert db_conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == users_before
    assert db_conn.execute("SELECT value FROM thresholds WHERE threshold_id = 1").fetchone()[0] == 25


@pytest.mark.parametrize("role", ["analyst", "admin"])
def test_deactivated_account_cannot_log_in(client, make_user, db_conn, role):
    """SEC-12: a deactivated account of either role is refused at login and gets no session."""
    r = login(client, email_of(db_conn, make_user(role=role, active=False)))
    assert r.status_code == 403
    assert r.json()["error"]["message"] == "Your account has been deactivated. Please contact your administrator."
    assert client.get("/api/me").status_code == 401
