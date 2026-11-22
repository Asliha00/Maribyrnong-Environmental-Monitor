"""Insights API: permissions, ranges, and that findings come from the data (never fixed text)."""
import pytest

from backend.app.services import analysis
from backend.tests.conftest import email_of, login, put

ENDPOINTS = ["summary", "trends", "diurnal", "green-infrastructure", "disparities", "recommendations"]
SENSORS = [(1, "PK-1", "Park One", "Parkland", 0), (2, "RD-1", "Road One", "Transport corridor", 0),
           (3, "CC-1", "Childcare One", "Residential", 1)]


def world(db_conn, park_offset: float, days: int = 60) -> None:
    """Three sensors, `days` days of valid hourly + daily temperature and PM2.5 from 2025-12-01.
    The park reads `park_offset` °C relative to the road; the childcare site is 0.5 °C warmer than
    the road. Every fifth day is hot (max 36 °C)."""
    c = db_conn
    c.executemany("INSERT INTO sensors (sensor_id, sensor_code, sensor_name, device_family, land_use, "
                  "location_verified, latitude, longitude, sensitive_receptor) VALUES (?, ?, ?, 'mcc_aq', ?, 1, "
                  "-37.8, 144.9, ?)", SENSORS)
    c.executemany("INSERT INTO sensor_variables (sensor_id, variable, unit, raw_column) VALUES (?, ?, ?, ?)",
                  [(s[0], v, u, v) for s in SENSORS for v, u in (("temperature_c", "°C"), ("pm25", "µg/m³"))])
    c.execute("INSERT INTO thresholds (threshold_id, variable, period, operator, value, label, source) "
              "VALUES (3, 'temperature_c', 'day_max', '>=', 35, 'Hot day', 'test')")
    c.execute("INSERT INTO thresholds (threshold_id, variable, period, operator, value, label, source) "
              "VALUES (1, 'pm25', 'day', '>', 25, 'PM2.5 24-hour standard', 'NEPM')")
    rows = []
    from datetime import date, timedelta
    for i in range(days):
        d = (date(2025, 12, 1) + timedelta(days=i)).isoformat()
        base = 22 + (i % 7)
        hot = i % 5 == 0
        for sid, offset, pm in ((1, park_offset, 4.0), (2, 0.0, 9.0), (3, 0.5, 6.0)):
            mx = (36.0 if hot else 30.0) + offset
            rows.append((sid, "day", d, "Summer", "temperature_c", base + offset, base - 5, mx, 144, 100.0, 1, "all"))
            rows.append((sid, "day", d, "Summer", "pm25", pm, 1, pm + 3, 144, 100.0, 1, "all"))
            for h in range(24):
                rows.append((sid, "hour", f"{d} {h:02d}:00", "Summer", "temperature_c", base + offset, base, base,
                             6, 100.0, 1, "all"))
                rows.append((sid, "hour", f"{d} {h:02d}:00", "Summer", "pm25", pm, pm, pm, 6, 100.0, 1, "all"))
    for sid in (1, 2, 3):
        for m in ("2025-12", "2026-01"):
            rows.append((sid, "month", m, "Summer", "temperature_c", 25.0, 15, 36, 4000, 100.0, 1, "all"))
    c.executemany("INSERT INTO aggregates (sensor_id, period, bucket_start_local, season, variable, mean, min, max, "
                  "n, completeness_pct, is_valid, qc_mode) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    c.commit()
    analysis._cache.clear()


@pytest.fixture
def user(client, make_user, db_conn):
    login(client, email_of(db_conn, make_user(role="analyst")))
    return client


def test_every_endpoint_answers_for_a_signed_in_user(user, db_conn):
    world(db_conn, park_offset=-1.5)
    for name in ENDPOINTS:
        r = user.get(f"/api/analysis/{name}")
        assert r.status_code == 200, (name, r.text[:200])
        assert r.json()["start"] == "2025-12-01" and r.json()["end"] == "2026-01-29"


def test_anonymous_is_refused(client, db_conn):
    world(db_conn, park_offset=-1.5)
    for name in ENDPOINTS:
        assert client.get(f"/api/analysis/{name}").status_code == 401


def test_findings_come_from_the_data_not_from_text(user, db_conn, make_settings):
    """Same page, two worlds: parks 1.5 °C cooler, then 1.5 °C warmer. The numbers and the
    recommendations must follow the data."""
    world(db_conn, park_offset=-1.5)
    cool = user.get("/api/analysis/green-infrastructure").json()
    cool_recs = {r["id"]: r for r in user.get("/api/analysis/recommendations").json()["recommendations"]}
    assert cool["all_hours"]["difference_c"] == pytest.approx(-1.75) and cool["all_hours"]["direction"] == "falling"
    assert cool["hot_afternoons"]["days"] == 12 and cool["hot_afternoons"]["hours"] == 12 * 6
    assert "canopy" in cool_recs and "1.8 °C cooler" in cool_recs["canopy"]["text"]

    db_conn.execute("UPDATE aggregates SET mean = mean + 3.0 WHERE sensor_id = 1 AND variable = 'temperature_c'")
    db_conn.execute("UPDATE aggregates SET max = max + 3.0 WHERE sensor_id = 1 AND variable = 'temperature_c'")
    db_conn.execute("UPDATE sensors SET last_reading_utc = '2026-02-01T00:00:00Z' WHERE sensor_id = 1")  # new data
    db_conn.commit()
    warm = user.get("/api/analysis/green-infrastructure").json()
    warm_recs = {r["id"]: r for r in user.get("/api/analysis/recommendations").json()["recommendations"]}
    assert warm["all_hours"]["difference_c"] == pytest.approx(1.25) and warm["all_hours"]["direction"] == "rising"
    assert "canopy" not in warm_recs and "canopy-evidence" in warm_recs


def test_disparities_and_the_sensitive_site(user, db_conn):
    world(db_conn, park_offset=-1.5)
    body = user.get("/api/analysis/disparities").json()
    assert body["rankings"]["temperature"] == ["CC-1", "RD-1", "PK-1"]
    assert body["rankings"]["pm25"] == ["RD-1", "CC-1", "PK-1"]
    cc = body["equity"][0]
    assert cc["sensor_code"] == "CC-1" and cc["more_exposed"] == ["temperature"]
    assert cc["comparison"]["temperature"]["difference"] == pytest.approx(0.5 - (-1.5 + 0) / 2)
    summary = user.get("/api/analysis/summary").json()
    assert summary["warmest_site"]["sensor_code"] == "CC-1" and summary["hot_days"] == 12


def test_threshold_edit_changes_hot_afternoons(client, make_user, db_conn):
    """Admin edits flow through: raising the hot-day threshold removes every hot day."""
    from backend.tests.conftest import admin_with_mfa

    world(db_conn, park_offset=-1.5)
    admin_with_mfa(client, make_user, db_conn)
    assert client.get("/api/analysis/green-infrastructure").json()["hot_days"] == 12
    r = put(client, "/api/admin/thresholds/3", {"value": 40, "reason": "Testing that insights follow edits."})
    assert r.status_code == 200
    assert client.get("/api/analysis/green-infrastructure").json()["hot_days"] == 0


def test_range_validation(user, db_conn):
    world(db_conn, park_offset=-1.5)
    assert user.get("/api/analysis/summary", params={"start": "2026-01-10", "end": "2026-01-01"}).status_code == 400
    assert user.get("/api/analysis/summary", params={"start": "2020-01-01", "end": "2026-01-01"}).status_code == 400
    r = user.get("/api/analysis/summary", params={"start": "2025-12-01", "end": "2025-12-10"})
    assert r.status_code == 200 and r.json()["days"] == 10


def test_empty_database_says_no_data(user):
    assert user.get("/api/analysis/summary").status_code == 404
