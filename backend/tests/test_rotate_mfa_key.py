"""MFA key rotation (SEC-07, docs/security/secret_rotation.md): every stored TOTP secret ends up
under the newest key, nothing changes if any secret is unreadable, logins keep working."""
import pyotp
import pytest
from cryptography.fernet import Fernet

from backend.app.db import Database
from backend.app.services import mfa
from backend.scripts.rotate_mfa_key import rotate
from backend.tests.conftest import audit_actions

OLD, NEW = Fernet.generate_key().decode(), Fernet.generate_key().decode()


@pytest.fixture
def db(make_settings, make_user, db_conn):
    secrets = {}
    for _ in range(3):
        uid = make_user(role="admin")
        secrets[uid] = pyotp.random_base32()
        db_conn.execute("UPDATE users SET mfa_enabled = 1, mfa_secret_encrypted = ? WHERE user_id = ?",
                        (mfa.encrypt_secret(OLD, secrets[uid]), uid))
    db_conn.commit()
    database = Database(make_settings())
    yield database, secrets
    database.close()


def _stored(db_conn):
    return {r["user_id"]: r["mfa_secret_encrypted"] for r in
            db_conn.execute("SELECT user_id, mfa_secret_encrypted FROM users WHERE mfa_secret_encrypted IS NOT NULL")}


def test_rotation_moves_every_secret_to_the_new_key(db, db_conn):
    database, secrets = db
    assert rotate(database, f"{NEW},{OLD}") == {"secrets": 3, "re_encrypted": 3, "already_current": 0}
    for uid, token in _stored(db_conn).items():
        assert mfa.decrypt_secret(NEW, token) == secrets[uid]           # the new key alone now works
    assert audit_actions(db_conn, "mfa_key_rotated")[0]["re_encrypted"] == 3
    # running it again changes nothing
    assert rotate(database, f"{NEW},{OLD}")["already_current"] == 3


def test_dry_run_writes_nothing(db, db_conn):
    database, _ = db
    before = _stored(db_conn)
    assert rotate(database, f"{NEW},{OLD}", dry_run=True)["re_encrypted"] == 3
    assert _stored(db_conn) == before
    assert audit_actions(db_conn, "mfa_key_rotated") == []


def test_unreadable_secret_aborts_without_changes(db, db_conn):
    database, _ = db
    before = _stored(db_conn)
    with pytest.raises(SystemExit, match="3 stored secret"):
        rotate(database, f"{NEW},{Fernet.generate_key().decode()}")   # old key missing
    assert _stored(db_conn) == before


def test_single_key_is_refused(db):
    database, _ = db
    with pytest.raises(SystemExit, match="NEW key first"):
        rotate(database, NEW)
