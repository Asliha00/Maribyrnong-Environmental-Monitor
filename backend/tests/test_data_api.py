"""Data API (UC2): meta, sensors, readings at every resolution, exceedances."""
import json

import pytest

from backend.tests.conftest import email_of, login

# Two sensors: A (MCC-style, Transport corridor) measures temperature + pm25 + co;
# B (Libelium, Parkland, unverified location) measures temperature + pm25 + humidity.
SENSORS = [
    (1, "A-01", "Alpha", "mcc_aq", "Transport corridor", 1),
    (2, "B-02", "Bravo", "libelium", "Parkland", 0),
]
VARS = [(1, "temperature_c", "°C"), (1, "pm25", "µg/m³"), (1, "co_ppb", "ppb"), (1, "aqi", "index"),
        (2, "temperature_c", "°C"), (2, "pm25", "µg/m³"), (2, "humidity_pct", "%")]


def _agg(sensor, period, bucket, variable, mean, n=96, comp=100.0, qc="all", season="Winter"):
    valid = 1 if comp >= 75 else 0
    return (sensor, period, bucket, season, variable, mean, None if mean is None else mean - 1,
            None if mean is None else mean + 1, n, comp, valid, qc)


@pytest.fixture
def data_db(db_conn):
    c = db_conn
    c.executemany("INSERT INTO sensors (sensor_id, sensor_code, sensor_name, device_family, land_use, "
                  "location_verified, latitude, longitude) VALUES (?, ?, ?, ?, ?, ?, -37.8, 144.9)", SENSORS)
    c.executemany("INSERT INTO sensor_variables (sensor_id, variable, unit, raw_column) VALUES (?, ?, ?, ?)",
                  [(s, v, u, v) for s, v, u in VARS])
    rows = []
    for day in range(1, 8):   # 1-7 July 2025
        d = f"2025-07-{day:02d}"
        rows += [_agg(1, "day", d, "temperature_c", 10.0 + day),
                 _agg(2, "day", d, "temperature_c", 8.0 + day, comp=50.0),
                 _agg(1, "day", d, "pm25", 5.0), _agg(2, "day", d, "pm25", 6.0)]
    rows += [_agg(1, "day", "2025-07-03", "pm25", 4.0, n=95, qc="clean"),          # a spike removed
             _agg(1, "day", "2025-07-04", "pm25", None, n=0, comp=0.0, qc="clean"),  # every value flagged
             _agg(1, "month", "2025-07", "temperature_c", 14.0, n=4000, comp=90.0),
             _agg(1, "month", "2025-08", "temperature_c", 15.0, n=4000, comp=90.0),
             _agg(1, "hour", "2025-07-01 13:00", "temperature_c", 12.5, n=6)]
    c.executemany("INSERT INTO aggregates (sensor_id, period, bucket_start_local, season, variable, mean, min, max, "
                  "n, completeness_pct, is_valid, qc_mode) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    # raw readings on 2025-07-01 (local, UTC+10): one normal, one flagged spike
    c.executemany("INSERT INTO readings (sensor_id, ts_utc, ts_local, temperature_c, pm25, qc_flags) "
                  "VALUES (?, ?, ?, ?, ?, ?)",
                  [(1, "2025-07-01T02:00:00Z", "2025-07-01T12:00:00+1000", 12.0, 5.0, None),
                   (1, "2025-07-01T02:10:00Z", "2025-07-01T12:10:00+1000", 12.1, 300.0, "pm25_spike"),
                   (2, "2025-07-01T02:00:00Z", "2025-07-01T12:00:00+1000", 9.0, 6.0, "humidity_saturated")])
    c.execute("INSERT INTO thresholds (threshold_id, variable, period, operator, value, label, source) "
              "VALUES (1, 'pm25', 'day', '>', 25, 'PM2.5 24-hour standard', 'NEPM')")
    c.execute("INSERT INTO thresholds (threshold_id, variable, period, operator, value, label, source) "
              "VALUES (3, 'temperature_c', 'day_max', '>=', 35, 'Hot day', 'test')")
    c.executemany("INSERT INTO exceedances (sensor_id, threshold_id, date_local, observed_value, completeness_pct) "
                  "VALUES (?, ?, ?, ?, ?)",
                  [(1, 1, "2025-12-01", 30.0, 100.0), (2, 3, "2026-01-10", 41.0, 90.0),
                   (1, 3, "2026-01-10", 38.0, 99.0)])
    c.commit()
    return c


@pytest.fixture
def analyst(client, make_user, db_conn, data_db):
    login(client, email_of(db_conn, make_user(role="analyst")))
    return client


def _get(client, url, **params):
    r = client.get(url, params=params)
    return r.status_code, r.json()


# ---------- meta and sensors ----------
def test_meta_lists_only_measured_dashboard_variables(analyst):
    _, body = _get(analyst, "/api/meta")
    keys = [v["variable"] for v in body["variables"]]
    assert keys == ["temperature_c", "humidity_pct", "pm25", "co_ppb"]     # aqi is a diagnostic, not shown
    assert body["data_range"] == {"first_day": "2025-07-01", "last_day": "2025-07-07"}
    assert {v["variable"]: v["unit"] for v in body["variables"]}["pm25"] == "µg/m³"


def test_sensors_never_show_unmeasured_variables(analyst):
    _, body = _get(analyst, "/api/sensors")
    by_code = {s["sensor_code"]: s for s in body["sensors"]}
    assert [v["variable"] for v in by_code["A-01"]["variables"]] == ["temperature_c", "pm25", "co_ppb"]
    assert "co_ppb" not in [v["variable"] for v in by_code["B-02"]["variables"]]
    assert "co_ppb" not in by_code["B-02"]["latest"]["values"]


def test_sensor_quality_notes_and_location_flag(analyst):
    _, body = _get(analyst, "/api/sensors")
    b = next(s for s in body["sensors"] if s["sensor_code"] == "B-02")
    assert b["location_verified"] is False
    assert any("not yet been verified" in n for n in b["quality_notes"])
    assert any("Humidity from the Libelium sensors" in n for n in b["quality_notes"])
    a = next(s for s in body["sensors"] if s["sensor_code"] == "A-01")
    assert a["quality_notes"] == []


def test_sensor_detail_and_not_found(analyst):
    status, body = _get(analyst, "/api/sensors/1")
    assert status == 200 and body["latest"]["ts_local"] == "2025-07-01T12:10:00+1000"
    assert body["completeness"]["temperature_c"]["days_with_data"] == 7
    status, body = _get(analyst, "/api/sensors/99")
    assert status == 404 and body["error"]["message"] == "Sensor not found."


# ---------- readings ----------
def test_daily_series_and_summary(analyst):
    status, body = _get(analyst, "/api/readings", variable="temperature_c", start="2025-07-01", end="2025-07-07")
    assert status == 200 and [s["sensor_code"] for s in body["series"]] == ["A-01", "B-02"]
    a = body["series"][0]
    assert [p["t"] for p in a["points"]][:2] == ["2025-07-01", "2025-07-02"]
    assert a["summary"]["mean"] == 14.0 and a["summary"]["min"] == 10.0
    b = body["series"][1]
    assert all(p["valid"] is False for p in b["points"])                   # 50% completeness: greyed out


def test_exclude_flagged_uses_clean_rows(analyst):
    _, clean = _get(analyst, "/api/readings", variable="pm25", start="2025-07-03", end="2025-07-04")
    pts = {p["t"]: p for p in clean["series"][0]["points"]}
    assert pts["2025-07-03"]["mean"] == 4.0 and pts["2025-07-03"]["n"] == 95   # clean row replaces 'all'
    assert pts["2025-07-04"]["mean"] is None and pts["2025-07-04"]["valid"] is False
    assert any("Flagged readings" in n for n in clean["notes"])
    _, everything = _get(analyst, "/api/readings", variable="pm25", start="2025-07-03", end="2025-07-04",
                         exclude_flagged="false")
    pts = {p["t"]: p for p in everything["series"][0]["points"]}
    assert pts["2025-07-03"]["mean"] == 5.0 and pts["2025-07-04"]["mean"] == 5.0


def test_monthly_and_hourly(analyst):
    _, month = _get(analyst, "/api/readings", variable="temperature_c", start="2025-07-15", end="2025-08-10",
                    resolution="month")
    assert [p["t"] for p in month["series"][0]["points"]] == ["2025-07", "2025-08"]
    _, hour = _get(analyst, "/api/readings", variable="temperature_c", start="2025-07-01", end="2025-07-01",
                   resolution="hour")
    assert hour["series"][0]["points"][0]["t"] == "2025-07-01 13:00"


def test_season_is_weighted_and_counts_missing_days(analyst):
    _, body = _get(analyst, "/api/readings", variable="temperature_c", start="2025-07-01", end="2025-07-14",
                   resolution="season")
    point = body["series"][0]["points"][0]
    assert point["t"] == "Winter 2025"
    assert point["mean"] == 14.0                       # n-weighted mean of the 7 days with data
    assert point["completeness_pct"] == 50.0           # 7 of 14 days, the rest count as 0
    assert point["valid"] is False


def test_summer_label_spans_two_years():
    from datetime import date

    from backend.app.services.data import _season_key, _season_label
    assert _season_label(*_season_key(date(2026, 1, 15))) == "Summer 2025–26"
    assert _season_label(*_season_key(date(2025, 12, 1))) == "Summer 2025–26"


def test_raw_readings_and_flagged_values(analyst):
    _, clean = _get(analyst, "/api/readings", variable="pm25", start="2025-07-01", end="2025-07-01", resolution="raw")
    assert [p["mean"] for p in clean["series"][0]["points"]] == [5.0]          # the 300 spike is left out
    _, everything = _get(analyst, "/api/readings", variable="pm25", start="2025-07-01", end="2025-07-01",
                         resolution="raw", exclude_flagged="false")
    points = everything["series"][0]["points"]
    assert [p["mean"] for p in points] == [5.0, 300.0] and points[1]["flagged"] is True


def test_raw_limited_to_7_days_and_hour_to_92(analyst):
    status, body = _get(analyst, "/api/readings", variable="pm25", start="2025-07-01", end="2025-07-08",
                        resolution="raw")
    assert status == 400 and body["error"]["code"] == "range_too_long"
    status, _ = _get(analyst, "/api/readings", variable="pm25", start="2025-01-01", end="2025-06-30", resolution="hour")
    assert status == 400


def test_invalid_date_range_message(analyst):
    status, body = _get(analyst, "/api/readings", variable="pm25", start="2025-07-07", end="2025-07-01")
    assert status == 400 and body["error"]["message"] == "Invalid date range selected."


def test_filters_and_no_data_message(analyst):
    _, park = _get(analyst, "/api/readings", variable="temperature_c", start="2025-07-01", end="2025-07-07",
                   land_use="Parkland")
    assert [s["sensor_code"] for s in park["series"]] == ["B-02"]
    _, one = _get(analyst, "/api/readings", variable="temperature_c", start="2025-07-01", end="2025-07-07",
                  sensor_ids=1)
    assert [s["sensor_code"] for s in one["series"]] == ["A-01"]
    status, body = _get(analyst, "/api/readings", variable="co_ppb", start="2025-07-01", end="2025-07-07",
                        land_use="Parkland")
    assert status == 404 and body["error"]["message"] == "No data available for the selected filters."


def test_humidity_note_only_when_libelium_humidity_shown(analyst, data_db):
    data_db.execute("INSERT INTO aggregates (sensor_id, period, bucket_start_local, season, variable, mean, min, max, "
                    "n, completeness_pct, is_valid, qc_mode) VALUES (2, 'day', '2025-07-01', 'Winter', 'humidity_pct', "
                    "80, 70, 90, 50, 80, 1, 'all')")
    data_db.commit()
    _, body = _get(analyst, "/api/readings", variable="humidity_pct", start="2025-07-01", end="2025-07-01")
    assert any("Humidity from the Libelium sensors" in n for n in body["notes"])
    _, temp = _get(analyst, "/api/readings", variable="temperature_c", start="2025-07-01", end="2025-07-01")
    assert not any("Humidity" in n for n in temp["notes"])


# ---------- exceedances ----------
def test_exceedances_sorted_filtered_and_counted(analyst):
    _, body = _get(analyst, "/api/exceedances")
    assert body["total"] == 3 and body["items"][0]["date_local"] == "2026-01-10"       # newest first
    _, by_value = _get(analyst, "/api/exceedances", sort="value", order="desc")
    assert [i["observed_value"] for i in by_value["items"]] == [41.0, 38.0, 30.0]
    _, pm = _get(analyst, "/api/exceedances", variable="pm25")
    assert pm["total"] == 1 and pm["items"][0]["unit"] == "µg/m³" and pm["items"][0]["statistic"] == "daily mean"
    _, park = _get(analyst, "/api/exceedances", land_use="Parkland")
    assert [i["sensor_code"] for i in park["items"]] == ["B-02"]
    _, page = _get(analyst, "/api/exceedances", limit=1, offset=1)
    assert page["total"] == 3 and len(page["items"]) == 1


# ---------- governance ----------
def test_data_queries_are_audited(analyst, db_conn):
    _get(analyst, "/api/readings", variable="pm25", start="2025-07-01", end="2025-07-07")
    row = db_conn.execute("SELECT detail_json FROM audit_log WHERE action = 'data_query'").fetchone()
    detail = json.loads(row["detail_json"])
    assert detail["endpoint"] == "readings" and detail["variable"] == "pm25" and detail["series"] == 2


def test_data_rate_limit_per_user(analyst):
    codes = [analyst.get("/api/sensors").status_code for _ in range(121)]
    assert codes[:120] == [200] * 120 and codes[120] == 429


def test_anonymous_gets_401(client, data_db):
    for url in ("/api/meta", "/api/sensors", "/api/readings?variable=pm25&start=2025-07-01&end=2025-07-01",
                "/api/exceedances"):
        assert client.get(url).status_code == 401


# ---------- the backend's rules match the pipeline's ----------
def test_flag_rule_matches_pipeline():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data_pipeline"))
    import etl  # noqa: E402

    from backend.app.variables import flag_hits
    cases = ["", "pm25_spike", "pm1_spike;pm25_spike;pm10_spike", "humidity_saturated", "temperature_flatline"]
    for flags in cases:
        for var in ("pm1", "pm25", "pm10", "temperature_c", "humidity_pct", "co2_ppm"):
            assert flag_hits(flags, var) == etl.flag_hits(flags, var), (flags, var)


def test_units_match_pipeline_config():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data_pipeline"))
    import config  # noqa: E402

    from backend.app.variables import VARIABLES
    for var, meta in VARIABLES.items():
        assert config.CANONICAL_UNITS[var] == meta["unit"], var


# ---------- temporal heat map ----------
def test_heatmap_grid_uses_only_valid_hours(analyst, data_db):
    data_db.executemany(
        "INSERT INTO aggregates (sensor_id, period, bucket_start_local, season, variable, mean, min, max, "
        "n, completeness_pct, is_valid, qc_mode) "
        "VALUES (?, 'hour', ?, 'Winter', 'temperature_c', ?, ?, ?, ?, ?, ?, 'all')",
        [(1, "2025-07-02 13:00", 14.5, 14, 15, 2, 33.3, 0),      # invalid hour: must be left out
         (2, "2025-07-01 13:00", 9.5, 9, 10, 4, 100.0, 1),       # second sensor, same cell
         (1, "2025-08-05 06:00", 7.0, 6, 8, 6, 100.0, 1)])
    data_db.commit()
    status, body = _get(analyst, "/api/heatmap", variable="temperature_c", start="2025-07-01", end="2025-08-31")
    assert status == 200 and body["months"] == ["2025-07", "2025-08"] and body["hours"] == list(range(24))
    cells = {(c["month"], c["hour"]): c for c in body["cells"]}
    # (12.5 x 6 + 9.5 x 4) / 10 = 11.3, from 2 valid hours; the invalid 14.5 is ignored
    assert cells[("2025-07", 13)]["mean"] == 11.3 and cells[("2025-07", 13)]["hours"] == 2
    assert cells[("2025-08", 6)]["mean"] == 7.0
    assert body["sensors"] == ["A-01", "B-02"] and body["summary"] == {"min": 7.0, "max": 11.3}


def test_heatmap_filters_limits_and_messages(analyst):
    _, one = _get(analyst, "/api/heatmap", variable="temperature_c", start="2025-07-01", end="2025-07-31",
                  sensor_ids=1)
    assert one["sensors"] == ["A-01"]
    status, body = _get(analyst, "/api/heatmap", variable="temperature_c", start="2025-01-01", end="2026-02-01")
    assert status == 400 and body["error"]["code"] == "range_too_long"
    status, body = _get(analyst, "/api/heatmap", variable="co_ppb", start="2025-07-01", end="2025-07-31",
                        land_use="Parkland")
    assert status == 404 and body["error"]["message"] == "No data available for the selected filters."
    status, body = _get(analyst, "/api/heatmap", variable="pm25", start="2025-07-31", end="2025-07-01")
    assert status == 400 and body["error"]["message"] == "Invalid date range selected."
