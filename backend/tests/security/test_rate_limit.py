"""SEC-23 database-backed rate limiting (shared by every app instance)."""
from fastapi.testclient import TestClient

from backend.app.main import create_app


def _attempt(client):
    return client.post("/api/auth/login", json={"email": "nobody@example.org", "password": "whatever-123"})


def test_login_429_after_limit(client):
    codes = [_attempt(client).status_code for _ in range(6)]
    assert codes == [401] * 5 + [429]
    r = _attempt(client)
    assert r.json()["error"]["code"] == "rate_limited" and int(r.headers["Retry-After"]) > 0


def test_limit_shared_across_two_app_instances(make_settings):
    settings = make_settings()   # both instances use the same database, like two Vercel instances
    first = TestClient(create_app(settings), base_url="https://testserver")
    second = TestClient(create_app(settings), base_url="https://testserver")
    codes = [_attempt(first).status_code for _ in range(3)] + [_attempt(second).status_code for _ in range(3)]
    assert codes == [401, 401, 401, 401, 401, 429]


def test_limit_is_per_ip(make_settings):
    app = create_app(make_settings())
    a = TestClient(app, base_url="https://testserver", client=("203.0.113.1", 5000))
    b = TestClient(app, base_url="https://testserver", client=("203.0.113.2", 5000))
    for _ in range(5):
        _attempt(a)
    assert _attempt(a).status_code == 429
    assert _attempt(b).status_code == 401      # another caller is unaffected


def test_forged_forwarded_header_ignored_outside_vercel(client):
    """A client cannot dodge the limit by sending its own X-Forwarded-For / X-Real-IP."""
    codes = [client.post("/api/auth/login", json={"email": "nobody@example.org", "password": "x" * 12},
                         headers={"X-Real-IP": f"198.51.100.{i}", "X-Forwarded-For": f"198.51.100.{i}"}).status_code
             for i in range(6)]
    assert codes[-1] == 429
