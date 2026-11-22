"""Data-quality page API (§4.5): completeness calendar, error_log browser, ingestion runs,
flag counts (analyst + admin), suspicious-login entries (admin only, SEC-27)."""
import json

import pytest

from backend.tests.conftest import admin_with_mfa, email_of, login
from backend.tests.test_data_api import data_db  # noqa: F401 - fixture


@pytest.fixture
def quality_db(db_conn, data_db):  # noqa: F811
    c = db_conn
    c.execute("INSERT INTO ingestion_runs (run_id, source_file, file_sha256, sensor_id, rows_read, rows_inserted, "
              "rows_duplicate, values_rejected, values_flagged, storage_path, started_at, finished_at) VALUES "
              "(1, 'alpha.csv', 'abcdef0123456789', 1, 100, 98, 2, 3, 1, 'raw/abc__alpha.csv', "
              "'2026-10-27T01:00:00Z', '2026-10-27T01:01:00Z')")
    c.execute("INSERT INTO ingestion_runs (run_id, source_file, file_sha256, sensor_id, started_at) VALUES "
              "(2, 'broken.csv', 'ffff', 2, '2026-10-28T01:00:00Z')")   # never finished
    c.executemany("INSERT INTO error_log (sensor_id, ts_utc, error_type, variable, raw_value, description, "
                  "ingestion_run_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  [(1, "2025-07-01T03:00:00Z", "out_of_range", "pm25", "9999", "PM2.5 above 1000", 1),
                   (1, "2025-07-02T03:00:00Z", "out_of_range", "temperature_c", "-80", "below -20", 1),
                   (2, "2025-07-03T03:00:00Z", "not_fitted", "co2_ppm", "0", "always zero", 1),
                   (None, None, "unknown_sensor", None, "mystery.csv", "no matching sensor", None)])
    c.execute("INSERT INTO readings (sensor_id, ts_utc, ts_local, pm25, qc_flags) VALUES "
              "(1, '2025-07-02T02:00:00Z', '2025-07-02T12:00:00+1000', 400, 'pm25_spike;temperature_flatline')")
    c.commit()
    return c


@pytest.fixture
def analyst(client, make_user, db_conn, quality_db):
    login(client, email_of(db_conn, make_user(role="analyst")))
    return client


def test_completeness_calendar_shows_every_day(analyst):
    r = analyst.get("/api/quality/completeness", params={"variable": "temperature_c", "start": "2025-06-30",
                                                        "end": "2025-07-07"})
    assert r.status_code == 200
    body = r.json()
    a, b = body["sensors"]
    assert a["sensor_code"] == "A-01" and len(a["cells"]) == 8
    assert a["cells"][0] == {"date": "2025-06-30", "pct": 0.0, "valid": False}     # gap shown, not hidden
    assert a["cells"][1] == {"date": "2025-07-01", "pct": 100.0, "valid": True}
    assert a["valid_days"] == 7 and b["valid_days"] == 0                          # Bravo is 50% every day
    assert {c["pct"] for c in b["cells"][1:]} == {50.0}


def test_completeness_only_lists_sensors_measuring_the_variable(analyst):
    body = analyst.get("/api/quality/completeness", params={"variable": "co_ppb", "start": "2025-07-01",
                                                           "end": "2025-07-07"}).json()
    assert [s["sensor_code"] for s in body["sensors"]] == ["A-01"]


def test_completeness_range_checks(analyst):
    assert analyst.get("/api/quality/completeness", params={"variable": "pm25", "start": "2025-07-07",
                                                           "end": "2025-07-01"}).status_code == 400
    assert analyst.get("/api/quality/completeness", params={"variable": "pm25", "start": "2024-01-01",
                                                           "end": "2025-07-01"}).status_code == 400


def test_errors_browser_filters_and_pages(analyst):
    body = analyst.get("/api/quality/errors").json()
    assert body["total"] == 4 and body["by_type"] == {"out_of_range": 2, "not_fitted": 1, "unknown_sensor": 1}
    assert body["items"][0]["error_type"] == "unknown_sensor"                        # newest first
    assert analyst.get("/api/quality/errors", params={"sensor_id": 1}).json()["total"] == 2
    assert analyst.get("/api/quality/errors", params={"error_type": "not_fitted"}).json()["items"][0]["variable"] \
        == "co2_ppm"
    assert analyst.get("/api/quality/errors", params={"variable": "pm25"}).json()["total"] == 1
    dated = analyst.get("/api/quality/errors", params={"start": "2025-07-02", "end": "2025-07-02"}).json()
    assert [i["variable"] for i in dated["items"]] == ["temperature_c"]
    page = analyst.get("/api/quality/errors", params={"limit": 1, "offset": 1}).json()
    assert page["total"] == 4 and len(page["items"]) == 1 and page["items"][0]["error_type"] == "not_fitted"


@pytest.mark.parametrize("params", [{"sensor_id": "1 OR 1=1"}, {"error_type": "x'; DROP TABLE error_log--"},
                                    {"variable": "pm25' OR '1'='1"}, {"limit": 1000}, {"start": "yesterday"}])
def test_errors_reject_hostile_filters(analyst, db_conn, params):
    assert analyst.get("/api/quality/errors", params=params).status_code == 422
    assert db_conn.execute("SELECT COUNT(*) FROM error_log").fetchone()[0] == 4


def test_runs_history(analyst):
    items = analyst.get("/api/quality/runs").json()["items"]
    assert [i["run_id"] for i in items] == [2, 1]
    assert items[0]["completed"] is False and items[1]["completed"] is True
    assert items[1]["rows_inserted"] == 98 and items[1]["archived"] is True
    assert items[1]["storage_path"] is None and items[1]["file_sha256"] == "abcdef012345"   # no blob path exposed


def test_flag_counts_split_combined_flags(analyst):
    body = analyst.get("/api/quality/flags").json()
    got = {(i["sensor_code"], i["flag"]): i["readings"] for i in body["items"]}
    assert got == {("A-01", "pm25_spike"): 2, ("A-01", "temperature_flatline"): 1, ("B-02", "humidity_saturated"): 1}
    assert body["total"] == 4
    saturated = next(i for i in body["items"] if i["flag"] == "humidity_saturated")
    assert saturated["description"] == "Humidity saturated at 100% (kept, flagged)"


def test_roles_without_view_quality_cannot_see_it(client, make_user, db_conn, quality_db):
    """The retired General User role (D-035) never held view_quality; its old records still cannot."""
    login(client, email_of(db_conn, make_user(role="legacy_user")))
    for url in ("/api/quality/errors", "/api/quality/runs", "/api/quality/flags",
                "/api/quality/completeness?variable=pm25&start=2025-07-01&end=2025-07-02"):
        assert client.get(url).status_code == 403


def test_security_events_are_admin_only(client, make_user, db_conn, quality_db):
    db_conn.execute("INSERT INTO audit_log (action, ip_address, detail_json) VALUES "
                    "('suspicious_login_activity', '203.0.113.9', ?)",
                    (json.dumps({"failed_logins_last_10_min": 21, "threshold": 20}),))
    db_conn.commit()
    login(client, email_of(db_conn, make_user(role="analyst")))
    assert client.get("/api/quality/security").status_code == 403
    client.cookies.clear()
    admin_with_mfa(client, make_user, db_conn)
    items = client.get("/api/quality/security").json()["items"]
    assert items[0]["failed_logins_last_10_min"] == 21 and items[0]["ip_address"] == "203.0.113.9"
