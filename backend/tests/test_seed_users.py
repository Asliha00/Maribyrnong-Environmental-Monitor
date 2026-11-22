"""backend/scripts/seed_users.py: two demo accounts (Analyst, Administrator; D-035), idempotent, policy enforced."""
import importlib.util
from pathlib import Path

import pytest

from backend.app import config as app_config

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "seed_users.py"
SEEDS = {"SEED_ANALYST_PASSWORD": "Velvet-Harbour-Prism-72",
         "SEED_ADMIN_PASSWORD": "Granite-Orbit-Meadow-19"}


@pytest.fixture
def seed(monkeypatch, sqlite_db):
    for k, v in SEEDS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("APP_DATABASE_URL", "")
    monkeypatch.setenv("SQLITE_PATH", str(sqlite_db))
    app_config.get_settings.cache_clear()
    spec = importlib.util.spec_from_file_location("seed_users", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module.main
    app_config.get_settings.cache_clear()


def test_creates_one_account_per_role(seed, db_conn, capsys):
    assert seed([]) == 0
    rows = db_conn.execute("SELECT username, role_id, must_change_password, password_hash FROM users "
                           "ORDER BY role_id").fetchall()
    assert [(r["username"], r["role_id"]) for r in rows] == [("demo_analyst", 2), ("demo_admin", 3)]
    assert all(r["password_hash"].startswith("$argon2id$") for r in rows)
    out = capsys.readouterr().out
    assert not any(v in out for v in SEEDS.values()), "seed passwords must never be printed"


def test_is_idempotent(seed, db_conn):
    seed([])
    assert seed([]) == 0
    assert db_conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2


def test_rejects_weak_seed_password(seed, monkeypatch, db_conn):
    monkeypatch.setenv("SEED_ADMIN_PASSWORD", "password")
    assert seed([]) == 1
    assert db_conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
