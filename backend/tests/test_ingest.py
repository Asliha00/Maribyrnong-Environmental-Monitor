"""UC4 live ingestion behaviour: storage, incremental aggregates, logging, exceedances."""
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from backend.app.db import Database
from backend.app.services import live
from backend.tests.security.test_ingest_security import KEY, device, now_iso, send  # noqa: F401 - fixture
from backend.tests.test_data_api import data_db  # noqa: F401 - fixture

LOCAL = ZoneInfo("Australia/Melbourne")


def _buckets(ts_iso: str) -> dict[str, str]:
    local = datetime.fromisoformat(ts_iso.replace("Z", "+00:00")).astimezone(LOCAL)
    return {"hour": local.strftime("%Y-%m-%d %H:00"), "day": local.strftime("%Y-%m-%d"),
            "month": local.strftime("%Y-%m")}


def _agg(db_conn, period, bucket, variable, qc="all", sensor_id=1):
    row = db_conn.execute("SELECT mean, n FROM aggregates WHERE sensor_id = ? AND period = ? "
                          "AND bucket_start_local = ? AND variable = ? AND qc_mode = ?",
                          (sensor_id, period, bucket, variable, qc)).fetchone()
    return None if row is None else tuple(row)


def test_reading_is_stored_and_its_buckets_updated(device, db_conn):  # noqa: F811
    t1 = datetime.now(UTC) - timedelta(seconds=20)
    r1 = send(device, {"timestamp": t1.isoformat(), "temperature": 20.0, "pm25": 4.0})
    assert r1.status_code == 200 and r1.json()["status"] == "stored"
    b = _buckets(r1.json()["ts_utc"])
    assert r1.json()["buckets"] == b
    assert _agg(db_conn, "hour", b["hour"], "temperature_c") == (20.0, 1)
    r2 = send(device, {"timestamp": (t1 + timedelta(seconds=10)).isoformat(), "temperature": 22.0, "pm25": 6.0})
    assert r2.status_code == 200
    for period in ("hour", "day", "month"):
        mean, n = _agg(db_conn, period, b[period], "temperature_c")
        assert n >= 2 and (period != "hour" or mean == 21.0)
    last = db_conn.execute("SELECT last_reading_utc FROM sensors WHERE sensor_id = 1").fetchone()[0]
    assert last == r2.json()["ts_utc"]


def test_out_of_range_value_logged_rest_stored(device, db_conn):  # noqa: F811
    r = send(device, {"timestamp": now_iso(), "temperature": 95.0, "pm25": 5.0})
    assert r.status_code == 200 and r.json()["rejected"] == ["temperature_c"]
    row = db_conn.execute("SELECT temperature_c, pm25 FROM readings WHERE ts_utc = ?", (r.json()["ts_utc"],)).fetchone()
    assert tuple(row) == (None, 5.0)
    err = db_conn.execute("SELECT error_type, variable, raw_value FROM error_log WHERE error_type = 'out_of_range'") \
        .fetchone()
    assert tuple(err) == ("out_of_range", "temperature_c", "95.0")


def test_spike_is_flagged_and_left_out_of_the_clean_variant(device, db_conn):  # noqa: F811
    start = datetime.now(UTC) - timedelta(seconds=60)
    for i in range(6):
        send(device, {"timestamp": (start + timedelta(seconds=i)).isoformat(), "pm25": 5.0})
    r = send(device, {"timestamp": (start + timedelta(seconds=6)).isoformat(), "pm25": 400.0})
    assert r.json()["flags"] == ["pm25_spike"]
    hour = r.json()["buckets"]["hour"]
    all_mean, all_n = _agg(db_conn, "hour", hour, "pm25")
    clean = _agg(db_conn, "hour", hour, "pm25", qc="clean")
    assert all_n == 7 and all_mean > 50
    assert clean == (5.0, 6)                                            # the spike is excluded only here


def test_new_sensor_registers_its_variables_on_first_reading(device, db_conn):  # noqa: F811
    db_conn.execute("INSERT INTO sensors (sensor_id, sensor_code, sensor_name, device_family, land_use, latitude, "
                    "longitude, auth_key_hash) VALUES (9, 'SIM-01', 'Simulator', 'libelium', 'Parkland', -37.8, "
                    "144.9, ?)", (live.key_hash(KEY),))
    db_conn.commit()
    r = send(device, {"timestamp": now_iso(), "temperature": 18.0, "pressure": 101300, "humidity": 70},
             device_id="SIM-01")
    assert r.status_code == 200
    got = {tuple(x) for x in db_conn.execute("SELECT variable, unit, raw_column FROM sensor_variables "
                                            "WHERE sensor_id = 9")}
    assert got == {("temperature_c", "°C", "temperature"), ("pressure_hpa", "hPa", "pressure"),
                   ("humidity_pct", "%", "humidity")}
    assert _agg(db_conn, "hour", r.json()["buckets"]["hour"], "pressure_hpa", sensor_id=9) == (1013.0, 1)
    assert device.get("/api/sensors").status_code == 401   # the device key is not a user session


def test_unknown_field_for_the_device_type(device):  # noqa: F811
    r = send(device, {"timestamp": now_iso(), "temperature": 20, "pressure": 1013})   # MCC units have no pressure
    assert r.status_code == 422 and "pressure" in r.json()["error"]["message"]


def test_readings_per_device_are_rate_limited(device, monkeypatch):  # noqa: F811
    from backend.app.routers import ingest as ingest_router

    monkeypatch.setattr(ingest_router, "READINGS_PER_DEVICE", ingest_router.rate_limit.Limit("ingest:device", 2, 60))
    t = datetime.now(UTC)
    codes = [send(device, {"timestamp": (t - timedelta(seconds=i)).isoformat(), "temperature": 20}).status_code
             for i in range(3)]
    assert codes == [200, 200, 429]


def test_exceedances_follow_the_daily_aggregate(make_settings, db_conn, data_db):  # noqa: F811
    """A valid day over the PM2.5 standard becomes an exceedance; an invalid one never does."""
    db = Database(make_settings())
    db_conn.execute("INSERT INTO aggregates (sensor_id, period, bucket_start_local, season, variable, mean, min, max, "
                    "n, completeness_pct, is_valid, qc_mode) VALUES (1, 'day', '2025-07-20', 'Winter', 'pm25', "
                    "31.0, 10, 80, 140, 97.0, 1, 'all')")
    db_conn.execute("INSERT INTO aggregates (sensor_id, period, bucket_start_local, season, variable, mean, min, max, "
                    "n, completeness_pct, is_valid, qc_mode) VALUES (1, 'day', '2025-07-21', 'Winter', 'pm25', "
                    "40.0, 10, 80, 40, 30.0, 0, 'all')")
    db_conn.commit()
    with db.transaction() as tx:
        assert live.update_exceedances(tx, 1, "2025-07-20") == 1
        assert live.update_exceedances(tx, 1, "2025-07-21") == 0
    rows = [tuple(r) for r in db_conn.execute("SELECT threshold_id, date_local, observed_value FROM exceedances "
                                             "WHERE sensor_id = 1 AND date_local LIKE '2025-07-2%'")]
    assert rows == [(1, "2025-07-20", 31.0)]
    db.close()
