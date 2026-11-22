"""SEC-07 TOTP MFA for administrators."""
import time

import pyotp
from cryptography.fernet import Fernet

from backend.app.services import mfa
from backend.tests.conftest import TEST_ENV, email_of, login, post


def _enrol(client):
    setup = post(client, "/api/auth/mfa/setup")
    assert setup.status_code == 200
    return setup.json()["manual_entry_key"]


def test_admin_without_mfa_gets_403_on_admin_routes(client, make_user, db_conn):
    r = login(client, email_of(db_conn, make_user(role="admin")))
    assert r.json()["next_step"] == "mfa_setup"
    check = client.get("/api/auth/check", params={"permission": "manage_users"})
    assert check.status_code == 403 and check.json()["error"]["code"] == "mfa_required"
    # non-admin permissions still work for an admin without MFA
    assert client.get("/api/auth/check", params={"permission": "view_data"}).status_code == 200


def test_admin_with_mfa_gets_admin_access(client, make_user, db_conn):
    login(client, email_of(db_conn, make_user(role="admin")))
    key = _enrol(client)
    r = post(client, "/api/auth/mfa/verify", {"code": pyotp.TOTP(key).now()})
    assert r.status_code == 200 and r.json()["user"]["mfa_verified"] is True
    assert client.get("/api/auth/check", params={"permission": "manage_users"}).status_code == 200


def test_enrolled_admin_must_verify_each_login(client, make_user, db_conn):
    email = email_of(db_conn, make_user(role="admin"))
    login(client, email)
    key = _enrol(client)
    post(client, "/api/auth/mfa/verify", {"code": pyotp.TOTP(key).now()})
    post(client, "/api/auth/logout")
    r = login(client, email)
    assert r.json()["next_step"] == "mfa_verify"
    assert client.get("/api/auth/check", params={"permission": "manage_users"}).status_code == 403


def test_wrong_code_rejected(client, make_user, db_conn):
    login(client, email_of(db_conn, make_user(role="admin")))
    key = _enrol(client)
    wrong = "000000" if pyotp.TOTP(key).now() != "000000" else "111111"
    r = post(client, "/api/auth/mfa/verify", {"code": wrong})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_mfa_code"
    assert post(client, "/api/auth/mfa/verify", {"code": "12ab56"}).status_code == 422


def test_code_reuse_rejected(client, make_user, db_conn):
    email = email_of(db_conn, make_user(role="admin"))
    login(client, email)
    key = _enrol(client)
    code = pyotp.TOTP(key).now()
    assert post(client, "/api/auth/mfa/verify", {"code": code}).status_code == 200
    post(client, "/api/auth/logout")
    login(client, email)
    replay = post(client, "/api/auth/mfa/verify", {"code": code})   # same code, same 30 s window
    assert replay.status_code == 400


def test_matching_step_rules():
    key = pyotp.random_base32()
    now = time.time()
    step = int(now // 30)
    assert mfa.matching_step(key, pyotp.TOTP(key).at(now), None, now) == step
    assert mfa.matching_step(key, pyotp.TOTP(key).at(now - 30), None, now) == step - 1   # clock drift
    assert mfa.matching_step(key, pyotp.TOTP(key).at(now - 90), None, now) is None       # too old
    assert mfa.matching_step(key, pyotp.TOTP(key).at(now), step, now) is None            # already used


def test_secret_encrypted_at_rest(client, make_user, db_conn):
    uid = make_user(role="admin")
    login(client, email_of(db_conn, uid))
    key = _enrol(client)
    stored = db_conn.execute("SELECT mfa_secret_encrypted FROM users WHERE user_id = ?", (uid,)).fetchone()[0]
    assert key not in stored and stored.startswith("gAAAA")           # Fernet token
    assert Fernet(TEST_ENV["MFA_ENCRYPTION_KEY"].encode()).decrypt(stored.encode()).decode() == key


def test_key_rotation_keeps_old_secrets_readable():
    old_key, new_key = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    token = mfa.encrypt_secret(old_key, "JBSWY3DPEHPK3PXP")
    assert mfa.decrypt_secret(f"{new_key},{old_key}", token) == "JBSWY3DPEHPK3PXP"


def test_setup_refused_when_already_enabled(client, make_user, db_conn):
    login(client, email_of(db_conn, make_user(role="admin")))
    key = _enrol(client)
    post(client, "/api/auth/mfa/verify", {"code": pyotp.TOTP(key).now()})
    again = post(client, "/api/auth/mfa/setup")
    assert again.status_code == 409   # cannot silently replace an enrolled authenticator


def test_authenticator_label_names_the_environment(monkeypatch):
    """Production and Preview have separate demo admins with the same email: their entries in
    an authenticator app must not look identical (a real mix-up, 2026-10-30)."""
    from urllib.parse import unquote

    from backend.app.services import mfa

    assert mfa.issuer_name("production") == "Maribyrnong Environmental Monitor"
    assert mfa.issuer_name("preview") == "Maribyrnong Monitor (Preview)"
    assert mfa.issuer_name("development") == "Maribyrnong Monitor (Development)"
    monkeypatch.delenv("VERCEL_ENV", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert mfa.issuer_name() == "Maribyrnong Environmental Monitor"   # unknown: never mislabel production
    monkeypatch.setenv("VERCEL_ENV", "preview")
    uri, _ = mfa.provisioning(mfa.new_secret(), "demo.admin@example.org")
    assert "issuer=Maribyrnong Monitor (Preview)" in unquote(uri)
