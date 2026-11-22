"""Safe error handling (SEC-24): no stack traces, SQL or paths reach the client."""
import pytest
from fastapi import Query
from fastapi.testclient import TestClient

from backend.app.main import create_app

SECRET_DETAIL = "SELECT * FROM app.users WHERE password_hash = 'x' -- D:\\secret\\path.py"


@pytest.fixture
def failing_client(make_settings):
    app = create_app(make_settings())

    @app.get("/api/_boom")
    def boom():
        raise RuntimeError(SECRET_DETAIL)

    @app.get("/api/_typed")
    def typed(n: int = Query(...)):
        return {"n": n}

    return TestClient(app)


def test_500_has_no_stacktrace(failing_client):
    response = failing_client.get("/api/_boom")
    assert response.status_code == 500
    text = response.text
    for leak in ("Traceback", "RuntimeError", "SELECT", "password_hash", ".py"):
        assert leak not in text
    assert response.json()["error"]["code"] == "internal_error"


def test_error_includes_correlation_id(failing_client, caplog):
    response = failing_client.get("/api/_boom")
    correlation_id = response.json()["error"]["correlation_id"]
    assert correlation_id and response.headers["x-request-id"] == correlation_id
    # The full detail is in the server log, findable by the same ID
    assert any(correlation_id in r.getMessage() for r in caplog.records)


def test_500_still_has_security_headers(failing_client):
    assert "content-security-policy" in failing_client.get("/api/_boom").headers


def test_404_uses_standard_body(client):
    body = client.get("/api/nope").json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "http_404"
    assert body["error"]["message"] == "The requested resource was not found."


def test_validation_error_does_not_echo_input(failing_client):
    payload = "<script>alert(1)</script>"
    response = failing_client.get("/api/_typed", params={"n": payload})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert payload not in response.text
