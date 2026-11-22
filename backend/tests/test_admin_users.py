"""User management (§4.5): create with a one-time temporary password, change role,
deactivate/reactivate, reset password and MFA; sessions end on every access change;
no self-service escalation or self-lockout (SEC-11); every action audited (SEC-12)."""
import pytest

from backend.app.passwords import verify_password
from backend.tests.conftest import STRONG_PASSWORD, admin_with_mfa, audit_actions, email_of, login, post, put

URL = "/api/admin/users"


@pytest.fixture
def admin(client, make_user, db_conn):
    admin_with_mfa(client, make_user, db_conn)
    return client


def _session_works(client, email, password=STRONG_PASSWORD):
    client.cookies.clear()
    return login(client, email, password)


def test_create_user_with_one_time_password(admin, db_conn, make_client):
    r = post(admin, URL, {"username": "new.analyst", "email": "New.Analyst@Example.org", "role_id": 2})
    assert r.status_code == 201
    body = r.json()
    temp = body["temporary_password"]
    assert len(temp) >= 20 and body["user"]["email"] == "new.analyst@example.org"
    assert body["user"]["role_name"] == "Environmental Analyst" and body["user"]["must_change_password"] is True
    row = db_conn.execute("SELECT password_hash FROM users WHERE username = 'new.analyst'").fetchone()
    assert row["password_hash"].startswith("$argon2id$") and verify_password(row["password_hash"], temp)
    assert temp not in admin.get(URL).text
    entry = audit_actions(db_conn, "user_created")[0]
    assert entry["username"] == "new.analyst" and temp not in str(entry)
    # the new user can log in, but must change the password first
    other = make_client()
    r = login(other, "new.analyst@example.org", temp)
    assert r.status_code == 200 and r.json()["next_step"] == "change_password"
    assert other.get("/api/meta").status_code == 403


@pytest.mark.parametrize("change", [{"email": "not-an-email"}, {"role_id": 4}, {"role_id": 0},
                                    {"username": "Has Space"}, {"username": "ab"},
                                    {"username": "x' OR '1'='1"}, {"password": "chosen-by-admin"}])
def test_invalid_create_rejected(admin, change):
    body = {"username": "valid.name", "email": "valid@example.org", "role_id": 2, **change}
    assert post(admin, URL, body).status_code == 422


def test_duplicate_email_and_username(admin, make_user, db_conn):
    existing = email_of(db_conn, make_user(role="analyst"))
    r = post(admin, URL, {"username": "someone.new", "email": existing.upper(), "role_id": 2})
    assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate_email"
    username = db_conn.execute("SELECT username FROM users WHERE email = ?", (existing,)).fetchone()[0]
    r = post(admin, URL, {"username": username, "email": "fresh@example.org", "role_id": 2})
    assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate_username"


def test_role_change_takes_effect_and_signs_the_user_out(admin, make_user, db_conn, make_client):
    """An old General User record (retired role, D-035) moved to Analyst."""
    uid = make_user(role="legacy_user")
    email = email_of(db_conn, uid)
    them = make_client()
    login(them, email)
    assert them.get("/api/auth/check?permission=view_quality").status_code == 403
    r = put(admin, f"{URL}/{uid}", {"role_id": 2})
    assert r.status_code == 200 and r.json()["user"]["role_name"] == "Environmental Analyst"
    assert them.get("/api/me").status_code == 401                      # old session ended
    login(them, email)
    assert them.get("/api/auth/check?permission=view_quality").status_code == 200
    assert audit_actions(db_conn, "user_updated")[0]["changes"] == {
        "role": {"from": "General User", "to": "Environmental Analyst"}}


def test_deactivate_and_reactivate(admin, make_user, db_conn, make_client):
    uid = make_user(role="analyst")
    email = email_of(db_conn, uid)
    them = make_client()
    login(them, email)
    assert put(admin, f"{URL}/{uid}", {"is_active": False}).json()["user"]["is_active"] is False
    assert them.get("/api/me").status_code == 401
    assert login(make_client(), email).status_code == 403             # deactivated accounts cannot log in
    put(admin, f"{URL}/{uid}", {"is_active": True})
    assert login(make_client(), email).status_code == 200


def test_reset_password_forces_change_and_unlocks(admin, make_user, db_conn, make_client):
    uid = make_user(role="analyst")
    email = email_of(db_conn, uid)
    db_conn.execute("UPDATE users SET failed_attempts = 5, locked_until = '2999-01-01T00:00:00.000Z' "
                    "WHERE user_id = ?", (uid,))
    db_conn.commit()
    assert next(u for u in admin.get(URL).json()["users"] if u["user_id"] == uid)["locked"] is True
    temp = post(admin, f"{URL}/{uid}/reset-password").json()["temporary_password"]
    assert login(make_client(), email, STRONG_PASSWORD).status_code == 401     # old password gone
    r = login(make_client(), email, temp)
    assert r.status_code == 200 and r.json()["next_step"] == "change_password"
    assert [a["target_user_id"] for a in audit_actions(db_conn, "user_password_reset")] == [uid]


def test_reset_mfa_removes_the_authenticator(admin, client, make_user, db_conn, make_client):
    other_admin = make_client()
    target = admin_with_mfa(other_admin, make_user, db_conn)
    r = post(admin, f"{URL}/{target}/reset-mfa")
    assert r.status_code == 200 and r.json()["user"]["mfa_enabled"] is False
    row = db_conn.execute("SELECT mfa_secret_encrypted, mfa_last_used_step FROM users WHERE user_id = ?",
                          (target,)).fetchone()
    assert row["mfa_secret_encrypted"] is None and row["mfa_last_used_step"] is None
    assert other_admin.get("/api/me").status_code == 401
    r = login(make_client(), email_of(db_conn, target))
    assert r.json()["next_step"] == "mfa_setup"                         # must enrol again
    assert audit_actions(db_conn, "user_mfa_reset")[0]["had_mfa"] is True


def test_admin_cannot_change_their_own_access(admin, db_conn):
    me = admin.get("/api/me").json()["user_id"]
    for call in (lambda: put(admin, f"{URL}/{me}", {"role_id": 2}),
                 lambda: put(admin, f"{URL}/{me}", {"is_active": False}),
                 lambda: post(admin, f"{URL}/{me}/reset-password"),
                 lambda: post(admin, f"{URL}/{me}/reset-mfa")):
        r = call()
        assert r.status_code == 409 and r.json()["error"]["code"] == "own_account"
    row = db_conn.execute("SELECT role_id, is_active, mfa_enabled FROM users WHERE user_id = ?", (me,)).fetchone()
    assert tuple(row) == (3, 1, 1)


def test_analyst_cannot_escalate_their_own_role(client, make_user, db_conn):
    """SEC-11: PUT /api/admin/users/{self} by an Analyst is refused and changes nothing."""
    uid = make_user(role="analyst")
    login(client, email_of(db_conn, uid))
    for body in ({"role_id": 3}, {"is_active": True}):
        assert put(client, f"{URL}/{uid}", body).status_code == 403
    assert post(client, URL, {"username": "sneaky", "email": "sneaky@example.org", "role_id": 3}).status_code == 403
    assert db_conn.execute("SELECT role_id FROM users WHERE user_id = ?", (uid,)).fetchone()[0] == 2
    assert db_conn.execute("SELECT COUNT(*) FROM users WHERE username = 'sneaky'").fetchone()[0] == 0


def test_retired_general_user_role_cannot_be_given(admin, make_user, db_conn):
    """D-035: two roles only. Role 1 stays in the roles table for old records, but the API
    refuses it for new accounts and role changes."""
    r = post(admin, URL, {"username": "old.role", "email": "old.role@example.org", "role_id": 1})
    assert r.status_code == 422
    uid = make_user(role="analyst")
    assert put(admin, f"{URL}/{uid}", {"role_id": 1}).status_code == 422
    assert db_conn.execute("SELECT role_id FROM users WHERE user_id = ?", (uid,)).fetchone()[0] == 2
    assert db_conn.execute("SELECT COUNT(*) FROM users WHERE username = 'old.role'").fetchone()[0] == 0
    assert db_conn.execute("SELECT role_name FROM roles WHERE role_id = 1").fetchone()[0] == "General User"


def test_list_never_exposes_secrets(admin, db_conn):
    text = admin.get(URL).text
    assert "argon2" not in text and "password_hash" not in text and "mfa_secret" not in text
    hashes = [r[0] for r in db_conn.execute("SELECT password_hash FROM users")]
    assert not any(h in text for h in hashes)


def test_validation_and_not_found(admin):
    assert put(admin, f"{URL}/999", {"role_id": 2}).status_code == 404
    assert put(admin, f"{URL}/1", {}).status_code == 422
    assert put(admin, f"{URL}/1", {"role_id": None}).status_code == 422
    assert put(admin, f"{URL}/1", {"password_hash": "x"}).status_code == 422
    assert post(admin, f"{URL}/999/reset-password").status_code == 404
