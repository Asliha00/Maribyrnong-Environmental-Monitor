"""SEC-07 single-use recovery codes for administrators (D-037)."""
import logging
import re
import sqlite3
from datetime import UTC, datetime

import pyotp

from backend.app.services import recovery_codes
from backend.tests.conftest import audit_actions, email_of, login, post

CODE_FORMAT = re.compile(r"^[0-9A-HJKMNP-TV-Z]{4}(-[0-9A-HJKMNP-TV-Z]{4}){3}$")
RECOVERY = "/api/auth/mfa/recovery"
CODES = "/api/auth/mfa/recovery-codes"


def _enrol(client, make_user, db_conn):
    """New admin, signed in and enrolled. Returns (user_id, email, totp_key, recovery codes)."""
    uid = make_user(role="admin")
    email = email_of(db_conn, uid)
    login(client, email)
    key = post(client, "/api/auth/mfa/setup").json()["manual_entry_key"]
    r = post(client, "/api/auth/mfa/verify", {"code": pyotp.TOTP(key).now()})
    assert r.status_code == 200
    return uid, email, key, r.json()["recovery_codes"]


def _signed_in_without_mfa(client, email):
    post(client, "/api/auth/logout")
    assert login(client, email).json()["next_step"] == "mfa_verify"


def test_enrolment_returns_ten_codes_once(client, make_user, db_conn):
    uid, email, key, codes = _enrol(client, make_user, db_conn)
    assert len(codes) == 10 and len(set(codes)) == 10
    assert all(CODE_FORMAT.match(c) for c in codes)
    # a later authenticator sign-in does not show codes again
    _signed_in_without_mfa(client, email)
    db_conn.execute("UPDATE users SET mfa_last_used_step = NULL WHERE user_id = ?", (uid,))
    db_conn.commit()
    r = post(client, "/api/auth/mfa/verify", {"code": pyotp.TOTP(key).now()})
    assert r.status_code == 200 and r.json()["recovery_codes"] is None


def test_codes_are_stored_hashed_and_never_logged_or_audited(client, make_user, db_conn, caplog):
    caplog.set_level(logging.DEBUG)
    uid, email, _, codes = _enrol(client, make_user, db_conn)
    _signed_in_without_mfa(client, email)
    assert post(client, RECOVERY, {"code": codes[0]}).status_code == 200
    rows = db_conn.execute("SELECT selector, code_hash FROM mfa_recovery_codes WHERE user_id = ?", (uid,)).fetchall()
    assert len(rows) == 10
    stored = " ".join(f"{r['selector']} {r['code_hash']}" for r in rows)
    assert all(r["code_hash"].startswith("$argon2id$") for r in rows)
    audit = " ".join(r[0] or "" for r in db_conn.execute("SELECT detail_json FROM audit_log").fetchall())
    for code in codes:
        secret = code.replace("-", "")[4:]
        assert secret not in stored and secret not in audit and secret not in caplog.text
        assert code not in caplog.text


def test_a_code_signs_in_once_and_gives_admin_access(client, make_user, db_conn):
    uid, email, _, codes = _enrol(client, make_user, db_conn)
    _signed_in_without_mfa(client, email)
    assert client.get("/api/auth/check", params={"permission": "manage_users"}).status_code == 403
    r = post(client, RECOVERY, {"code": codes[3]})
    assert r.status_code == 200
    assert r.json()["user"]["mfa_verified"] is True and r.json()["recovery_codes_remaining"] == 9
    assert client.get("/api/auth/check", params={"permission": "manage_users"}).status_code == 200
    assert audit_actions(db_conn, "mfa_recovery_used")[-1]["remaining"] == 9
    # the same code never works again
    _signed_in_without_mfa(client, email)
    r = post(client, RECOVERY, {"code": codes[3]})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_recovery_code"
    assert len(audit_actions(db_conn, "mfa_recovery_failed")) == 1


def test_code_entry_ignores_case_spaces_and_hyphens(client, make_user, db_conn):
    _, email, _, codes = _enrol(client, make_user, db_conn)
    _signed_in_without_mfa(client, email)
    typed = " " + codes[0].replace("-", " ").lower() + " "
    assert post(client, RECOVERY, {"code": typed}).status_code == 200


def test_wrong_and_malformed_codes_are_rejected(client, make_user, db_conn):
    _, email, _, codes = _enrol(client, make_user, db_conn)
    _signed_in_without_mfa(client, email)
    selector = codes[0][:4]
    for bad in (f"{selector}-2222-2222-2222", "not-a-code", "UUUU-UUUU-UUUU-UUUU", codes[0][:-1]):
        r = post(client, RECOVERY, {"code": bad})
        assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_recovery_code", bad
    assert post(client, RECOVERY, {"code": "x" * 33}).status_code == 422
    assert client.get("/api/auth/check", params={"permission": "manage_users"}).status_code == 403


def test_refused_before_the_password_step_and_before_enrolment(client, make_user, db_conn):
    assert post(client, RECOVERY, {"code": "2222-2222-2222-2222"}).status_code in (401, 403)   # no session
    login(client, email_of(db_conn, make_user(role="admin")))                          # admin, no 2FA yet
    r = post(client, RECOVERY, {"code": "2222-2222-2222-2222"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "mfa_not_set_up"


def test_recovery_and_authenticator_share_one_rate_limit(client, make_user, db_conn):
    _, email, key, codes = _enrol(client, make_user, db_conn)    # 1 hit (the enrolment code)
    _signed_in_without_mfa(client, email)
    wrong = "000000" if pyotp.TOTP(key).now() != "000000" else "111111"
    for _ in range(2):
        assert post(client, "/api/auth/mfa/verify", {"code": wrong}).status_code == 400
    for _ in range(2):
        assert post(client, RECOVERY, {"code": "2222-2222-2222-2222"}).status_code == 400
    r = post(client, RECOVERY, {"code": codes[0]})                 # 6th try this minute: blocked
    assert r.status_code == 429 and "Retry-After" in r.headers
    assert client.get("/api/auth/check", params={"permission": "manage_users"}).status_code == 403


def test_new_set_cancels_the_old_one(client, make_user, db_conn):
    _, email, _, old = _enrol(client, make_user, db_conn)
    r = post(client, CODES)
    assert r.status_code == 200
    new = r.json()["recovery_codes"]
    assert len(new) == 10 and not set(new) & set(old)
    entry = audit_actions(db_conn, "mfa_recovery_codes_generated")[-1]
    assert (entry["count"], entry["cancelled"]) == (10, 10)
    _signed_in_without_mfa(client, email)
    assert post(client, RECOVERY, {"code": old[0]}).status_code == 400
    assert post(client, RECOVERY, {"code": new[0]}).status_code == 200


def test_new_codes_and_status_need_a_session_that_passed_2fa(client, make_user, db_conn):
    _, email, _, _ = _enrol(client, make_user, db_conn)
    _signed_in_without_mfa(client, email)                          # password only
    for r in (post(client, CODES), client.get(CODES)):
        assert r.status_code == 403 and r.json()["error"]["code"] == "mfa_required"
    analyst = make_user(role="analyst")
    post(client, "/api/auth/logout")
    login(client, email_of(db_conn, analyst))
    assert post(client, CODES).status_code == 403


def test_status_counts_unused_codes_and_warns_when_low(client, make_user, db_conn):
    _, email, _, codes = _enrol(client, make_user, db_conn)
    assert client.get(CODES).json() == {"remaining": 10, "low": False}
    _signed_in_without_mfa(client, email)
    assert post(client, RECOVERY, {"code": codes[0]}).status_code == 200
    # six more used (directly: the login and 2FA rate limits allow only 5 tries a minute)
    db_conn.execute("UPDATE mfa_recovery_codes SET used_at = '2026-01-01T00:00:00.000Z' WHERE code_id IN "
                    "(SELECT code_id FROM mfa_recovery_codes WHERE used_at IS NULL LIMIT 6)")
    db_conn.commit()
    assert client.get(CODES).json() == {"remaining": 3, "low": True}


def test_reset_2fa_cancels_the_codes(client, make_user, db_conn, make_client):
    target, _, _, codes = _enrol(make_client(), make_user, db_conn)
    _enrol(client, make_user, db_conn)                              # the admin doing the reset
    r = post(client, f"/api/admin/users/{target}/reset-mfa")
    assert r.status_code == 200
    left = db_conn.execute("SELECT COUNT(*) FROM mfa_recovery_codes WHERE user_id = ? AND revoked_at IS NULL",
                           (target,)).fetchone()[0]
    assert left == 0
    assert audit_actions(db_conn, "user_mfa_reset")[-1]["recovery_codes_cancelled"] == 10


# ---------- service-level rules ----------
def test_alphabet_has_no_look_alikes_and_60_bit_secrets():
    assert len(set(recovery_codes.ALPHABET)) == 32 and not set("ILOU") & set(recovery_codes.ALPHABET)
    assert recovery_codes.SECRET_LEN * 5 >= 60
    assert recovery_codes.normalise("abcd-efgh-jkmn-pqrs") == "ABCDEFGHJKMNPQRS"
    assert recovery_codes.normalise("ABCD-EFGH-JKMN-PQRO") == "ABCDEFGHJKMNPQR0"   # typed O read as 0
    assert recovery_codes.normalise("ABCD-EFGH-JKMN-PQRU") is None                 # U is never used
    assert recovery_codes.normalise("ABCD") is None


def test_a_code_used_concurrently_is_accepted_only_once(make_settings, make_user, sqlite_db, monkeypatch):
    """Two sign-ins racing with the same code: the second one's conditional UPDATE marks nothing."""
    from backend.app.db import Database

    db = Database(make_settings())
    uid = make_user(role="admin")
    now = datetime.now(UTC)
    with db.transaction() as tx:
        code = recovery_codes.replace_set(tx, uid, now)[0]

    real_verify = recovery_codes.verify_password

    def verify_then_lose_the_race(hashed, secret):
        ok = real_verify(hashed, secret)
        other = sqlite3.connect(sqlite_db)                        # the other request wins first
        other.execute("UPDATE mfa_recovery_codes SET used_at = ? WHERE user_id = ? AND used_at IS NULL",
                      ("2026-01-01T00:00:00.000Z", uid))
        other.commit()
        other.close()
        return ok

    monkeypatch.setattr(recovery_codes, "verify_password", verify_then_lose_the_race)
    with db.transaction() as tx:
        assert recovery_codes.consume(tx, uid, code, now) is False
