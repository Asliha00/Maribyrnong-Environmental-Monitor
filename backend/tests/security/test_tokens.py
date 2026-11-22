"""SEC-08 token lifecycle."""
import base64
import json
from datetime import UTC, datetime, timedelta

from backend.app.tokens import issue_pair
from backend.tests.conftest import TEST_ENV, email_of, login, post

SECRET = TEST_ENV["JWT_SECRET"]


def _replace_cookies(client, **cookies):
    """Simulate a browser that presents exactly these cookies (e.g. a replayed token)."""
    client.cookies.clear()
    for name, value in cookies.items():
        client.cookies.set(name, value)


def _b64(obj) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()


def test_expired_token_401(client, make_user, db_conn):
    uid = make_user()
    old = datetime.now(UTC) - timedelta(hours=1)
    access, _ = issue_pair(SECRET, uid, mfa=False, now=old)       # expired 30 minutes ago
    client.cookies.set("mem_access", access)
    r = client.get("/api/me")
    assert r.status_code == 401
    assert r.json()["error"] == {"code": "session_expired", "message": "Your session has expired. Please log in again.",
                                 "correlation_id": r.json()["error"]["correlation_id"]}


def test_revoked_token_401_after_logout(client, make_user, db_conn):
    login(client, email_of(db_conn, make_user()))
    access = client.cookies.get("mem_access")
    assert client.get("/api/me").status_code == 200
    assert post(client, "/api/auth/logout").status_code == 200
    _replace_cookies(client, mem_access=access)                    # replay the old cookie
    assert client.get("/api/me").status_code == 401


def test_alg_none_rejected(client, make_user):
    uid = make_user()
    now = int(datetime.now(UTC).timestamp())
    payload = {"sub": str(uid), "typ": "access", "jti": "x", "iat": now, "exp": now + 600,
               "iss": "maribyrnong-env-monitor", "aud": "maribyrnong-env-monitor-web", "mfa": True}
    forged = f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(payload)}."
    client.cookies.set("mem_access", forged)
    assert client.get("/api/me").status_code == 401


def test_tampered_token_rejected(client, make_user, db_conn):
    victim = make_user(role="admin")
    login(client, email_of(db_conn, make_user()))
    header, payload, signature = client.cookies.get("mem_access").split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
    claims["sub"], claims["mfa"] = str(victim), True               # try to become the admin
    _replace_cookies(client, mem_access=f"{header}.{_b64(claims)}.{signature}")
    assert client.get("/api/me").status_code == 401


def test_token_signed_with_other_secret_rejected(client, make_user):
    access, _ = issue_pair("another-secret-" + "y" * 40, make_user(), mfa=True)
    client.cookies.set("mem_access", access)
    assert client.get("/api/me").status_code == 401


def test_deactivated_user_token_rejected(client, make_user, db_conn):
    uid = make_user()
    login(client, email_of(db_conn, uid))
    db_conn.execute("UPDATE users SET is_active = 0 WHERE user_id = ?", (uid,))
    db_conn.commit()
    r = client.get("/api/me")
    assert r.status_code == 401 and r.json()["error"]["code"] == "account_deactivated"


def test_refresh_rotates_and_reuse_ends_all_sessions(client, make_user, db_conn):
    login(client, email_of(db_conn, make_user()))
    first_refresh = client.cookies.get("mem_refresh")
    assert post(client, "/api/auth/refresh").status_code == 200
    assert client.cookies.get("mem_refresh") != first_refresh       # rotated
    assert client.get("/api/me").status_code == 200
    current_access, csrf = client.cookies.get("mem_access"), client.cookies.get("mem_csrf")
    # An attacker replays the already-used refresh token: treated as theft
    _replace_cookies(client, mem_refresh=first_refresh, mem_csrf=csrf)
    assert post(client, "/api/auth/refresh").status_code == 401
    _replace_cookies(client, mem_access=current_access)
    assert client.get("/api/me").status_code == 401                 # the legitimate session ended too


def test_password_change_ends_other_sessions(make_client, make_user, db_conn):
    from fastapi.testclient import TestClient

    email = email_of(db_conn, make_user())
    laptop = make_client()
    phone = TestClient(laptop.app, base_url="https://testserver")   # same server, second browser
    login(laptop, email)
    login(phone, email)
    r = post(laptop, "/api/auth/change-password",
             {"current_password": "Tram-Lantern-Quartz-58", "new_password": "Harbour-Signal-Pewter-93"})
    assert r.status_code == 200
    assert laptop.get("/api/me").status_code == 200                 # the browser that changed it continues
    assert phone.get("/api/me").status_code == 401                  # every other session has ended


def test_access_token_lifetime_is_30_minutes(client, make_user, db_conn):
    login(client, email_of(db_conn, make_user()))
    _, payload, _ = client.cookies.get("mem_access").split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
    assert abs(claims["exp"] - claims["iat"] - 30 * 60) < 1    # iat has milliseconds, exp whole seconds
    _, payload, _ = client.cookies.get("mem_refresh").split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
    assert abs(claims["exp"] - claims["iat"] - 8 * 3600) < 1
