"""
Replay one day of REAL council readings to POST /api/ingest, as a live device would (UC4 demo,
and the deployed ingestion-latency measurement).

    python scripts/simulate_sensor.py --url https://<preview>.vercel.app --device-id SIM-01 \
        --file data/raw/mcc---1_1_device_17_variables_RTG7DUBK4D.csv --limit 100 \
        --out-of-range-every 25 --report docs/performance/ingestion_preview_<date>.md

* Register the device first (Administration -> Sensors -> Register; device type must match the
  file) and copy its device key. The key is read from SIM_DEVICE_KEY (.env) or asked for, and is
  never printed.
* Each reading keeps its measured values but is stamped with the CURRENT time: the API rejects
  timestamps more than 5 minutes from server time (SEC-03 replay protection), so a historical
  day cannot be sent with its original times. Readings go out at a steady rate (`--speed`
  seconds apart, at least 1), which also keeps every timestamp unique.
* Run it against a local server or the Preview deployment (Neon dev branch), not production
  (DECISIONS.md D-034): the readings become "today" and would mix with the council data.
  Preview deployments are protected; put a "Protection Bypass for Automation" secret (Vercel ->
  Settings -> Deployment Protection) in .env as VERCEL_PROTECTION_BYPASS. It is sent as the
  x-vercel-protection-bypass header and never printed or written to the report.
* `--out-of-range-every N` replaces the temperature of every Nth reading with 95.0 (outside the
  valid -20..60 °C range): a TEST value, to check it is rejected, logged and answered 200.

Prints one line per reading (status, flags, rejected values, round-trip time) and a summary: the
first request (possibly a cold start) separately from warm p50/p95/p99/max, against the 2 s target.
"""
from __future__ import annotations

import argparse
import getpass
import math
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "data_pipeline"))
import config as C  # noqa: E402  (also loads .env into the environment)

DEFAULT_URL = "http://127.0.0.1:8000"
TARGET_P95_S = 2.0          # BUILD_PROMPT §6: ingestion under 2 s
TEST_TEMPERATURE = 95.0     # outside VALID_RANGES["temperature_c"] (-20..60)


def day_readings(path: Path, family: str, day: str | None, limit: int = 0) -> tuple[str, list[dict[str, float]]]:
    """Readings as device payload values (the device's own field names), in time order. Without
    a limit: one local day. With a limit: from that day onward, across day boundaries, until
    `limit` readings are collected. Returns a description of the days used and the readings."""
    raw = pd.read_csv(path, low_memory=False)
    fields = [f for f in C.COLUMN_MAP[family] if f in raw.columns]
    if not fields:
        raise SystemExit(f"{path.name} has no {family} measurement columns. Check --family.")
    ts = pd.to_datetime(pd.to_numeric(raw["timestamp"], errors="coerce"), unit="ms", utc=True)
    local_day = ts.dt.tz_convert(C.LOCAL_TZ).dt.strftime("%Y-%m-%d")
    day = day or local_day.dropna().value_counts().sort_index().index[1]   # first full day
    chosen = (local_day >= day) if limit else (local_day == day)
    rows = raw[chosen].assign(_ts=ts, _day=local_day).sort_values("_ts")
    if rows.empty:
        raise SystemExit(f"No readings on or after {day} in {path.name}.")
    out, days = [], []
    for _, r in rows.iterrows():
        values = {f: float(r[f]) for f in fields if pd.notna(r[f]) and math.isfinite(float(r[f]))}
        if values:
            out.append(values)
            days.append(r["_day"])
        if limit and len(out) == limit:
            break
    return (days[0] if days[0] == days[-1] else f"{days[0]} to {days[-1]}"), out


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(pct / 100 * len(ordered) + 0.5) - 1))]


def latency_summary(latencies: list[float]) -> dict[str, float | int | None]:
    """The first request (possibly a cold start) separately from the warm ones that follow, in ms."""
    warm = latencies[1:]
    return {"cold_ms": latencies[0] * 1000 if latencies else None, "warm_n": len(warm),
            "p50_ms": percentile(warm, 50) * 1000 if warm else None,
            "p95_ms": percentile(warm, 95) * 1000 if warm else None,
            "p99_ms": percentile(warm, 99) * 1000 if warm else None,
            "max_ms": max(warm) * 1000 if warm else None}


def _ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f}"


def write_report(path: Path, meta: dict, s: dict, counts: dict[str, int], codes: dict[int, int],
                 injected: list[dict]) -> None:
    """Markdown report. Contains no key, no bypass secret and no full URL query."""
    passed = s["p95_ms"] is not None and s["p95_ms"] < TARGET_P95_S * 1000
    non_200 = sum(n for code, n in codes.items() if code != 200)
    lines = [f"# Live ingestion latency ({meta['when']})", "",
             f"Target `{meta['host']}` (POST /api/ingest), device `{meta['device']}`: {meta['sent']} readings "
             f"replayed from `{meta['file']}` (local day {meta['day']}), one every {meta['interval']:.0f} s, "
             "each re-stamped to the current time (SEC-03 replay window).",
             "Times are measured on the client from sending each request to receiving its response, so they "
             "include the network path from the measuring machine.", "",
             "| Measure | Value |", "|---|--:|",
             f"| First request (after the Preview was idle; may include a cold start) | {_ms(s['cold_ms'])} ms |",
             f"| Warm requests | {s['warm_n']} |",
             f"| Warm p50 | {_ms(s['p50_ms'])} ms |",
             f"| Warm p95 | {_ms(s['p95_ms'])} ms |",
             f"| Warm p99 | {_ms(s['p99_ms'])} ms |",
             f"| Warm max | {_ms(s['max_ms'])} ms |",
             f"| Non-200 responses | {non_200} |", "",
             f"**Result: {'PASS' if passed else 'FAIL'}** (warm p95 {_ms(s['p95_ms'])} ms against the "
             f"{TARGET_P95_S:.0f} s target).", "",
             "HTTP status counts: " + ", ".join(f"{c}: {n}" for c, n in sorted(codes.items())) + ".",
             "Outcomes: " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) + ".", ""]
    if injected:
        lines += ["Out-of-range TEST values (deliberately injected; expected: HTTP 200, the value rejected and "
                  "logged, the rest of the reading stored):", "",
                  "| Reading | Field | Sent | HTTP | Rejected by the API |", "|--:|---|--:|--:|---|"]
        lines += [f"| {x['index']} | {x['field']} | {x['value']} | {x['http']} | "
                  f"{', '.join(x['rejected']) or 'none'} |" for x in injected]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=DEFAULT_URL, help=f"site base URL (default {DEFAULT_URL})")
    ap.add_argument("--device-id", required=True, help="the registered sensor code, e.g. SIM-01")
    ap.add_argument("--file", type=Path, required=True, help="a council CSV export to take readings from")
    ap.add_argument("--family", default="mcc_aq", choices=sorted(C.COLUMN_MAP), help="device type of --file")
    ap.add_argument("--day", help="local date in the file to replay (default: its first full day)")
    ap.add_argument("--speed", type=float, default=1.0, help="seconds between readings (default 1, minimum 1)")
    ap.add_argument("--limit", type=int, default=0, help="send at most this many readings (0 = the whole day)")
    ap.add_argument("--out-of-range-every", type=int, default=0,
                    help=f"replace the temperature of every Nth reading with {TEST_TEMPERATURE} (a TEST value)")
    ap.add_argument("--report", type=Path, help="also write a Markdown report (no secrets) to this path")
    args = ap.parse_args(argv)

    key = os.environ.get("SIM_DEVICE_KEY") or getpass.getpass(f"Device key for {args.device_id}: ")
    day, readings = day_readings(args.file, args.family, args.day, args.limit)
    headers = {"X-Device-Id": args.device_id, "X-Device-Key": key}
    bypass = os.environ.get("VERCEL_PROTECTION_BYPASS") or os.environ.get("VERCEL_AUTOMATION_BYPASS_SECRET")
    if bypass:   # Vercel "Protection Bypass for Automation" for protected Preview deployments
        headers["x-vercel-protection-bypass"] = bypass
    interval = max(args.speed, 1.0)   # at most one reading per second: timestamps are per second
    print(f"Replaying {len(readings)} readings from {args.file.name} ({day}) to {args.url} as {args.device_id}"
          + (" (protection bypass header set)" if bypass else ""))

    counts: dict[str, int] = {}
    codes: dict[int, int] = {}
    latencies: list[float] = []
    injected: list[dict] = []
    last_send: float | None = None
    last_stamp: str | None = None
    with httpx.Client(base_url=args.url, timeout=30) as client:
        for i, values in enumerate(readings, 1):
            # Each send at least `interval` after the PREVIOUS send, never "catching up" after a slow
            # request: two sends in one second would get the same per-second timestamp and the
            # second would be a duplicate (it happened after a 6.8 s cold start on 2026-10-31).
            if last_send is not None:
                wait = last_send + interval - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
            last_send = time.monotonic()
            test_value = bool(args.out_of_range_every) and i % args.out_of_range_every == 0 \
                and "temperature" in values
            if test_value:
                values = {**values, "temperature": TEST_TEMPERATURE}
            stamp = datetime.now(UTC).isoformat(timespec="seconds")
            while stamp == last_stamp:   # clock jitter: never two readings in the same second
                time.sleep(0.05)
                stamp = datetime.now(UTC).isoformat(timespec="seconds")
            last_stamp = stamp
            body = {"timestamp": stamp, **values}
            t0 = time.perf_counter()
            r = client.post("/api/ingest", json=body, headers=headers)
            latencies.append(time.perf_counter() - t0)
            codes[r.status_code] = codes.get(r.status_code, 0) + 1
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            status = data.get("status") or data.get("error", {}).get("code") or f"http_{r.status_code}"
            counts[status] = counts.get(status, 0) + 1
            extra = []
            if test_value:
                extra.append(f"TEST temperature={TEST_TEMPERATURE}")
                injected.append({"index": i, "field": "temperature", "value": TEST_TEMPERATURE,
                                 "http": r.status_code, "rejected": data.get("rejected") or []})
            if data.get("flags"):
                extra.append("flags=" + ",".join(data["flags"]))
            if data.get("rejected"):
                extra.append("rejected=" + ",".join(data["rejected"]))
            print(f"{i:4d}  {r.status_code}  {status:<16} {latencies[-1] * 1000:6.0f} ms  {' '.join(extra)}")
            if r.status_code in (401, 403):
                print("Stopping: the device was refused (check the device id, key and that it is active).")
                break
    del key, bypass, headers
    s = latency_summary(latencies)
    print(f"\nOutcomes: {counts}   HTTP: {codes}")
    if latencies:
        print(f"First (possibly cold) {_ms(s['cold_ms'])} ms; warm p50 {_ms(s['p50_ms'])} ms, "
              f"p95 {_ms(s['p95_ms'])} ms, p99 {_ms(s['p99_ms'])} ms, max {_ms(s['max_ms'])} ms")
    if args.report and latencies:
        write_report(args.report, {"when": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
                                   "host": urlparse(args.url).hostname, "device": args.device_id,
                                   "sent": len(latencies), "file": args.file.name, "day": day,
                                   "interval": interval}, s, counts, codes, injected)
        print(f"Report written to {args.report}")
    return 0 if counts.get("stored") else 1


if __name__ == "__main__":
    sys.exit(main())
