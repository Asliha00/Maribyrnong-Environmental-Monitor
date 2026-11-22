"""GET /api/health: public uptime check."""


def test_health_ok_with_database(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_reports_missing_database(make_client, tmp_path):
    client = make_client(sqlite_path=tmp_path / "does-not-exist.db")
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["database"] == "unavailable"
    assert not (tmp_path / "does-not-exist.db").exists(), "health check must not create a database file"
