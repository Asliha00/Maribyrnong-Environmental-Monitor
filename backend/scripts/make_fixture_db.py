"""
Build a small, SYNTHETIC SQLite database for browser tests and CI (no council data).

    python backend/scripts/make_fixture_db.py e2e/.fixture.db

Everything here is invented and deterministic: four sensors (one with an XSS payload as
its name, for SEC-22), a year of hourly/daily/monthly aggregates with smooth seasonal and
daily cycles over the same dates as the real data, raw readings for the last week, the
thresholds, a few exceedances, and the three demo users with passwords from
SEED_ANALYST_PASSWORD / SEED_ADMIN_PASSWORD.
It must never be used as, or mixed with, real data.
"""
from __future__ import annotations

import math
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.passwords import hash_password, policy_violations  # noqa: E402
from backend.app.services import mfa  # noqa: E402

TZ = ZoneInfo("Australia/Melbourne")
FIRST_DAY, LAST_DAY = date(2025, 2, 16), date(2026, 2, 16)
XSS_NAME = '<img src=x onerror="window.__xss=1"><script>window.__xss=1</script> Fixture Kiosk'

# id, code, name, family, land use, verified, lat, lon, interval (min), variables
SENSORS = [
    (1, "FX-TR", "Fixture Transport Hub", "mcc_aq", "Transport corridor", 1, -37.801, 144.889, 10,
     ["temperature_c", "humidity_pct", "pm25", "pm10", "co_ppb"]),
    (2, "FX-PK", "Fixture Riverside Park", "libelium", "Parkland", 0, -37.795, 144.903, 15,
     ["temperature_c", "humidity_pct", "pm25"]),
    (3, "FX-RS", "Fixture Residential Street", "libelium", "Residential", 0, -37.809, 144.877, 15,
     ["temperature_c", "pm25"]),
    (4, "FX-XS", XSS_NAME, "lora_r270", "Commercial", 0, -37.799, 144.899, 15, ["temperature_c"]),
]
UNITS = {"temperature_c": "°C", "humidity_pct": "%", "pm25": "µg/m³", "pm10": "µg/m³", "co_ppb": "ppb"}
THRESHOLDS = [(1, "pm25", "day", ">", 25.0, "PM2.5 24-hour standard", "NEPM (Ambient Air Quality) 24-hr PM2.5"),
              (2, "pm10", "day", ">", 50.0, "PM10 24-hour standard", "NEPM (Ambient Air Quality) 24-hr PM10"),
              (3, "temperature_c", "day_max", ">=", 35.0, "Hot day (max >= 35°C)", "Fixture"),
              (4, "temperature_c", "day_max", ">=", 40.0, "Extreme heat day (max >= 40°C)", "Fixture")]


def season_of(month: int) -> str:
    return {12: "Summer", 1: "Summer", 2: "Summer", 3: "Autumn", 4: "Autumn", 5: "Autumn",
            6: "Winter", 7: "Winter", 8: "Winter"}.get(month, "Spring")


def value(variable: str, sensor_id: int, moment: datetime) -> float:
    """Smooth synthetic signal: a seasonal cycle (warm in January) plus a daily cycle."""
    doy = moment.timetuple().tm_yday
    seasonal = math.cos(2 * math.pi * (doy - 15) / 365.25)          # +1 mid-January, -1 mid-July
    daily = math.sin(2 * math.pi * (moment.hour - 9) / 24)           # peak mid-afternoon
    if variable == "temperature_c":
        return 15 + 7 * seasonal + 5 * daily + {1: 1.5, 2: -1.0, 3: 0.5, 4: 1.0}[sensor_id]
    if variable == "humidity_pct":
        return 65 - 10 * seasonal - 12 * daily
    if variable == "pm25":
        return 7 + 2 * math.sin(2 * math.pi * doy / 30) + {1: 3, 2: 0, 3: 1}.get(sensor_id, 0)
    if variable == "pm10":
        return 15 + 4 * math.sin(2 * math.pi * doy / 30)
    return 300 + 80 * daily                                          # co_ppb


def coverage(sensor_id: int, day: date) -> float:
    """Share of expected readings received: FX-RS has a 40% month (invalid buckets) in July."""
    return 0.4 if sensor_id == 3 and day.month == 7 else 1.0


def build(path: Path) -> None:
    passwords = {v: os.environ.get(v, "") for v in ("SEED_ANALYST_PASSWORD", "SEED_ADMIN_PASSWORD")}
    for var, pw in passwords.items():
        if not pw or policy_violations(pw):
            raise SystemExit(f"{var} must be set to a password that meets the policy (12+ characters, not common)")
    if path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript((ROOT / "data_pipeline" / "schema_sqlite.sql").read_text(encoding="utf-8"))

    conn.executemany("INSERT INTO sensors (sensor_id, sensor_code, sensor_name, device_family, land_use, "
                     "location_verified, latitude, longitude, notes, first_reading_utc, last_reading_utc, "
                     "sensitive_receptor) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'SYNTHETIC FIXTURE', ?, ?, ?)",
                     [(s[0], s[1], s[2], s[3], s[4], s[5], s[6], s[7], "2025-02-15T13:00:00Z", "2026-02-16T12:45:00Z",
                       int(s[1] == "FX-RS")) for s in SENSORS])   # FX-RS stands in for a childcare centre
    conn.executemany("INSERT INTO sensor_variables (sensor_id, variable, unit, raw_column) VALUES (?, ?, ?, ?)",
                     [(s[0], v, UNITS[v], v) for s in SENSORS for v in s[9]])

    hourly, daily, monthly = [], defaultdict(list), defaultdict(list)
    day = FIRST_DAY
    while day <= LAST_DAY:
        for s in SENSORS:
            sid, interval, variables = s[0], s[8], s[9]
            expected = 60 // interval
            n = max(1, round(expected * coverage(sid, day)))
            for hour in range(24):
                moment = datetime(day.year, day.month, day.day, hour, tzinfo=TZ)
                comp = round(100 * n / expected, 1)
                for v in variables:
                    mean = round(value(v, sid, moment), 3)
                    row = (sid, "hour", f"{day.isoformat()} {hour:02d}:00", season_of(day.month), v,
                           mean, round(mean - 0.4, 3), round(mean + 0.4, 3), n, comp, int(comp >= 75))
                    hourly.append(row)
                    daily[(sid, day.isoformat(), v, interval)].append(row)
                    monthly[(sid, day.isoformat()[:7], v, interval)].append(row)
        day += timedelta(days=1)

    def roll(rows, expected_n):
        n = sum(r[8] for r in rows)
        mean = round(sum(r[5] * r[8] for r in rows) / n, 3)
        comp = round(min(100.0, 100 * n / expected_n), 1)
        return mean, min(r[6] for r in rows), max(r[7] for r in rows), n, comp, int(comp >= 75)

    rows = [r + ("all",) for r in hourly]
    for (sid, d, v, interval), group in daily.items():
        stats = roll(group, 1440 // interval)
        rows.append((sid, "day", d, season_of(int(d[5:7])), v) + stats + ("all",))
    for (sid, m, v, interval), group in monthly.items():
        y, mo = int(m[:4]), int(m[5:7])
        days_in_month = (date(y + (mo == 12), mo % 12 + 1, 1) - date(y, mo, 1)).days
        stats = roll(group, days_in_month * 1440 // interval)
        rows.append((sid, "month", m, season_of(mo), v) + stats + ("all",))
    conn.executemany("INSERT INTO aggregates (sensor_id, period, bucket_start_local, season, variable, mean, min, "
                     "max, n, completeness_pct, is_valid, qc_mode) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)

    # Raw readings for the last 7 days (raw view; latest values for the map). One flagged spike.
    raw = []
    start = datetime(2026, 2, 10, tzinfo=TZ)
    for s in SENSORS:
        sid, interval, variables = s[0], s[8], s[9]
        moment = start
        while moment < datetime(2026, 2, 17, tzinfo=TZ):
            vals = {v: round(value(v, sid, moment), 2) for v in variables}
            flags = None
            if sid == 1 and moment == datetime(2026, 2, 12, 14, 0, tzinfo=TZ):
                vals["pm25"], flags = 180.0, "pm25_spike"
            utc = moment.astimezone(UTC)
            raw.append((sid, utc.strftime("%Y-%m-%dT%H:%M:%SZ"), moment.strftime("%Y-%m-%dT%H:%M:%S%z"),
                        vals.get("temperature_c"), vals.get("humidity_pct"), vals.get("pm25"), vals.get("pm10"),
                        vals.get("co_ppb"), flags))
            moment += timedelta(minutes=interval)
    conn.executemany("INSERT INTO readings (sensor_id, ts_utc, ts_local, temperature_c, humidity_pct, pm25, pm10, "
                     "co_ppb, qc_flags) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", raw)

    conn.executemany("INSERT INTO thresholds (threshold_id, variable, period, operator, value, label, source) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?)", THRESHOLDS)
    conn.executemany("INSERT INTO exceedances (sensor_id, threshold_id, date_local, observed_value, completeness_pct) "
                     "VALUES (?, ?, ?, ?, ?)",
                     [(1, 1, "2026-01-25", 31.2, 100.0), (1, 3, "2026-01-28", 36.4, 100.0),
                      (2, 3, "2026-01-28", 35.1, 100.0), (4, 4, "2026-01-29", 40.3, 100.0)])
    # Two roles (D-035), plus a DEACTIVATED analyst so the browser tests can check that a
    # deactivated account cannot log in (SEC-12).
    users = [("demo_analyst", "demo.analyst@example.org", 2, passwords["SEED_ANALYST_PASSWORD"], 1),
             ("demo_admin", "demo.admin@example.org", 3, passwords["SEED_ADMIN_PASSWORD"], 1),
             ("fixture_inactive", "fixture.inactive@example.org", 2, passwords["SEED_ANALYST_PASSWORD"], 0)]
    conn.executemany("INSERT INTO users (username, email, password_hash, role_id, must_change_password, is_active) "
                     "VALUES (?, ?, ?, ?, 0, ?)", [(u, e, hash_password(p), r, a) for u, e, r, p, a in users])
    # A second administrator with MFA already enrolled, for the admin browser tests. Its TOTP
    # secret is fresh per build and written next to the database (git-ignored), never committed.
    key = os.environ.get("MFA_ENCRYPTION_KEY", "")
    if key:
        secret = mfa.new_secret()
        conn.execute("INSERT INTO users (username, email, password_hash, role_id, must_change_password, mfa_enabled, "
                     "mfa_secret_encrypted) VALUES ('e2e_admin', 'e2e.admin@example.org', ?, 3, 0, 1, ?)",
                     (hash_password(passwords["SEED_ADMIN_PASSWORD"]), mfa.encrypt_secret(key, secret)))
        path.with_name(path.name + ".totp").write_text(secret, encoding="utf-8")
    conn.commit()
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: S608 - fixed table names
              for t in ("sensors", "aggregates", "readings", "exceedances", "users")}
    conn.close()
    print(f"fixture database {path}: {counts}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    build(Path(sys.argv[1]))
