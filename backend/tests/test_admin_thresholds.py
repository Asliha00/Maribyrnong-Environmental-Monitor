"""Threshold management (§4.5, R24): value change with a required reason, append-only history,
exceedances recomputed with the pipeline's rule; admin + MFA only; audited."""
import pytest

from backend.app.routers.admin_thresholds import RECOMPUTE_SQL
from backend.tests.conftest import admin_with_mfa, audit_actions, email_of, login, put
from backend.tests.test_data_api import _agg, data_db  # noqa: F401 - fixture

URL = "/api/admin/thresholds"
REASON = "Aligning with the updated NEPM guidance for this trial."


@pytest.fixture
def admin(client, make_user, db_conn, data_db):  # noqa: F811
    # daily PM2.5 means for A-01 on 1-7 July are 5.0 (fixture); add two clearly high valid days
    # and one high INVALID day, which must never count as an exceedance
    db_conn.executemany("INSERT INTO aggregates (sensor_id, period, bucket_start_local, season, variable, mean, min, "
                        "max, n, completeness_pct, is_valid, qc_mode) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [_agg(1, "day", "2025-07-08", "pm25", 30.0), _agg(1, "day", "2025-07-09", "pm25", 22.0),
                         _agg(1, "day", "2025-07-10", "pm25", 40.0, comp=50.0)])
    db_conn.commit()
    admin_with_mfa(client, make_user, db_conn)
    return client


def _exceedance_days(db_conn, threshold_id=1):
    return sorted(r[0] for r in db_conn.execute("SELECT date_local FROM exceedances WHERE threshold_id = ?",
                                                (threshold_id,)))


def test_list_shows_thresholds_counts_and_history(admin):
    body = admin.get(URL).json()
    pm = next(t for t in body["thresholds"] if t["threshold_id"] == 1)
    assert pm["statistic"] == "daily mean" and pm["unit"] == "µg/m³" and pm["value"] == 25
    assert pm["exceedance_days"] == 1 and body["history"] == []


def test_lowering_a_threshold_recomputes_and_logs(admin, db_conn):
    r = put(admin, f"{URL}/1", {"value": 20, "reason": REASON})
    assert r.status_code == 200
    assert "2 days now exceed it (was 1)" in r.json()["message"]
    assert _exceedance_days(db_conn) == ["2025-07-08", "2025-07-09"]   # 30 and 22; the invalid 40 never counts
    history = r.json()["history"]
    assert len(history) == 1
    assert history[0]["old_value"] == 25 and history[0]["new_value"] == 20 and history[0]["reason"] == REASON
    assert history[0]["changed_by"].startswith("admin_") and history[0]["changed_at"]
    entry = audit_actions(db_conn, "threshold_updated")[0]
    assert entry["exceedance_days_before"] == 1 and entry["exceedance_days_after"] == 2
    assert entry["reason"] == REASON


def test_raising_a_threshold_removes_exceedances(admin, db_conn):
    put(admin, f"{URL}/1", {"value": 35, "reason": REASON})
    assert _exceedance_days(db_conn) == []
    assert admin.get("/api/exceedances?variable=pm25&start=2025-07-01&end=2025-07-31").json()["total"] == 0


def test_daily_maximum_threshold_uses_the_max(admin, db_conn):
    # threshold 3: temperature daily max >= 35; fixture daily max for A-01 is mean + 1 (12..18)
    put(admin, f"{URL}/3", {"value": 17, "reason": REASON})
    assert _exceedance_days(db_conn, 3) == ["2025-07-06", "2025-07-07"]   # max 17 and 18 (>=)


def test_history_is_cumulative_and_append_only(admin, db_conn):
    put(admin, f"{URL}/1", {"value": 20, "reason": REASON})
    put(admin, f"{URL}/1", {"value": 25, "reason": "Back to the NEPM value after review."})
    history = admin.get(URL).json()["history"]
    assert [(h["old_value"], h["new_value"]) for h in history] == [(20, 25), (25, 20)]   # newest first


@pytest.mark.parametrize("body", [{"value": 20}, {"value": 20, "reason": "too short"},
                                  {"value": -1, "reason": REASON}, {"value": "abc", "reason": REASON},
                                  {"value": 1e9, "reason": REASON}, {"value": 20, "reason": "x\u0000" * 10},
                                  {"value": 20, "reason": REASON, "operator": "<"},
                                  {"value": 20, "reason": REASON, "variable": "co_ppb"}])
def test_invalid_updates_rejected(admin, db_conn, body):
    assert put(admin, f"{URL}/1", body).status_code == 422
    assert db_conn.execute("SELECT value FROM thresholds WHERE threshold_id = 1").fetchone()[0] == 25
    assert db_conn.execute("SELECT COUNT(*) FROM threshold_history").fetchone()[0] == 0


def test_same_value_unknown_id_and_clash(admin, db_conn):
    assert put(admin, f"{URL}/1", {"value": 25, "reason": REASON}).json()["error"]["code"] == "nothing_to_change"
    assert put(admin, f"{URL}/999", {"value": 20, "reason": REASON}).status_code == 404
    db_conn.execute("INSERT INTO thresholds (threshold_id, variable, period, operator, value, label, source) "
                    "VALUES (7, 'pm25', 'day', '>', 50, 'Second PM2.5 level', 'test')")
    db_conn.commit()
    assert put(admin, f"{URL}/1", {"value": 50, "reason": REASON}).status_code == 409


def test_only_admins_with_mfa(client, make_user, db_conn, data_db):  # noqa: F811
    for role in ("analyst", "admin"):
        client.cookies.clear()
        login(client, email_of(db_conn, make_user(role=role)))
        assert client.get(URL).status_code == 403
        assert put(client, f"{URL}/1", {"value": 20, "reason": REASON}).status_code == 403
    assert db_conn.execute("SELECT value FROM thresholds WHERE threshold_id = 1").fetchone()[0] == 25


def test_recompute_sql_has_no_placeholders_for_identifiers():
    """Only values are parameters; the statement text is fixed per (statistic, operator)."""
    assert set(RECOMPUTE_SQL) == {("day", ">"), ("day", ">="), ("day_max", ">"), ("day_max", ">=")}
    for (period, op), sql in RECOMPUTE_SQL.items():
        assert sql.count("?") == 3 and f" {op} ?" in sql
        assert (" mean " in sql) == (period == "day")
