"""
User management (BUILD_PROMPT §4.5): list, create, change role, deactivate/reactivate, reset
password, reset MFA. `manage_users` (administrators with MFA) only.

- Temporary passwords are generated here (128 random bits), shown once, stored as argon2id,
  and must be changed at the next login.
- Any change to a user's access signs them out everywhere (`tokens_valid_after`, SEC-08).
- An administrator cannot change their own role, deactivate themselves or reset their own
  password or MFA here, so the system can never be left without a working administrator
  and nobody approves their own access change.
"""
from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request

from ..db import Transaction, to_datetime
from ..errors import AppError
from ..passwords import hash_password, policy_violations
from ..schemas import UserCreate, UserUpdate
from ..security import Session, require_permission
from ..services import recovery_codes
from ..tokens import truncate_ms
from . import admin_common

router = APIRouter(prefix="/admin/users", tags=["admin"])
can_manage = require_permission("manage_users")

UserId = Annotated[int, Path(ge=1, le=1_000_000)]
MSG_SELF = "You cannot change your own access here. Ask another administrator."
SQL_USERS = """SELECT u.user_id, u.username, u.email, u.role_id, r.role_name, u.is_active, u.must_change_password,
                      u.failed_attempts, u.locked_until, u.mfa_enabled, u.last_login_at, u.created_at
               FROM users u JOIN roles r ON r.role_id = u.role_id ORDER BY u.username"""


def _iso(value: Any) -> str | None:
    moment = to_datetime(value)
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if moment else None


def _out(row: dict[str, Any]) -> dict[str, Any]:
    """What an administrator sees about a user: never the password hash or MFA secret."""
    locked_until = to_datetime(row["locked_until"])
    return {"user_id": row["user_id"], "username": row["username"], "email": row["email"],
            "role_id": row["role_id"], "role_name": row["role_name"], "is_active": bool(row["is_active"]),
            "must_change_password": bool(row["must_change_password"]), "mfa_enabled": bool(row["mfa_enabled"]),
            "locked": bool(locked_until and locked_until > datetime.now(UTC)),
            "last_login_at": _iso(row["last_login_at"]), "created_at": _iso(row["created_at"])}


def _find(tx: Transaction, user_id: int) -> dict[str, Any]:
    row = next((r for r in tx.fetch_all(SQL_USERS) if r["user_id"] == user_id), None)
    if row is None:
        raise AppError(404, "user_not_found", "User not found.")
    return row


def _not_self(session: Session, user_id: int) -> None:
    if session.user_id == user_id:
        raise AppError(409, "own_account", MSG_SELF)


def temporary_password(username: str, email: str) -> str:
    """A random temporary password that passes the policy (practically always first time)."""
    while True:
        candidate = secrets.token_urlsafe(16)
        if not policy_violations(candidate, username, email):
            return candidate


def _sign_out_everywhere(tx: Transaction, user_id: int) -> None:
    tx.execute("UPDATE users SET tokens_valid_after = ? WHERE user_id = ?",
               (truncate_ms(datetime.now(UTC)), user_id))


@router.get("")
def list_users(request: Request, session: Session = Depends(can_manage)) -> dict[str, Any]:
    with request.app.state.db.transaction() as tx:
        admin_common.limit(tx, session)
        return {"users": [_out(r) for r in tx.fetch_all(SQL_USERS)]}


@router.post("", status_code=201)
def create_user(request: Request, body: UserCreate, session: Session = Depends(can_manage)) -> dict[str, Any]:
    """Create an account with a temporary password (shown once; must be changed at first login)."""
    password = temporary_password(body.username, body.email)
    with request.app.state.db.transaction() as tx:
        admin_common.limit(tx, session)
        for row in tx.fetch_all("SELECT username, email FROM users"):
            if row["email"].lower() == body.email:
                raise AppError(409, "duplicate_email", "An account with this email address already exists.")
            if row["username"].lower() == body.username:
                raise AppError(409, "duplicate_username", "This username is already taken.")
        tx.execute("INSERT INTO users (username, email, password_hash, role_id, is_active, must_change_password) "
                   "VALUES (?, ?, ?, ?, 1, 1)", (body.username, body.email, hash_password(password), body.role_id))
        row = next(r for r in tx.fetch_all(SQL_USERS) if r["username"] == body.username)
        admin_common.record(tx, request, session, "user_created", {
            "target_user_id": row["user_id"], "username": body.username, "role": row["role_name"]})
    return {"message": "Account created. Give the user this temporary password; they must change it when they "
                       "first log in. It will not be shown again.",
            "user": _out(row), "temporary_password": password}


@router.put("/{user_id}")
def update_user(request: Request, user_id: UserId, body: UserUpdate,
                session: Session = Depends(can_manage)) -> dict[str, Any]:
    """Change role and/or active state. The user is signed out everywhere."""
    changes = body.model_dump(exclude_unset=True)
    if not changes or None in changes.values():
        raise AppError(422, "nothing_to_change", "Choose a role or an account status to change.")
    _not_self(session, user_id)
    with request.app.state.db.transaction() as tx:
        admin_common.limit(tx, session)
        before = _find(tx, user_id)
        role_id = changes.get("role_id", before["role_id"])
        active = int(changes.get("is_active", bool(before["is_active"])))
        tx.execute("UPDATE users SET role_id = ?, is_active = ? WHERE user_id = ?", (role_id, active, user_id))
        _sign_out_everywhere(tx, user_id)
        after = _find(tx, user_id)
        diff = {}
        if after["role_id"] != before["role_id"]:
            diff["role"] = {"from": before["role_name"], "to": after["role_name"]}
        if bool(after["is_active"]) != bool(before["is_active"]):
            diff["is_active"] = {"from": bool(before["is_active"]), "to": bool(after["is_active"])}
        admin_common.record(tx, request, session, "user_updated",
                            {"target_user_id": user_id, "username": before["username"], "changes": diff})
    return {"message": "User updated. They have been signed out of every device.", "user": _out(after)}


@router.post("/{user_id}/reset-password")
def reset_password(request: Request, user_id: UserId, session: Session = Depends(can_manage)) -> dict[str, Any]:
    """New temporary password (shown once), must be changed at next login; clears any lockout."""
    _not_self(session, user_id)
    with request.app.state.db.transaction() as tx:
        admin_common.limit(tx, session)
        before = _find(tx, user_id)
        password = temporary_password(before["username"], before["email"])
        tx.execute("UPDATE users SET password_hash = ?, must_change_password = 1, failed_attempts = 0, "
                   "locked_until = NULL WHERE user_id = ?", (hash_password(password), user_id))
        _sign_out_everywhere(tx, user_id)
        admin_common.record(tx, request, session, "user_password_reset",
                            {"target_user_id": user_id, "username": before["username"]})
        after = _find(tx, user_id)
    return {"message": "Password reset. Give the user this temporary password; they must change it when they "
                       "next log in. It will not be shown again.",
            "user": _out(after), "temporary_password": password}


@router.post("/{user_id}/reset-mfa")
def reset_mfa(request: Request, user_id: UserId, session: Session = Depends(can_manage)) -> dict[str, Any]:
    """Remove a lost authenticator: the user enrols a new one at next login (admins must)."""
    _not_self(session, user_id)
    with request.app.state.db.transaction() as tx:
        admin_common.limit(tx, session)
        before = _find(tx, user_id)
        tx.execute("UPDATE users SET mfa_enabled = 0, mfa_secret_encrypted = NULL, mfa_last_used_step = NULL "
                   "WHERE user_id = ?", (user_id,))
        cancelled = recovery_codes.revoke_all(tx, user_id, truncate_ms(datetime.now(UTC)))   # D-037
        _sign_out_everywhere(tx, user_id)
        admin_common.record(tx, request, session, "user_mfa_reset",
                            {"target_user_id": user_id, "username": before["username"],
                             "had_mfa": bool(before["mfa_enabled"]), "recovery_codes_cancelled": cancelled})
        after = _find(tx, user_id)
    return {"message": "Two-factor authentication reset. The user will set it up again at their next login.",
            "user": _out(after)}
