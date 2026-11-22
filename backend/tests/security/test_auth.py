"""SEC-04 password storage, SEC-05 password policy, SEC-06 brute-force/enumeration (UC1)."""
import time

from backend.app.passwords import hash_password, policy_violations, verify_password
from backend.tests.conftest import STRONG_PASSWORD, email_of, login, post


def _reset_rate_limit(db_conn):
    # Lets a test make more than 5 login attempts from one IP (SEC-23 is tested separately)
    db_conn.execute("DELETE FROM rate_limits")
    db_conn.commit()


# ---------- SEC-04 ----------
def test_password_is_hashed(client, make_user, db_conn):
    uid = make_user()
    stored = db_conn.execute("SELECT password_hash FROM users WHERE user_id = ?", (uid,)).fetchone()[0]
    assert STRONG_PASSWORD not in stored
    assert stored.startswith("$argon2id$")
    response = login(client, email_of(db_conn, uid))
    assert "password" not in response.text.lower() or "password_hash" not in response.text


def test_hash_uses_strong_params():
    h = hash_password("anything-long-enough")
    # argon2id, version 19, 64 MiB, 3 iterations, 4 lanes: above OWASP's argon2id minimum
    assert h.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    assert hash_password("anything-long-enough") != h, "each hash must use a fresh salt"
    assert verify_password(h, "anything-long-enough") and not verify_password(h, "wrong")


def test_login_response_never_contains_hash_or_password(client, make_user, db_conn):
    uid = make_user()
    body = login(client, email_of(db_conn, uid)).text
    assert "$argon2" not in body and STRONG_PASSWORD not in body


# ---------- SEC-05 ----------
def test_short_password_rejected():
    assert any("12 characters" in p for p in policy_violations("Sh0rt-pass!"))


def test_common_password_rejected():
    assert any("too common" in p for p in policy_violations("unbelievable"))   # 12 characters, on the bundled list
    assert policy_violations(STRONG_PASSWORD) == []


def test_password_containing_username_or_email_rejected():
    problems = policy_violations("my-name-is-jsmith-2026", username="jsmith", email="jsmith@example.org")
    assert any("username or email" in p for p in problems)


def test_first_login_forces_change(client, make_user, db_conn):
    uid = make_user(must_change=True)
    response = login(client, email_of(db_conn, uid))
    assert response.status_code == 200 and response.json()["next_step"] == "change_password"
    # Nothing else works until the password is changed
    blocked = client.get("/api/auth/check", params={"permission": "view_data"})
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "password_change_required"
    weak = post(client, "/api/auth/change-password", {"current_password": STRONG_PASSWORD, "new_password": "short"})
    assert weak.status_code == 400 and weak.json()["error"]["code"] == "weak_password"
    ok = post(client, "/api/auth/change-password",
              {"current_password": STRONG_PASSWORD, "new_password": "Harbour-Signal-Pewter-93"})
    assert ok.status_code == 200 and ok.json()["next_step"] == "done"
    assert client.get("/api/auth/check", params={"permission": "view_data"}).status_code == 200


def test_change_password_requires_current_password(client, make_user, db_conn):
    uid = make_user()
    login(client, email_of(db_conn, uid))
    r = post(client, "/api/auth/change-password",
             {"current_password": "not-my-password", "new_password": "Harbour-Signal-Pewter-93"})
    assert r.status_code == 400 and r.json()["error"]["message"] == "Your current password is incorrect."


# ---------- SEC-06 ----------
def test_lockout_after_5_failures(client, make_user, db_conn):
    email = email_of(db_conn, make_user())
    codes = [login(client, email, "wrong-password-xx").status_code for _ in range(5)]
    assert codes == [401, 401, 401, 401, 423]
    _reset_rate_limit(db_conn)
    locked = login(client, email)                       # even the right password is refused while locked
    assert locked.status_code == 423
    assert locked.json()["error"]["message"].startswith("Your account has been locked after 5 failed login attempts.")
    db_conn.execute("UPDATE users SET locked_until = '2000-01-01T00:00:00Z'")   # 15 minutes later
    db_conn.commit()
    assert login(client, email).status_code == 200


def test_unknown_email_same_response_as_wrong_password(client, make_user, db_conn):
    email = email_of(db_conn, make_user())
    t0 = time.perf_counter()
    wrong = login(client, email, "wrong-password-xx")
    t1 = time.perf_counter()
    unknown = login(client, "nobody@example.org", "wrong-password-xx")
    t2 = time.perf_counter()
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"] == "Invalid email or password"
    assert wrong.json()["error"]["code"] == unknown.json()["error"]["code"]
    # An unknown email still costs one argon2id verification (dummy hash), so timing does not
    # reveal whether the account exists. Loose bound: CI machines are noisy.
    assert (t2 - t1) > 0.4 * (t1 - t0)


def test_deactivated_account_message(client, make_user, db_conn):
    uid = make_user(active=False)
    r = login(client, email_of(db_conn, uid))
    assert r.status_code == 403
    assert r.json()["error"]["message"] == "Your account has been deactivated. Please contact your administrator."
