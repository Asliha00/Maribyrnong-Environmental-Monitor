"""
Performance (BUILD_PROMPT §6): dashboard filter responses < 3 s at p95.

Times the key endpoints over the FULL year of council data (local SQLite copy) and
prints p50/p95/p99. Needs data/processed/environment.db (`make db`); skipped in CI,
which has no council data. Deployed timings: scripts/measure_latency.py.

    python -m pytest backend/tests/test_performance.py -s
    PERF_REPORT=docs/performance/local.md python -m pytest backend/tests/test_performance.py -s
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.config import ROOT
from backend.tests.conftest import STRONG_PASSWORD, TEST_ENV, _hash

FULL_DB = ROOT / "data" / "processed" / "environment.db"
REPEATS = 30
P95_TARGET_S = 3.0

ENDPOINTS = [
    ("meta", "/api/meta"),
    ("sensors (map)", "/api/sensors"),
    ("sensor detail", "/api/sensors/1"),
    ("daily, full year, temperature, all sensors",
     "/api/readings?variable=temperature_c&resolution=day&start=2025-02-16&end=2026-02-16"),
    ("monthly, full year, PM2.5", "/api/readings?variable=pm25&resolution=month&start=2025-02-16&end=2026-02-16"),
    ("seasonal, full year, temperature",
     "/api/readings?variable=temperature_c&resolution=season&start=2025-02-16&end=2026-02-16"),
    ("hourly, 92 days, temperature",
     "/api/readings?variable=temperature_c&resolution=hour&start=2025-11-17&end=2026-02-16"),
    ("raw, 7 days, PM2.5", "/api/readings?variable=pm25&resolution=raw&start=2026-01-20&end=2026-01-26"),
    ("daily, flagged included, PM10",
     "/api/readings?variable=pm10&resolution=day&start=2025-02-16&end=2026-02-16&exclude_flagged=false"),
    ("exceedances", "/api/exceedances?sort=value"),
    ("heat map, full year, temperature", "/api/heatmap?variable=temperature_c&start=2025-02-16&end=2026-02-16"),
    ("insights, full year (first request computes, then cached)", "/api/analysis/disparities"),
]
EXPORT = {"variable": "pm25", "resolution": "day", "start": "2025-02-16", "end": "2026-02-16"}
EXPORTS = [("export CSV, daily, full year, PM2.5", {**EXPORT, "format": "csv"}),
           ("export PDF, daily, full year, PM2.5", {**EXPORT, "format": "pdf"}),
           ("export CSV, hourly, 92 days, temperature",
            {"variable": "temperature_c", "resolution": "hour", "start": "2025-11-17", "end": "2026-02-16",
             "format": "csv"})]

pytestmark = pytest.mark.skipif(not FULL_DB.exists(), reason="needs the full council database (make db)")


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * len(ordered) + 0.5) - 1))
    return ordered[index]


@pytest.fixture(scope="module")
def full_client(tmp_path_factory):
    from backend.app.config import Settings
    from backend.app.main import create_app

    copy = tmp_path_factory.mktemp("perf") / "environment.db"
    shutil.copyfile(FULL_DB, copy)        # never write to the developer's working database
    conn = sqlite3.connect(copy)
    conn.execute("DELETE FROM users WHERE email = 'perf.analyst@example.org'")
    conn.execute("INSERT INTO users (username, email, password_hash, role_id, must_change_password) "
                 "VALUES ('perf_analyst', 'perf.analyst@example.org', ?, 2, 0)", (_hash(STRONG_PASSWORD),))
    conn.commit()
    settings = Settings(_env_file=None, environment="test", jwt_secret=TEST_ENV["JWT_SECRET"],
                        mfa_encryption_key=TEST_ENV["MFA_ENCRYPTION_KEY"], app_database_url="", sqlite_path=copy)
    client = TestClient(create_app(settings), base_url="https://testserver")
    assert client.post("/api/auth/login", json={"email": "perf.analyst@example.org",
                                                "password": STRONG_PASSWORD}).status_code == 200
    yield client, conn
    conn.close()


def test_key_endpoints_meet_p95_target(full_client):
    client, conn = full_client
    results = []
    csrf = {"X-CSRF-Token": client.cookies.get("mem_csrf") or ""}
    requests = [(name, url, None) for name, url in ENDPOINTS] + [(name, "/api/reports/export", body)
                                                                for name, body in EXPORTS]
    for name, url, body in requests:
        timings = []
        for _ in range(REPEATS):
            conn.execute("DELETE FROM rate_limits")   # the per-user limits are not what is measured here
            conn.commit()
            t0 = time.perf_counter()
            response = client.get(url) if body is None else client.post(url, json=body, headers=csrf)
            timings.append(time.perf_counter() - t0)
            assert response.status_code == 200, (name, response.text[:200])
        size_kb = len(response.content) / 1024
        results.append((name, _percentile(timings, 50), _percentile(timings, 95), _percentile(timings, 99),
                        statistics.mean(timings), size_kb))

    lines = [f"Local performance, full year of data (SQLite, in-process), {REPEATS} requests each, "
             f"{datetime.now(UTC):%Y-%m-%d %H:%M} UTC", "",
             "| Endpoint | p50 (ms) | p95 (ms) | p99 (ms) | mean (ms) | response (KB) |", "|---|--:|--:|--:|--:|--:|"]
    lines += [f"| {n} | {p50*1000:.0f} | {p95*1000:.0f} | {p99*1000:.0f} | {mean*1000:.0f} | {kb:.0f} |"
              for n, p50, p95, p99, mean, kb in results]
    report = "\n".join(lines)
    print("\n" + report)
    if os.environ.get("PERF_REPORT"):
        Path(os.environ["PERF_REPORT"]).parent.mkdir(parents=True, exist_ok=True)
        Path(os.environ["PERF_REPORT"]).write_text(report + "\n", encoding="utf-8")

    slow = [(n, round(p95, 2)) for n, _, p95, *_ in results if p95 >= P95_TARGET_S]
    assert not slow, f"p95 over {P95_TARGET_S}s: {slow}"
