"""
Shared fixtures. Tests never read the developer's .env: every setting is given
explicitly, and the database is a fresh SQLite file built from schema_sqlite.sql.
"""
from __future__ import annotations

import functools
import os
import sqlite3
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]

# Importing backend.app.main builds a module-level app from the environment, so
# make the import-time environment safe before anything imports it.
TEST_ENV = {
    "ENVIRONMENT": "test",
    "JWT_SECRET": "test-only-jwt-secret-" + "x" * 32,
    "MFA_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    "APP_DATABASE_URL": "",
}
os.environ.update(TEST_ENV)


@pytest.fixture(autouse=True)
def frozen_rate_window(monkeypatch):
    """Rate limits count per fixed window (one minute for logins). Freeze the limiter's clock
    so a test's requests never straddle a window boundary on a slow machine (a CI flake seen
    2026-10-29). Each test has a fresh database, so counters start at zero anyway; tests that
    pass `now=` explicitly are unaffected."""
    from datetime import UTC, datetime

    from backend.app.services import rate_limit

    frozen = datetime(2026, 1, 1, 0, 0, 30, tzinfo=UTC)

    class FrozenClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen if tz else frozen.replace(tzinfo=None)

    monkeypatch.setattr(rate_limit, "datetime", FrozenClock)


@pytest.fixture
def sqlite_db(tmp_path: Path) -> Path:
    """An empty database with the production schema (SQLite copy)."""
    path = tmp_path / "test.db"
    conn = sqlite3.connect(path)
    conn.executescript((ROOT / "data_pipeline" / "schema_sqlite.sql").read_text(encoding="utf-8"))
    conn.close()
    return path


@pytest.fixture
def make_settings(sqlite_db: Path):
    """Factory for Settings that ignores .env; override any field by keyword."""
    from backend.app.config import Settings

    def _make(**overrides):
        values = {
            "environment": "test",
            "jwt_secret": TEST_ENV["JWT_SECRET"],
            "mfa_encryption_key": TEST_ENV["MFA_ENCRYPTION_KEY"],
            "app_database_url": "",
            "sqlite_path": sqlite_db,
            **overrides,
        }
        return Settings(_env_file=None, **values)

    return _make


@pytest.fixture
def make_client(make_settings):
    """Factory for a TestClient around a freshly built app."""
    from backend.app.main import create_app

    def _make(**overrides) -> TestClient:
        # https so Secure cookies are stored and sent, as in production
        return TestClient(create_app(make_settings(**overrides)), base_url="https://testserver")

    return _make


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


# ---------------------------------------------------------------- Phase 1 helpers
# The two roles (D-035); "legacy_user" is the retired General User role, kept for old records.
ROLE_IDS = {"legacy_user": 1, "analyst": 2, "admin": 3}
STRONG_PASSWORD = "Tram-Lantern-Quartz-58"


@functools.lru_cache
def _hash(password: str) -> str:
    """Real argon2id hashes, computed once per password to keep the suite fast."""
    from backend.app.passwords import hash_password

    return hash_password(password)


@pytest.fixture
def db_conn(sqlite_db: Path):
    """Direct connection to the test database, for arranging and inspecting state."""
    conn = sqlite3.connect(sqlite_db)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def make_user(db_conn):
    """Insert a user directly. Returns its user_id."""
    counter = iter(range(1, 1000))

    def _make(role: str = "analyst", email: str | None = None, password: str = STRONG_PASSWORD,
              must_change: bool = False, active: bool = True) -> int:
        n = next(counter)
        email = email or f"{role}{n}@example.org"
        cur = db_conn.execute(
            "INSERT INTO users (username, email, password_hash, role_id, must_change_password, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (f"{role}_{n}", email, _hash(password), ROLE_IDS[role], int(must_change), int(active)))
        db_conn.commit()
        return cur.lastrowid

    return _make


def csrf_headers(client: TestClient) -> dict[str, str]:
    """The double-submit header a real browser page would send (SEC-09)."""
    return {"X-CSRF-Token": client.cookies.get("mem_csrf") or ""}


def login(client: TestClient, email: str, password: str = STRONG_PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def post(client: TestClient, url: str, json: dict | None = None):
    """POST with the CSRF header, like the frontend's API client."""
    return client.post(url, json=json, headers=csrf_headers(client))


def email_of(db_conn, user_id: int) -> str:
    return db_conn.execute("SELECT email FROM users WHERE user_id = ?", (user_id,)).fetchone()["email"]


def admin_with_mfa(client: TestClient, make_user, db_conn) -> int:
    """Log `client` in as a new administrator whose session passed TOTP. Returns the user id."""
    import pyotp

    user_id = make_user(role="admin")
    assert login(client, email_of(db_conn, user_id)).status_code == 200
    key = post(client, "/api/auth/mfa/setup").json()["manual_entry_key"]
    assert post(client, "/api/auth/mfa/verify", {"code": pyotp.TOTP(key).now()}).status_code == 200
    return user_id


def put(client: TestClient, url: str, json: dict | None = None):
    return client.put(url, json=json, headers=csrf_headers(client))


def delete(client: TestClient, url: str):
    return client.delete(url, headers=csrf_headers(client))


def audit_actions(db_conn, action: str) -> list[dict]:
    """Audit entries for one action, oldest first, as their detail dicts (+ `_user_id`)."""
    import json

    rows = db_conn.execute("SELECT user_id, detail_json FROM audit_log WHERE action = ? ORDER BY audit_id",
                           (action,)).fetchall()
    return [json.loads(r["detail_json"]) | {"_user_id": r["user_id"]} for r in rows]
