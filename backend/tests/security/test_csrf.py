"""SEC-09 browser token storage and CSRF."""
from backend.tests.conftest import STRONG_PASSWORD, email_of, login


def _set_cookie_headers(response) -> dict[str, str]:
    return {h.split("=", 1)[0]: h for h in response.headers.get_list("set-cookie")}


def test_login_sets_httponly_secure_cookie(client, make_user, db_conn):
    r = login(client, email_of(db_conn, make_user()))
    cookies = _set_cookie_headers(r)
    for name in ("mem_access", "mem_refresh"):
        header = cookies[name].lower()
        assert "httponly" in header and "secure" in header and "samesite=strict" in header
    assert "path=/api/auth" in cookies["mem_refresh"].lower(), "refresh token only goes to the auth endpoints"
    csrf = cookies["mem_csrf"].lower()
    assert "secure" in csrf and "samesite=strict" in csrf and "httponly" not in csrf   # page JS must read it


def test_tokens_never_in_response_body(client, make_user, db_conn):
    r = login(client, email_of(db_conn, make_user()))
    body = r.text
    assert client.cookies.get("mem_access") not in body and client.cookies.get("mem_refresh") not in body


def test_post_without_csrf_header_403(client, make_user, db_conn):
    login(client, email_of(db_conn, make_user()))
    body = {"current_password": STRONG_PASSWORD, "new_password": "Harbour-Signal-Pewter-93"}
    no_header = client.post("/api/auth/change-password", json=body)
    assert no_header.status_code == 403 and no_header.json()["error"]["code"] == "csrf_failed"
    wrong = client.post("/api/auth/change-password", json=body, headers={"X-CSRF-Token": "forged"})
    assert wrong.status_code == 403
    right = client.post("/api/auth/change-password", json=body,
                        headers={"X-CSRF-Token": client.cookies.get("mem_csrf")})
    assert right.status_code == 200


def test_logout_requires_csrf(client, make_user, db_conn):
    login(client, email_of(db_conn, make_user()))
    assert client.post("/api/auth/logout").status_code == 403      # a cross-site form cannot log you out
    assert client.get("/api/me").status_code == 200


def test_development_cookies_not_secure(make_client, make_user, db_conn):
    """Local http://localhost would drop Secure cookies; only development relaxes it."""
    client = make_client(environment="development")
    r = login(client, email_of(db_conn, make_user()))
    assert "secure" not in _set_cookie_headers(r)["mem_access"].lower()
