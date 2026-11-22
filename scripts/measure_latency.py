"""
Measure the DEPLOYED site's data API latency (BUILD_PROMPT §6).

Reports, per endpoint, the first request (after the site has been idle, so it may
include Vercel function and Neon compute cold starts) separately from warm p50/p95/p99.

    python scripts/measure_latency.py --email demo.analyst@example.org
    python scripts/measure_latency.py --email ... --report docs/performance/deployed_2026-10-28.md

The password is asked for interactively (or read from MEASURE_PASSWORD) and is never
printed or written anywhere. Run it after ~10 minutes of no traffic for a true cold start.
Stays under the API's 120 requests/minute/user limit and the 10 exports/minute limit
(exports are real, so each one is logged in `reports` and the audit log like any user's).
"""
from __future__ import annotations

import argparse
import getpass
import os
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

DEFAULT_URL = "https://maribyrnong-environmental-monitor.vercel.app"
WARM_REPEATS = 10
ENDPOINTS = [
    ("health (no auth)", "/api/health"),
    ("sensors (map)", "/api/sensors"),
    ("daily, full year, temperature",
     "/api/readings?variable=temperature_c&resolution=day&start=2025-02-16&end=2026-02-16"),
    ("monthly, full year, PM2.5", "/api/readings?variable=pm25&resolution=month&start=2025-02-16&end=2026-02-16"),
    ("seasonal, full year, temperature",
     "/api/readings?variable=temperature_c&resolution=season&start=2025-02-16&end=2026-02-16"),
    ("hourly, 92 days, temperature",
     "/api/readings?variable=temperature_c&resolution=hour&start=2025-11-17&end=2026-02-16"),
    ("raw, 7 days, PM2.5", "/api/readings?variable=pm25&resolution=raw&start=2026-01-20&end=2026-01-26"),
    ("exceedances", "/api/exceedances?sort=value"),
    ("heat map, full year, temperature", "/api/heatmap?variable=temperature_c&start=2025-02-16&end=2026-02-16"),
]
EXPORT_REPEATS = 4   # 2 formats x (1 first + 4 warm) = 10 exports: exactly the per-minute limit
EXPORT_FILTERS = {"variable": "pm25", "resolution": "day", "start": "2025-02-16", "end": "2026-02-16"}
EXPORTS = [("export CSV, daily, full year, PM2.5", "csv"), ("export PDF, daily, full year, PM2.5", "pdf")]


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(pct / 100 * len(ordered) + 0.5) - 1))]


def timed_get(client: httpx.Client, url: str) -> tuple[float, httpx.Response]:
    t0 = time.perf_counter()
    response = client.get(url)
    return time.perf_counter() - t0, response


def timed_export(client: httpx.Client, fmt: str) -> tuple[float, httpx.Response]:
    t0 = time.perf_counter()
    response = client.post("/api/reports/export", json={**EXPORT_FILTERS, "format": fmt},
                           headers={"X-CSRF-Token": client.cookies.get("mem_csrf") or ""})
    return time.perf_counter() - t0, response


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--email", required=True)
    parser.add_argument("--report", help="also write the results as Markdown to this file")
    args = parser.parse_args()
    password = os.environ.get("MEASURE_PASSWORD") or getpass.getpass(f"Password for {args.email}: ")

    with httpx.Client(base_url=args.url, timeout=60, follow_redirects=False) as client:
        # Health first: its timing shows the cold start before any authenticated call
        cold_health, _ = timed_get(client, "/api/health")
        t0 = time.perf_counter()
        login = client.post("/api/auth/login", json={"email": args.email, "password": password})
        login_s = time.perf_counter() - t0
        del password
        if login.status_code != 200:
            print(f"Login failed: HTTP {login.status_code} {login.json().get('error', {}).get('message', '')}")
            return 1
        if login.json().get("next_step") not in ("done", "mfa_setup", "mfa_verify"):
            print("This account must change its password first; use another account.")
            return 1

        rows = []
        for name, url in ENDPOINTS:
            first, response = timed_get(client, url)
            if response.status_code != 200:
                print(f"{name}: HTTP {response.status_code}")
                return 1
            warm = [timed_get(client, url)[0] for _ in range(WARM_REPEATS)]
            rows.append((name, first, percentile(warm, 50), percentile(warm, 95), percentile(warm, 99),
                         statistics.mean(warm), len(response.content) / 1024))
        for name, fmt in EXPORTS:
            first, response = timed_export(client, fmt)
            if response.status_code != 200:
                print(f"{name}: HTTP {response.status_code}")
                return 1
            warm = [timed_export(client, fmt)[0] for _ in range(EXPORT_REPEATS)]
            rows.append((name, first, percentile(warm, 50), percentile(warm, 95), percentile(warm, 99),
                         statistics.mean(warm), len(response.content) / 1024))
        client.post("/api/auth/logout", headers={"X-CSRF-Token": client.cookies.get("mem_csrf") or ""})

    lines = [f"Deployed latency, {args.url}, {datetime.now(UTC):%Y-%m-%d %H:%M} UTC "
             f"(from the measuring machine; includes its network path)", "",
             f"First request of the run (`/api/health`, possibly cold): {cold_health*1000:.0f} ms; "
             f"login (argon2id verification): {login_s*1000:.0f} ms", "",
             "| Endpoint | first (ms) | warm p50 (ms) | warm p95 (ms) | warm p99 (ms) | mean (ms) | KB |",
             "|---|--:|--:|--:|--:|--:|--:|"]
    lines += [f"| {n} | {f*1000:.0f} | {p50*1000:.0f} | {p95*1000:.0f} | {p99*1000:.0f} | {m*1000:.0f} | {kb:.0f} |"
              for n, f, p50, p95, p99, m, kb in rows]
    report = "\n".join(lines)
    print(report)
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(report + "\n", encoding="utf-8")
    slow = [n for n, _, _, p95, *_ in rows if p95 >= 3.0]
    print("\nAll warm p95 under 3 s." if not slow else f"\nWarm p95 at or over 3 s: {slow}")
    return 0 if not slow else 2


if __name__ == "__main__":
    sys.exit(main())
