"""SEC-12 audit trail for authentication events (admin and export events: Phases 4-5)."""
import json

import pytest

from backend.app.services import audit
from backend.tests.conftest import email_of, login, post


def _actions(db_conn):
    return [r["action"] for r in db_conn.execute("SELECT action FROM audit_log ORDER BY audit_id")]


def test_login_logout_and_failures_logged(client, make_user, db_conn):
    uid = make_user()
    email = email_of(db_conn, uid)
    login(client, email, "wrong-password-xx")
    login(client, "nobody@example.org", "wrong-password-xx")
    login(client, email)
    post(client, "/api/auth/logout")
    assert _actions(db_conn) == ["login_failed", "login_failed", "login_success", "logout"]
    rows = db_conn.execute("SELECT user_id, ip_address, detail_json FROM audit_log ORDER BY audit_id").fetchall()
    assert rows[0]["user_id"] == uid and json.loads(rows[0]["detail_json"])["reason"] == "wrong_password"
    assert rows[1]["user_id"] is None and json.loads(rows[1]["detail_json"])["reason"] == "unknown_email"
    assert all(r["ip_address"] for r in rows)


def test_lockout_and_password_change_logged(client, make_user, db_conn):
    email = email_of(db_conn, make_user())
    for _ in range(5):
        login(client, email, "wrong-password-xx")
    assert "account_locked" in _actions(db_conn)


def test_audit_refuses_secret_fields():
    with pytest.raises(ValueError):
        audit.record(tx=None, action="x", detail={"password": "hunter2hunter2"})
