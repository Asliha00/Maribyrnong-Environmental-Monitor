"""Unit tests for the transform/validation rules. Run: pytest data_pipeline/tests -v"""
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import etl  # noqa: E402

BASE_MS = 1_750_000_000_000  # mid-June 2025


def libelium_frame(n=10, **overrides):
    """Build a fake Libelium export with n readings 15 minutes apart."""
    ts = [BASE_MS + i * 900_000 for i in range(n)]
    df = pd.DataFrame({
        "timestamp": ts,
        "temperature": [15.0 + i * 0.1 for i in range(n)],
        "humidity": [60.0] * n,
        "pm1": [1.0] * n, "pm25": [2.0] * n, "pm10": [3.0] * n,
        "no2": [0.05] * n, "co2": [400.0] * n,
        "pressure": [101300.0] * n, "batteryvoltage": [4.2] * n,
    })
    for col, values in overrides.items():
        df[col] = values
    return df


def run(df, family="libelium"):
    return etl.transform(df, family, sensor_id=1)


def test_unit_conversions():
    clean, _, _ = run(libelium_frame())
    assert clean.pressure_hpa.iloc[0] == pytest.approx(1013.0)   # Pa -> hPa
    assert clean.no2_ppb.iloc[0] == pytest.approx(50.0)          # ppm -> ppb


def test_out_of_range_value_rejected_but_row_kept():
    temps = [15.0] * 10
    temps[3] = 122.88  # the real Nicholson Mall error code
    clean, errors, stats = run(libelium_frame(temperature=temps))
    assert len(clean) == 10                     # row kept
    assert np.isnan(clean.temperature_c.iloc[3])  # value nulled
    assert clean.humidity_pct.iloc[3] == 60.0     # other values untouched
    assert (errors.error_type == "out_of_range").sum() == 1
    assert stats["values_rejected"] == 1


def test_duplicate_timestamps_removed_and_logged():
    df = libelium_frame()
    df.loc[5, "timestamp"] = df.loc[4, "timestamp"]
    clean, errors, stats = run(df)
    assert len(clean) == 9
    assert stats["rows_duplicate"] == 1
    assert "duplicate" in errors.error_type.values


def test_invalid_timestamp_logged():
    df = libelium_frame()
    df["timestamp"] = df["timestamp"].astype(object)
    df.loc[2, "timestamp"] = "not-a-time"
    clean, errors, _ = run(df)
    assert len(clean) == 9
    assert "invalid_timestamp" in errors.error_type.values


def test_all_zero_column_treated_as_not_fitted():
    clean, errors, stats = run(libelium_frame(co2=[0.0] * 10))
    assert clean.co2_ppm.isna().all()
    assert "co2_ppm" not in stats["variables"]
    assert "not_fitted" in errors.error_type.values


def test_humidity_saturation_flagged_not_removed():
    clean, _, _ = run(libelium_frame(humidity=[100.0] * 10))
    assert clean.humidity_pct.iloc[0] == 100.0
    assert "humidity_saturated" in clean.qc_flags.iloc[0]


def test_pm_spike_flagged():
    pm = [2.0] * 10
    pm[5] = 300.0
    clean, _, _ = run(libelium_frame(pm10=pm))
    assert "pm10_spike" in clean.qc_flags.iloc[5]
    assert clean.pm10.iloc[5] == 300.0   # real events are kept


def test_temperature_flatline_flagged():
    clean, _, _ = run(libelium_frame(n=15, temperature=[20.0] * 15))
    assert clean.qc_flags.str.contains("temperature_flatline").all()


def test_local_time_has_melbourne_offset():
    clean, _, _ = run(libelium_frame())
    assert clean.ts_local.iloc[0].endswith("+1000")  # June = AEST


def test_season_mapping():
    assert etl.season_of(1) == "Summer"
    assert etl.season_of(7) == "Winter"
    assert etl.season_of(10) == "Spring"
    assert etl.season_of(4) == "Autumn"


def test_end_to_end_idempotent(tmp_path, monkeypatch):
    raw = libelium_frame(n=200)
    f = tmp_path / "mcc---environment-sensor-libelium---footscray-park-amenities-block_test.csv"
    raw.to_csv(f, index=False)
    conn = etl.connect(f"sqlite:///{tmp_path / 't.db'}")
    reg = etl.sync_sensor_registry(conn)
    etl.ingest_file(conn, f, reg)
    etl.ingest_file(conn, f, reg)            # second run is skipped (sha256)
    etl.ingest_file(conn, f, reg, force=True)  # forced run inserts nothing new
    n = conn.scalar("SELECT COUNT(*) FROM readings")
    assert n == 200
    etl.build_aggregates(conn)
    day = conn.scalar("SELECT COUNT(*) FROM aggregates WHERE period='day'")
    assert day > 0


def test_flag_hits_maps_flags_to_their_own_variable():
    assert etl.flag_hits("pm25_spike", "pm25")
    assert not etl.flag_hits("pm10_spike", "pm1") and not etl.flag_hits("pm1_spike", "pm10")
    assert etl.flag_hits("temperature_flatline", "temperature_c")
    assert etl.flag_hits("humidity_saturated;pm10_spike", "humidity_pct")
    assert not etl.flag_hits("humidity_saturated", "temperature_c")
    assert not etl.flag_hits("", "pm25")


def test_clean_aggregates_leave_out_flagged_values(tmp_path):
    """D-028: 'clean' drops values whose own variable is flagged; 'all' keeps them;
    exceedances stay on 'all'."""
    raw = libelium_frame(n=200)
    f = tmp_path / "mcc---environment-sensor-libelium---footscray-park-amenities-block_test.csv"
    raw.to_csv(f, index=False)
    conn = etl.connect(f"sqlite:///{tmp_path / 't.db'}")
    etl.ingest_file(conn, f, etl.sync_sensor_registry(conn))
    rid = conn.scalar("SELECT reading_id FROM readings ORDER BY ts_utc LIMIT 1")
    conn.execute("UPDATE readings SET pm25 = 999, qc_flags = 'pm25_spike' WHERE reading_id = ?", (rid,))
    conn.commit()
    etl.build_aggregates(conn)

    def month(var, mode):
        return conn.execute("SELECT max, n FROM aggregates WHERE period='month' AND variable=? AND qc_mode=? "
                            "ORDER BY bucket_start_local LIMIT 1", (var, mode)).fetchone()

    assert month("pm25", "all")[0] == 999                        # the spike is kept in 'all'
    assert month("pm25", "clean")[0] < 999                       # and left out of 'clean'
    assert month("pm25", "clean")[1] == month("pm25", "all")[1] - 1
    # sparse storage: an unaffected variable has no clean row (readers fall back to 'all')
    assert month("temperature_c", "clean") is None


def test_fully_flagged_bucket_gets_empty_clean_row(tmp_path):
    raw = libelium_frame(n=200)
    f = tmp_path / "mcc---environment-sensor-libelium---footscray-park-amenities-block_test.csv"
    raw.to_csv(f, index=False)
    conn = etl.connect(f"sqlite:///{tmp_path / 't.db'}")
    etl.ingest_file(conn, f, etl.sync_sensor_registry(conn))
    first_hour = conn.execute("SELECT substr(ts_local, 1, 13) FROM readings ORDER BY ts_utc LIMIT 1").fetchone()[0]
    conn.execute("UPDATE readings SET qc_flags = 'pm25_spike' WHERE substr(ts_local, 1, 13) = ?", (first_hour,))
    conn.commit()
    etl.build_aggregates(conn)
    bucket = first_hour.replace("T", " ") + ":00"
    row = conn.execute("SELECT n, mean, is_valid FROM aggregates WHERE period='hour' AND variable='pm25' "
                       "AND qc_mode='clean' AND bucket_start_local = ?", (bucket,)).fetchone()
    assert row == (0, None, 0)   # explicit "no clean data" for that hour


def test_seeding_keeps_an_admin_edited_threshold(tmp_path):
    """D-033: a rebuild must not add the original threshold back after an admin edit."""
    conn = etl.connect(f"sqlite:///{tmp_path / 't.db'}")
    etl.seed_thresholds(conn)
    count = conn.scalar("SELECT COUNT(*) FROM thresholds")
    assert count == len(etl.C.THRESHOLDS)
    conn.execute("UPDATE thresholds SET value = 20 WHERE variable = 'pm25' AND period = 'day'")
    etl.seed_thresholds(conn)
    assert conn.scalar("SELECT COUNT(*) FROM thresholds") == count
    assert conn.scalar("SELECT value FROM thresholds WHERE variable = 'pm25' AND period = 'day'") == 20


def test_one_sensor_rebuild_leaves_other_sensors_alone(tmp_path):
    """D-033: an admin upload rebuilds aggregates for its own sensor only."""
    conn = etl.connect(f"sqlite:///{tmp_path / 't.db'}")
    reg = etl.sync_sensor_registry(conn)
    for code in ("FP-AMEN", "FP-LH"):
        raw = libelium_frame(n=200)
        sensor = reg[reg.sensor_code == code].iloc[0]
        f = tmp_path / f"upload_{code}.csv"            # name matches nothing: the sensor is passed in
        raw.to_csv(f, index=False)
        etl.ingest_file(conn, f, reg, sensor=sensor)
    etl.build_aggregates(conn)
    amen, lh = (int(reg[reg.sensor_code == c].iloc[0].sensor_id) for c in ("FP-AMEN", "FP-LH"))
    before = conn.scalar("SELECT COUNT(*) FROM aggregates WHERE sensor_id = ?", (lh,))
    conn.execute("UPDATE aggregates SET mean = -999 WHERE sensor_id = ?", (lh,))   # marker
    conn.execute("DELETE FROM aggregates WHERE sensor_id = ?", (amen,))
    etl.build_aggregates(conn, sensor_id=amen)
    assert conn.scalar("SELECT COUNT(*) FROM aggregates WHERE sensor_id = ?", (amen,)) > 0
    assert conn.scalar("SELECT COUNT(*) FROM aggregates WHERE sensor_id = ? AND mean = -999", (lh,)) == before


def test_named_sensor_overrides_file_name_matching(tmp_path):
    conn = etl.connect(f"sqlite:///{tmp_path / 't.db'}")
    reg = etl.sync_sensor_registry(conn)
    f = tmp_path / "mystery.csv"
    libelium_frame(n=50).to_csv(f, index=False)
    assert etl.ingest_file(conn, f, reg) is None                       # unknown by name: logged, skipped
    sensor = reg[reg.sensor_code == "SALT-CC"].iloc[0]
    assert etl.ingest_file(conn, f, reg, sensor=sensor)["rows_read"] == 50


def test_seeding_skips_a_threshold_with_the_same_value_but_another_label(tmp_path):
    conn = etl.connect(f"sqlite:///{tmp_path / 't.db'}")
    var, per, op, val, _label, src = etl.C.THRESHOLDS[0]
    conn.execute("INSERT INTO thresholds (variable, period, operator, value, label, source) VALUES (?,?,?,?,?,?)",
                 (var, per, op, val, "Renamed by an administrator", src))
    etl.seed_thresholds(conn)                                   # must not violate UNIQUE(variable, period, value)
    assert conn.scalar("SELECT COUNT(*) FROM thresholds WHERE variable = ? AND period = ? AND value = ?",
                       (var, per, val)) == 1


# ---------- live readings (UC4): the same rules as file loads ----------
def _recent(values: list[dict]) -> pd.DataFrame:
    base = pd.Timestamp("2026-01-01T00:00:00Z")
    return pd.DataFrame([{"ts_utc": (base + pd.Timedelta(minutes=15 * i)).strftime("%Y-%m-%dT%H:%M:%SZ"), **v}
                         for i, v in enumerate(values)])


NOW = pd.Timestamp("2026-01-01T06:00:00Z")


def test_live_reading_converts_units_like_a_file():
    row, errors, stats = etl.transform_live({"temperature": 21.5, "pressure": 101325, "no2": 0.04}, NOW,
                                            "libelium", 3, _recent([]))
    assert row["temperature_c"] == 21.5 and row["pressure_hpa"] == 1013.25 and row["no2_ppb"] == 40
    assert row["ts_utc"] == "2026-01-01T06:00:00Z" and row["ts_local"] == "2026-01-01T17:00:00+1100"
    assert errors == [] and stats["flags"] == [] and row["qc_flags"] is None


def test_live_out_of_range_value_rejected_and_logged():
    row, errors, stats = etl.transform_live({"temperature": 75.0, "pm25": 4.0}, NOW, "mcc_aq", 1, _recent([]))
    assert row["temperature_c"] is None and row["pm25"] == 4.0
    assert stats["values_rejected"] == 1
    assert errors[0]["error_type"] == "out_of_range" and errors[0]["variable"] == "temperature_c"


def test_live_spike_uses_previous_readings():
    calm = _recent([{"pm25": 5.0}] * 6)
    _, _, stats = etl.transform_live({"pm25": 400.0}, NOW, "mcc_aq", 1, calm)
    assert stats["flags"] == ["pm25_spike"]
    _, _, stats = etl.transform_live({"pm25": 6.0}, NOW, "mcc_aq", 1, calm)
    assert stats["flags"] == []


def test_live_flatline_counts_the_run_before_it():
    frozen = _recent([{"temperature_c": 18.2}] * (etl.C.FLATLINE_MIN_RUN - 1))
    _, _, stats = etl.transform_live({"temperature": 18.2}, NOW, "mcc_aq", 1, frozen)
    assert stats["flags"] == ["temperature_flatline"]
    _, _, stats = etl.transform_live({"temperature": 18.3}, NOW, "mcc_aq", 1, frozen)
    assert stats["flags"] == []


def test_live_saturated_humidity_flagged_and_unknown_fields_ignored():
    row, _, stats = etl.transform_live({"humidity": 100.0, "batteryvoltage": 3.9}, NOW, "libelium", 3, _recent([]))
    assert stats["flags"] == ["humidity_saturated"] and row["battery_v"] == 3.9


def test_shared_rules_give_the_batch_result_unchanged(tmp_path):
    """The refactor into shared helpers must not change what a file load produces."""
    raw = libelium_frame(n=60)
    raw.loc[10, "pm25"] = 900          # out of range
    raw.loc[20:40, "temperature"] = 17.0
    df, errors, stats = etl.transform(raw, "libelium", 1)
    assert stats["values_rejected"] == 1 and errors["error_type"].tolist().count("out_of_range") == 1
    assert df.qc_flags.fillna("").str.contains("temperature_flatline").sum() == 21
