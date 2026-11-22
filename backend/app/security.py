"""
Request-level security: cookies, CSRF, client IP, and the role guard.

* SEC-09: tokens live only in HttpOnly, Secure, SameSite=Strict cookies. A third,
  JavaScript-readable cookie holds a random CSRF token that must be echoed in the
  `X-CSRF-Token` header on every state-changing request (double-submit cookie).
* SEC-10/11 (proposal Algorithm 4): every protected route depends on
  `require_permission(...)`. The guard re-reads the user and role from the database
  on each request, so deactivation, role changes and password changes apply at once.
* SEC-07: any `manage_*` permission also needs a session that passed TOTP MFA.
"""
from __future__ import annotations

import hmac
import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import Request, Response

from .errors import AppError
from .services import users
from .tokens import ACCESS_TTL, REFRESH_TTL, TokenClaims, TokenError, decode, issued_before

ACCESS_COOKIE = "mem_access"
REFRESH_COOKIE = "mem_refresh"
CSRF_COOKIE = "mem_csrf"
CSRF_HEADER = "X-CSRF-Token"

AUTHENTICATED = "authenticated"   # pseudo-permission: any logged-in user
KNOWN_PERMISSIONS = frozenset({"view_data", "filter_data", "export_data", "view_quality",
                               "manage_sensors", "manage_users", "manage_thresholds"})
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# No session exists yet (login) or the caller is a device, not a browser (ingest, Phase 6).
CSRF_EXEMPT_PATHS = {"/api/auth/login", "/api/ingest"}

MSG_LOGIN = "Please log in to continue."
MSG_EXPIRED = "Your session has expired. Please log in again."
MSG_DEACTIVATED = "Your account has been deactivated. Please contact your administrator."
MSG_FORBIDDEN = "You do not have permission to access this page."
MSG_MFA = "Administrators must set up and use two-factor authentication to open this page."
MSG_CHANGE_PASSWORD = "You must change your password before continuing."  # noqa: S105 - a message, not a secret


# ---------- cookies ----------
def _secure(request: Request) -> bool:
    # Development runs on http://localhost, where browsers drop Secure cookies.
    return request.app.state.settings.environment != "development"


def set_session_cookies(request: Request, response: Response, access: str, refresh: str) -> str:
    """Set the token cookies and a fresh CSRF token; return the CSRF token."""
    secure = _secure(request)
    response.set_cookie(ACCESS_COOKIE, access, max_age=int(ACCESS_TTL.total_seconds()), path="/api",
                        httponly=True, secure=secure, samesite="strict")
    # The refresh token is only ever sent to the auth endpoints that need it
    response.set_cookie(REFRESH_COOKIE, refresh, max_age=int(REFRESH_TTL.total_seconds()), path="/api/auth",
                        httponly=True, secure=secure, samesite="strict")
    csrf = secrets.token_urlsafe(32)
    response.set_cookie(CSRF_COOKIE, csrf, max_age=int(REFRESH_TTL.total_seconds()), path="/",
                        httponly=False, secure=secure, samesite="strict")
    return csrf


def clear_session_cookies(request: Request, response: Response) -> None:
    secure = _secure(request)
    for name, path in ((ACCESS_COOKIE, "/api"), (REFRESH_COOKIE, "/api/auth"), (CSRF_COOKIE, "/")):
        response.delete_cookie(name, path=path, secure=secure, httponly=name != CSRF_COOKIE, samesite="strict")


# ---------- client IP ----------
def client_ip(request: Request) -> str:
    """The caller's IP. On Vercel, `x-real-ip` is set by Vercel's edge (a client cannot
    choose it); anywhere else proxy headers are ignored because a client could forge them."""
    if os.environ.get("VERCEL") == "1":
        real = request.headers.get("x-real-ip")
        if real:
            return real.strip()
    return request.client.host if request.client else "unknown"


# ---------- CSRF (global dependency) ----------
async def verify_csrf(request: Request) -> None:
    """Reject state-changing requests whose X-CSRF-Token header does not match the cookie."""
    if request.method not in UNSAFE_METHODS or request.url.path in CSRF_EXEMPT_PATHS:
        return
    cookie = request.cookies.get(CSRF_COOKIE, "")
    header = request.headers.get(CSRF_HEADER, "")
    if not cookie or not header or not hmac.compare_digest(cookie, header):
        raise AppError(403, "csrf_failed", "Your request could not be verified. Please refresh the page and try again.")


# ---------- the role guard ----------
@dataclass(frozen=True)
class Session:
    user: dict[str, Any]       # never contains password_hash or the MFA secret
    claims: TokenClaims

    @property
    def user_id(self) -> int:
        return self.user["user_id"]


PUBLIC_USER_FIELDS = ("user_id", "username", "email", "role_name", "permissions", "must_change_password",
                      "mfa_enabled", "is_active")


def load_session(request: Request, *, allow_pending_password_change: bool) -> tuple[Session, dict[str, Any]]:
    """Authenticate the access cookie. Returns the Session and the full user row."""
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise AppError(401, "not_authenticated", MSG_LOGIN)
    settings = request.app.state.settings
    try:
        claims = decode(settings.jwt_secret, token, "access")
    except TokenError as exc:
        expired = str(exc) == "expired"
        raise AppError(401, "session_expired" if expired else "invalid_token",
                       MSG_EXPIRED if expired else MSG_LOGIN) from exc
    with request.app.state.db.transaction() as tx:
        user = users.by_id(tx, claims.user_id)
        revoked = user is not None and users.is_revoked(tx, claims.jti)
    if user is None:
        raise AppError(401, "invalid_token", MSG_LOGIN)
    if not user["is_active"]:
        raise AppError(401, "account_deactivated", MSG_DEACTIVATED)
    if revoked or issued_before(claims, user["tokens_valid_after"]):
        raise AppError(401, "session_expired", MSG_EXPIRED)
    if user["must_change_password"] and not allow_pending_password_change:
        raise AppError(403, "password_change_required", MSG_CHANGE_PASSWORD)
    public = {k: user[k] for k in PUBLIC_USER_FIELDS}
    return Session(user=public, claims=claims), user


def require_permission(permission: str, *, allow_pending_password_change: bool = False) -> Callable[..., Session]:
    """FastAPI dependency factory (Algorithm 4). `permission` is a value from
    roles.permissions, or AUTHENTICATED for 'any logged-in user'."""
    if permission != AUTHENTICATED and permission not in KNOWN_PERMISSIONS:
        raise ValueError(f"unknown permission {permission!r}")

    def dependency(request: Request) -> Session:
        session, user = load_session(request, allow_pending_password_change=allow_pending_password_change)
        if permission != AUTHENTICATED and permission not in user["permissions"]:
            raise AppError(403, "forbidden", MSG_FORBIDDEN)
        if permission.startswith("manage_") and not (user["mfa_enabled"] and session.claims.mfa):
            raise AppError(403, "mfa_required", MSG_MFA)
        return session

    # Lets test_every_route_is_protected find the guard on each route (SEC-10)
    dependency.required_permission = permission  # type: ignore[attr-defined]
    return dependency
