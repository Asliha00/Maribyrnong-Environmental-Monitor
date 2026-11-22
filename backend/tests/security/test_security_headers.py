"""Browser security headers and CORS (SEC-01, SEC-22, SEC-25)."""
import json

from backend.app.config import ROOT

DEV_ORIGIN = "http://localhost:5173"


def _vercel_header(key: str) -> str:
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    for rule in config["headers"]:
        for header in rule["headers"]:
            if header["key"] == key:
                return header["value"]
    raise KeyError(key)


def test_hsts_header(client):
    value = client.get("/api/health").headers["strict-transport-security"]
    assert "max-age=31536000" in value and "includeSubDomains" in value


def test_csp_present(client):
    csp = client.get("/api/health").headers["content-security-policy"]
    assert csp == _vercel_header("Content-Security-Policy"), "local CSP must match vercel.json"
    for directive in ("default-src 'self'", "script-src 'self'", "object-src 'none'", "frame-ancestors 'none'"):
        assert directive in csp


def test_nosniff(client):
    assert client.get("/api/health").headers["x-content-type-options"] == "nosniff"


def test_frame_and_referrer_headers(client):
    headers = client.get("/api/health").headers
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "camera=()" in headers["permissions-policy"]


def test_api_responses_not_cached(client):
    assert client.get("/api/health").headers["cache-control"] == "private, no-store"


def test_headers_also_on_404(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert "content-security-policy" in response.headers


def test_no_cors_headers_in_production(make_client):
    client = make_client(environment="production",
                         app_database_url="postgresql://app_user:Zq8vR3nT6yW1bX4m@ep-x-pooler.ap-southeast-2.aws.neon.tech/db?sslmode=require")
    response = client.get("/api/openapi.json", headers={"Origin": DEV_ORIGIN})
    assert "access-control-allow-origin" not in response.headers
    preflight = client.options("/api/health", headers={"Origin": DEV_ORIGIN, "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in preflight.headers


def test_allowed_origin_gets_cors_in_development(make_client):
    client = make_client(environment="development", allowed_origins=DEV_ORIGIN)
    response = client.get("/api/health", headers={"Origin": DEV_ORIGIN})
    assert response.headers["access-control-allow-origin"] == DEV_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"


def test_disallowed_origin_no_cors_headers(make_client):
    client = make_client(environment="development", allowed_origins=DEV_ORIGIN)
    response = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers
