"""SEC-27 security logging without secrets."""
import logging

from backend.tests.conftest import STRONG_PASSWORD, email_of, login, post

NEW_PASSWORD = "Harbour-Signal-Pewter-93"


def test_password_never_logged(client, make_user, db_conn, caplog):
    caplog.set_level(logging.DEBUG)
    email = email_of(db_conn, make_user())
    login(client, email, "wrong-but-secret-xx")
    login(client, email)
    post(client, "/api/auth/change-password", {"current_password": STRONG_PASSWORD, "new_password": NEW_PASSWORD})
    tokens = [client.cookies.get("mem_access"), client.cookies.get("mem_refresh")]
    logged = "\n".join(r.getMessage() for r in caplog.records)
    stored = "\n".join(r["detail_json"] or "" for r in db_conn.execute("SELECT detail_json FROM audit_log"))
    for secret in ["wrong-but-secret-xx", STRONG_PASSWORD, NEW_PASSWORD, *tokens]:
        assert secret not in logged and secret not in stored


def test_failed_login_burst_flagged(client, db_conn):
    # 20 earlier failures inside the 10-minute window (from many IPs, below each IP's rate limit)
    db_conn.executemany("INSERT INTO audit_log (action, detail_json, ip_address) VALUES ('login_failed', '{}', ?)",
                        [(f"198.51.100.{i}",) for i in range(20)])
    db_conn.commit()
    login(client, "nobody@example.org", "wrong-password-xx")            # the 21st
    login(client, "nobody@example.org", "wrong-password-xx")            # flagged only once per window
    flagged = db_conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'suspicious_login_activity'").fetchone()[0]
    assert flagged == 1
