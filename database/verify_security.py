"""
Automated verification of the Neon database and raw-file archive security settings.

Run after database/01_schema.sql + 02_security.sql, and again before every submission:

    python database/verify_security.py

Reads from .env (or the environment):
    PIPELINE_DATABASE_URL   pipeline_user connection, direct host          (required)
    APP_DATABASE_URL        app_user connection, pooled host               (required)
    OWNER_DATABASE_URL      neondb_owner connection                        (optional: tests the
                            audit trigger blocks even the owner)
    BACKUP_DATABASE_URL     backup_user connection                         (optional: read-only check)
    BLOB_READ_WRITE_TOKEN   private Vercel Blob store token                (optional: proves the raw-file
                            archive cannot be read without credentials)

Writes docs/security/database_verification.md as evidence for the Technical
Implementation Document and exits non-zero if any check FAILS (usable in CI).
"""
from __future__ import annotations

import os
import subprocess
import sys
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "data_pipeline"))
import config  # noqa: E402,F401  (loads .env)
from db import InsecureConnectionError, validate_postgres_url  # noqa: E402

import psycopg  # noqa: E402

results: list[tuple[str, str, str, str]] = []


def record(sec_id: str, check: str, ok: bool | None, detail: str = ""):
    status = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
    results.append((sec_id, check, status, detail))
    print(f"[{status}] {sec_id:7s} {check}" + (f" - {detail}" if detail else ""))


def connect(url: str):
    conn = psycopg.connect(url, autocommit=True, prepare_threshold=None)
    conn.execute("SET search_path TO app")
    return conn


def attempt(conn, *statements) -> tuple[bool, str]:
    """Run statements inside a transaction that is ALWAYS rolled back.
    Returns (allowed, message). allowed=False means the database refused."""
    try:
        with conn.transaction():
            for sql in statements:
                conn.execute(sql)
            raise psycopg.Rollback()
    except psycopg.Error as e:
        return False, type(e).__name__
    return True, "statement succeeded"


def expect_denied(sec_id, desc, conn, *statements):
    allowed, msg = attempt(conn, *statements)
    record(sec_id, desc, not allowed, msg)


# Neon's own platform roles. Neon creates and holds their credentials; we cannot
# drop them without breaking the project, and they reach our database only through
# Neon's platform role neon_superuser (the provider trust boundary, SEC-17).
NEON_PLATFORM_ROLES = {"neon_superuser", "cloud_admin"}
# Neon-managed service roles, exempt ONLY while their access comes purely from
# membership of neon_superuser. neon_service was created with Neon Auth and stayed
# after Neon Auth was removed (DECISIONS.md D-017). Any grant we make to it directly
# turns it back into an intruder.
NEON_SERVICE_ROLES = {"neon_service"}


def neon_service_roles_ok(conn) -> set[str]:
    """Neon service roles that are members of neon_superuser and hold no direct grant
    on this database, schema app, or any table in app."""
    ok = set()
    for role in NEON_SERVICE_ROLES:
        member = conn.execute("SELECT pg_has_role(%s, 'neon_superuser', 'MEMBER') "
                              "FROM pg_roles WHERE rolname = %s", (role, role)).fetchone()
        direct = conn.execute(
            """SELECT count(*) FROM (
                 SELECT (aclexplode(datacl)).grantee FROM pg_database WHERE datname = current_database()
                 UNION ALL SELECT (aclexplode(nspacl)).grantee FROM pg_namespace WHERE nspname = 'app'
                 UNION ALL SELECT (aclexplode(c.relacl)).grantee FROM pg_class c
                           JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'app'
               ) g JOIN pg_roles r ON r.oid = g.grantee WHERE r.rolname = %s""", (role,)).fetchone()[0]
        if member and member[0] and direct == 0:
            ok.add(role)
    return ok


# app_user's table privileges exactly as granted in 02_security.sql (D-033). Any drift, in
# either direction, fails the check: a missing grant breaks the app, an extra one widens it.
APP_USER_GRANTS: dict[str, set[str]] = {
    "roles": {"SELECT"},
    "ingestion_runs": {"SELECT", "INSERT", "UPDATE"},
    "sensor_variables": {"SELECT", "INSERT", "UPDATE"},
    "readings": {"SELECT", "INSERT"},
    "error_log": {"SELECT", "INSERT"},
    "aggregates": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "exceedances": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "users": {"SELECT", "INSERT", "UPDATE"},
    "sensors": {"SELECT", "INSERT", "UPDATE"},
    "thresholds": {"SELECT", "INSERT", "UPDATE"},
    "reports": {"SELECT", "INSERT", "UPDATE"},
    "revoked_tokens": {"SELECT", "INSERT", "DELETE"},
    "rate_limits": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "audit_log": {"SELECT", "INSERT"},
    "threshold_history": {"SELECT", "INSERT"},
    "mfa_recovery_codes": {"SELECT", "INSERT"},   # + UPDATE of two columns only (below)
}
# Column-level UPDATE grants (has_table_privilege does not see these). Every other column
# of these tables must NOT be updatable: a recovery code's hash, owner and selector are fixed.
APP_USER_COLUMN_UPDATES: dict[str, set[str]] = {"mfa_recovery_codes": {"used_at", "revoked_at"}}
TABLE_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")


def grant_differences(actual: dict[str, set[str]], expected: dict[str, set[str]]) -> list[str]:
    """Human-readable differences between actual and expected table privileges."""
    out = []
    for table in sorted(set(actual) | set(expected)):
        extra = actual.get(table, set()) - expected.get(table, set())
        missing = expected.get(table, set()) - actual.get(table, set())
        out += [f"unexpected {p} on {table}" for p in sorted(extra)]
        out += [f"missing {p} on {table}" for p in sorted(missing)]
    return out


def app_user_grants(conn) -> dict[str, set[str]]:
    tables = [r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'app'").fetchall()]
    return {t: {p for p in TABLE_PRIVILEGES
                if conn.execute("SELECT has_table_privilege('app_user', %s, %s)", (f"app.{t}", p)).fetchone()[0]}
            for t in tables}


def app_user_column_updates(conn, table: str) -> set[str]:
    cols = [r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = 'app' AND table_name = %s",
        (table,)).fetchall()]
    return {c for c in cols
            if conn.execute("SELECT has_column_privilege('app_user', %s, %s, 'UPDATE')",
                            (f"app.{table}", c)).fetchone()[0]}


def find_intruders(candidates: list[str], allowed: set[str], service_roles_ok: set[str]) -> list[str]:
    """Roles that can connect or use schema app but are neither ours nor a Neon platform role."""
    return [r for r in candidates
            if r not in allowed and r not in NEON_PLATFORM_ROLES and r not in service_roles_ok]


def plaintext_refused(url: str) -> tuple[bool, str]:
    """Try the same credentials WITHOUT TLS. Neon (and our local test server) must refuse.
    This tests what an attacker would try, instead of trusting pg_stat_ssl, which behind
    Neon's proxy describes the proxy-to-compute hop rather than the client's connection."""
    parsed = urlparse(url)
    query = {k: v for k, v in parse_qs(parsed.query).items() if k not in ("sslmode", "channel_binding")}
    query["sslmode"] = ["disable"]
    insecure = urlunparse(parsed._replace(query=urlencode(query, doseq=True)))
    try:
        psycopg.connect(insecure, connect_timeout=10).close()
        return False, "server ACCEPTED an unencrypted connection"
    except psycopg.Error as e:
        return True, f"refused ({type(e).__name__})"


def http_status(url: str, headers: dict, data: bytes | None = None, method="GET") -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers=headers, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def main() -> int:
    pipe_url = os.environ.get("PIPELINE_DATABASE_URL", "")
    app_url = os.environ.get("APP_DATABASE_URL", "")
    if not pipe_url or not app_url:
        print("PIPELINE_DATABASE_URL and APP_DATABASE_URL must be set (see .env.example).")
        return 2

    # SEC-02: TLS enforced in configuration and actually negotiated
    for name, url in (("pipeline", pipe_url), ("app", app_url)):
        try:
            validate_postgres_url(url)
            record("SEC-02", f"{name} URL requires TLS and a non-default password", True)
        except InsecureConnectionError as e:
            record("SEC-02", f"{name} URL requires TLS and a non-default password", False, str(e))

    for name, url in (("pipeline", pipe_url), ("app", app_url)):
        ok, detail = plaintext_refused(url)
        record("SEC-02", f"database refuses an unencrypted {name} connection", ok, detail)

    pipe, app = connect(pipe_url), connect(app_url)

    # SEC-14: least privilege roles
    for name, conn in (("pipeline", pipe), ("app", app)):
        row = conn.execute("""SELECT current_user, rolsuper, rolcreaterole, rolcreatedb, rolbypassrls,
                                     COALESCE((SELECT pg_has_role(current_user, 'neon_superuser', 'MEMBER')
                                               WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'neon_superuser')), false)
                              FROM pg_roles WHERE rolname = current_user""").fetchone()
        user, *powers = row
        owner = conn.execute("SELECT nspowner::regrole::text FROM pg_namespace WHERE nspname = 'app'").fetchone()[0]
        record("SEC-14", f"{name} connects as a dedicated non-admin role ({user})",
               user not in ("postgres", "neondb_owner", owner) and not any(powers),
               f"super/createrole/createdb/bypassrls/neon_superuser = {powers}")
    expect_denied("SEC-14", "app_user cannot create tables", app, "CREATE TABLE app.sec_probe (x int)")
    expect_denied("SEC-14", "app_user cannot drop tables", app, "DROP TABLE app.readings")
    expect_denied("SEC-14", "app_user cannot alter tables", app, "ALTER TABLE app.users ADD COLUMN probe int")
    expect_denied("SEC-14", "pipeline_user cannot read users (password hashes)", pipe, "SELECT * FROM app.users LIMIT 1")
    expect_denied("SEC-14", "pipeline_user cannot read audit_log", pipe, "SELECT * FROM app.audit_log LIMIT 1")
    expect_denied("SEC-14", "pipeline_user cannot read 2FA recovery codes", pipe,
                  "SELECT * FROM app.mfa_recovery_codes LIMIT 1")

    # SEC-12: append-only / governance
    probe = "INSERT INTO app.audit_log (action, detail_json) VALUES ('security_verification_probe', '{}')"
    allowed, msg = attempt(app, probe)
    record("SEC-12", "app_user can append to audit_log", allowed, msg)
    expect_denied("SEC-12", "app_user cannot UPDATE audit_log", app, probe,
                  "UPDATE app.audit_log SET action = 'tampered'")
    expect_denied("SEC-12", "app_user cannot DELETE audit_log", app, "DELETE FROM app.audit_log")
    expect_denied("SEC-12", "app_user cannot UPDATE sensor readings", app, "UPDATE app.readings SET pm25 = 0")
    expect_denied("SEC-12", "app_user cannot DELETE sensor readings", app, "DELETE FROM app.readings")
    expect_denied("SEC-12", "app_user cannot DELETE users (deactivate only)", app, "DELETE FROM app.users")
    forbidden = [(t, p) for t in ("audit_log", "threshold_history", "readings") for p in ("UPDATE", "DELETE", "TRUNCATE")]
    granted = [f"{p} {t}" for t, p in forbidden
               if app.execute("SELECT has_table_privilege('app_user', %s, %s)", (f"app.{t}", p)).fetchone()[0]]
    record("SEC-12", "app_user holds no UPDATE/DELETE/TRUNCATE grants on audit_log, threshold_history, readings",
           not granted, f"unexpected grants: {granted}" if granted else "")
    drift = grant_differences(app_user_grants(app), APP_USER_GRANTS)
    record("SEC-14", "app_user table privileges match 02_security.sql exactly", not drift, "; ".join(drift))
    for table, expected_cols in APP_USER_COLUMN_UPDATES.items():
        cols = app_user_column_updates(app, table)
        record("SEC-14", f"app_user may UPDATE only {sorted(expected_cols)} on {table}", cols == expected_cols,
               f"updatable columns: {sorted(cols)}")
    temp, create = app.execute("SELECT has_database_privilege('app_user', current_database(), 'TEMP'), "
                               "has_database_privilege('app_user', current_database(), 'CREATE')").fetchone()
    record("SEC-14", "app_user may create temp tables (upload COPY) but no schemas", temp and not create,
           f"TEMP={temp} CREATE={create}")
    admin_url = os.environ.get("OWNER_DATABASE_URL") or os.environ.get("ADMIN_DATABASE_URL")
    if admin_url:
        admin = connect(admin_url)
        expect_denied("SEC-12", "even the owner role cannot UPDATE audit_log (trigger)", admin, probe,
                      "UPDATE app.audit_log SET action = 'tampered'")
        admin.close()
    else:
        record("SEC-12", "even the owner role cannot UPDATE audit_log (trigger)", None, "OWNER_DATABASE_URL not set")

    backup_url = os.environ.get("BACKUP_DATABASE_URL")
    if backup_url:
        bk = connect(backup_url)
        allowed, msg = attempt(bk, "SELECT count(*) FROM app.readings")
        record("SEC-18", "backup_user can read all app tables", allowed, msg)
        expect_denied("SEC-18", "backup_user is read-only (cannot INSERT)", bk, probe)
        expect_denied("SEC-18", "backup_user is read-only (cannot DELETE)", bk, "DELETE FROM app.readings")
        bk.close()
    else:
        record("SEC-18", "backup_user is read-only", None, "BACKUP_DATABASE_URL not set")

    # SEC-13: RLS everywhere, API roles locked out
    rows = app.execute("""SELECT c.relname, c.relrowsecurity FROM pg_class c
                          JOIN pg_namespace n ON n.oid = c.relnamespace
                          WHERE n.nspname = 'app' AND c.relkind = 'r'""").fetchall()
    no_rls = [r[0] for r in rows if not r[1]]
    record("SEC-13", f"row-level security enabled on all {len(rows)} app tables", not no_rls and len(rows) > 0,
           f"missing: {no_rls}" if no_rls else "")
    owner = app.execute("SELECT nspowner::regrole::text FROM pg_namespace WHERE nspname = 'app'").fetchone()[0]
    allowed_roles = {owner, "app_user", "pipeline_user", "backup_user"}
    candidates = [r[0] for r in app.execute(
        """SELECT rolname FROM pg_roles
           WHERE left(rolname, 3) <> 'pg_' AND NOT rolsuper
             AND (has_schema_privilege(oid, 'app', 'USAGE')
                  OR has_database_privilege(oid, current_database(), 'CONNECT'))""").fetchall()]
    intruders = find_intruders(candidates, allowed_roles, neon_service_roles_ok(app))
    record("SEC-13", "no role outside owner/app_user/pipeline_user/backup_user can connect or use schema app",
           not intruders, f"unexpected: {intruders}" if intruders else "")
    api_roles = [r[0] for r in app.execute(
        "SELECT rolname FROM pg_roles WHERE rolname IN ('authenticator', 'anonymous', 'authenticated', 'anon')").fetchall()]
    record("SEC-13", "Neon Data API is not enabled (no API roles present)", not api_roles,
           f"found {api_roles}: disable the Data API in the Neon Console" if api_roles else "")

    # SEC-15: the private raw-file archive cannot be read without credentials
    if config.BLOB_READ_WRITE_TOKEN:
        try:
            from vercel.blob import sync as blob
            first = next(iter(blob.query_blobs(prefix=config.RAW_PREFIX, page_size=1)), None)
        except Exception as e:  # noqa: BLE001 - report any SDK/network failure as a FAIL
            record("SEC-15", "raw-file archive reachable with the server token", False, type(e).__name__)
            first = None
        if first is not None:
            record("SEC-15", "raw-file archive is a PRIVATE Blob store", ".private.blob.vercel-storage.com" in first.url,
                   first.url.split("/")[2])
            code, _ = http_status(first.url, {})
            record("SEC-15", "anonymous request for an archived CSV is refused", code != 200, f"HTTP {code}")
            record("SEC-01", "Blob delivery URL uses HTTPS", first.url.startswith("https://"))
        elif first is None and not any(r[0] == "SEC-15" for r in results):
            record("SEC-15", "anonymous request for an archived CSV is refused", None, "archive is empty")
    else:
        record("SEC-15", "private raw-file archive checks", None, "BLOB_READ_WRITE_TOKEN not set")

    # SEC-16: secrets not committed
    gi = (ROOT / ".gitignore").read_text() if (ROOT / ".gitignore").exists() else ""
    record("SEC-16", ".env is listed in .gitignore", ".env" in gi.split())
    try:
        tracked = subprocess.run(["git", "ls-files", ".env"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        record("SEC-16", ".env is not tracked by git", tracked == "", tracked)
    except FileNotFoundError:
        record("SEC-16", ".env is not tracked by git", None, "git not installed")

    pipe.close()
    app.close()

    # Evidence file
    out = ROOT / "docs" / "security" / "database_verification.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    fails = sum(r[2] == "FAIL" for r in results)
    lines = ["# Database and storage security verification",
             f"_Run {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} by database/verify_security.py_", "",
             f"**{sum(r[2] == 'PASS' for r in results)} passed, {fails} failed, "
             f"{sum(r[2] == 'SKIP' for r in results)} skipped**", "",
             "| ID | Check | Result | Detail |", "|---|---|---|---|"]
    lines += [f"| {i} | {c} | {s} | {d} |" for i, c, s, d in results]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nEvidence written to {out.relative_to(ROOT)}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
