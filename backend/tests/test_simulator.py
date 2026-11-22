"""scripts/simulate_sensor.py replays real-format readings to the real ingest endpoint (in-process)."""
import sys
from pathlib import Path

import pandas as pd

from backend.app.services import live
from backend.tests.security.test_ingest_security import KEY
from backend.tests.test_data_api import data_db  # noqa: F401 - fixture

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import simulate_sensor  # noqa: E402


def test_simulator_replays_a_day(client, db_conn, data_db, tmp_path, monkeypatch, capsys):  # noqa: F811
    db_conn.execute("UPDATE sensors SET auth_key_hash = ? WHERE sensor_id = 1", (live.key_hash(KEY),))
    db_conn.commit()
    start = pd.Timestamp("2025-08-01T00:00:00+10:00").value // 1_000_000
    pd.DataFrame({"timestamp": [start + i * 600_000 for i in range(5)],
                  "temperature": [12.0, 12.5, 13.0, 95.0, 13.5], "pm25": [4.0] * 5,
                  "aqi": [20] * 5}).to_csv(tmp_path / "mcc.csv", index=False)
    monkeypatch.setenv("SIM_DEVICE_KEY", KEY)
    monkeypatch.setattr(simulate_sensor.time, "sleep", lambda s: None)
    # each reading gets its own second, as the 1-second pacing would give it
    clock = iter(pd.date_range(pd.Timestamp.now(tz="UTC").floor("s") - pd.Timedelta(seconds=10), periods=10,
                               freq="s"))
    monkeypatch.setattr(simulate_sensor, "datetime",
                        type("FakeDatetime", (), {"now": staticmethod(lambda tz=None: next(clock))}))
    # the in-process app (TestClient is an httpx.Client) instead of a network server
    monkeypatch.setattr(simulate_sensor.httpx, "Client", lambda base_url, timeout: client)
    secret = "bypass-secret-value-1234567890"
    monkeypatch.setenv("VERCEL_PROTECTION_BYPASS", secret)
    report = tmp_path / "ingestion.md"
    code = simulate_sensor.main(["--device-id", "A-01", "--file", str(tmp_path / "mcc.csv"), "--day", "2025-08-01",
                                 "--out-of-range-every", "2", "--report", str(report)])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "Outcomes: {'stored': 5}" in out and "HTTP: {200: 5}" in out
    assert "TEST temperature=95.0" in out and "rejected=temperature_c" in out
    assert "warm p50" in out and "First (possibly cold)" in out
    text = report.read_text(encoding="utf-8")
    assert "**Result: PASS**" in text and "| Non-200 responses | 0 |" in text
    assert "| 2 | temperature | 95.0 | 200 | temperature_c |" in text      # injected test values listed
    for leaked in (KEY, secret):
        assert leaked not in out and leaked not in text                     # never printed or saved
    # readings 2 and 4 were injected; reading 4 was already 95.0 in the file
    assert db_conn.execute("SELECT COUNT(*) FROM error_log WHERE error_type = 'out_of_range'").fetchone()[0] == 2


def test_latency_summary_separates_the_first_request():
    s = simulate_sensor.latency_summary([2.5] + [0.1] * 19 + [0.9])
    assert s["cold_ms"] == 2500 and s["warm_n"] == 20
    assert round(s["p50_ms"]) == 100 and round(s["max_ms"]) == 900


def test_readings_continue_into_the_next_day_until_the_limit(tmp_path):
    """The first full day of the MCC-01 file has only 65 readings; a limit of 100 must carry on."""
    day1 = pd.Timestamp("2025-08-01T00:00:00+10:00").value // 1_000_000
    day2 = pd.Timestamp("2025-08-02T00:00:00+10:00").value // 1_000_000
    stamps = [day1 + i * 600_000 for i in range(3)] + [day2 + i * 600_000 for i in range(3)]
    pd.DataFrame({"timestamp": stamps, "temperature": [10.0 + i for i in range(6)]}).to_csv(tmp_path / "m.csv",
                                                                                             index=False)
    span, readings = simulate_sensor.day_readings(tmp_path / "m.csv", "mcc_aq", "2025-08-01", limit=5)
    assert span == "2025-08-01 to 2025-08-02" and [r["temperature"] for r in readings] == [10, 11, 12, 13, 14]
    assert len(simulate_sensor.day_readings(tmp_path / "m.csv", "mcc_aq", "2025-08-01")[1]) == 3   # no limit: one day


def test_a_slow_request_never_causes_catch_up_sends(tmp_path, monkeypatch, capsys):
    """Regression (2026-10-31): after a 6.8 s cold start the old pacing sent the next readings
    back-to-back, several in one second, so the API rightly answered 'duplicate'."""
    start = pd.Timestamp("2025-08-01T00:00:00+10:00").value // 1_000_000
    pd.DataFrame({"timestamp": [start + i * 600_000 for i in range(6)], "temperature": [12.0] * 6}) \
        .to_csv(tmp_path / "mcc.csv", index=False)
    now = [1000.0]                                  # one fake clock for monotonic time and wall time
    sends: list[float] = []
    latencies = iter([6.8, 0.2, 0.2, 0.2, 0.2, 0.2])

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}

        @staticmethod
        def json():
            return {"status": "stored"}

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, json, headers):
            sends.append(now[0])
            now[0] += next(latencies)
            return FakeResponse()

    def sleep(seconds):
        now[0] += seconds

    monkeypatch.setenv("SIM_DEVICE_KEY", "k" * 43)
    monkeypatch.setattr(simulate_sensor.time, "sleep", sleep)
    monkeypatch.setattr(simulate_sensor.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(simulate_sensor.time, "perf_counter", lambda: now[0])
    monkeypatch.setattr(simulate_sensor, "datetime", type("FakeDatetime", (), {
        "now": staticmethod(lambda tz=None: pd.Timestamp(now[0], unit="s", tz="UTC"))}))
    monkeypatch.setattr(simulate_sensor.httpx, "Client", lambda base_url, timeout: FakeClient())
    assert simulate_sensor.main(["--device-id", "X", "--file", str(tmp_path / "mcc.csv"), "--day", "2025-08-01"]) == 0
    gaps = [b - a for a, b in zip(sends, sends[1:], strict=False)]
    assert len(sends) == 6 and min(gaps) >= 1.0          # never two sends within a second
    stamps = [int(s) for s in sends]
    assert len(set(stamps)) == len(stamps)               # every timestamp second is unique
    assert "First (possibly cold) 6800 ms" in capsys.readouterr().out
