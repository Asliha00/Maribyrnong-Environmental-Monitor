"""User and role queries (parameterised SQL only, SEC-19)."""
from __future__ import annotations

from typing import Any

from ..db import Transaction, to_datetime

TIMESTAMP_FIELDS = ("locked_until", "tokens_valid_after")


def _normalise(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    for field in TIMESTAMP_FIELDS:
        row[field] = to_datetime(row[field])
    row["permissions"] = frozenset(p.strip() for p in row["permissions"].split(",") if p.strip())
    for flag in ("is_active", "must_change_password", "mfa_enabled"):
        row[flag] = bool(row[flag])
    return row


def by_email(tx: Transaction, email: str) -> dict[str, Any] | None:
    """Case-insensitive email lookup."""
    return _normalise(tx.fetch_one(
        """SELECT u.user_id, u.username, u.email, u.password_hash, u.role_id, u.is_active,
              u.must_change_password, u.failed_attempts, u.locked_until, u.mfa_enabled,
              u.mfa_secret_encrypted, u.mfa_last_used_step, u.tokens_valid_after,
              r.role_name, r.permissions
           FROM users u JOIN roles r ON r.role_id = u.role_id
           WHERE lower(u.email) = lower(?)""",
        (email,)))


def by_id(tx: Transaction, user_id: int) -> dict[str, Any] | None:
    return _normalise(tx.fetch_one(
        """SELECT u.user_id, u.username, u.email, u.password_hash, u.role_id, u.is_active,
              u.must_change_password, u.failed_attempts, u.locked_until, u.mfa_enabled,
              u.mfa_secret_encrypted, u.mfa_last_used_step, u.tokens_valid_after,
              r.role_name, r.permissions
           FROM users u JOIN roles r ON r.role_id = u.role_id
           WHERE u.user_id = ?""",
        (user_id,)))


def is_revoked(tx: Transaction, jti: str) -> bool:
    return tx.fetch_one("SELECT 1 AS hit FROM revoked_tokens WHERE jti = ?", (jti,)) is not None


def revoke(tx: Transaction, jti: str, user_id: int, expires_at) -> None:
    """Add a token id to the deny-list (idempotent)."""
    tx.execute("INSERT INTO revoked_tokens (jti, user_id, expires_at) VALUES (?, ?, ?) ON CONFLICT (jti) DO NOTHING",
               (jti, user_id, expires_at))


def purge_expired_revocations(tx: Transaction, now) -> int:
    """Expired tokens are rejected by their own `exp`, so their deny-list rows can go."""
    return tx.execute("DELETE FROM revoked_tokens WHERE expires_at < ?", (now,))
