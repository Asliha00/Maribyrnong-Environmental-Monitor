"""
Authentication endpoints (UC1, proposal Algorithm 3; SEC-04 to SEC-09, SEC-23, SEC-27).

Pattern used throughout: decide the outcome INSIDE the transaction, raise AFTER it
commits. Otherwise raising would roll back the very things a failure must record:
the failed-attempt counter, the lockout, the rate-limit hit and the audit entry.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request, Response

from ..errors import AppError
from ..passwords import dummy_hash, hash_password, needs_rehash, policy_violations, verify_password
from ..schemas import (
    ChangePasswordRequest,
    CheckResponse,
    LoginRequest,
    LoginResponse,
    MfaSetupResponse,
    MfaVerifyRequest,
    MfaVerifyResponse,
    OkResponse,
    RecoveryCodeRequest,
    RecoveryCodesResponse,
    RecoveryLoginResponse,
    RecoveryStatusResponse,
    UserOut,
)
from ..security import (
    ACCESS_COOKIE,
    AUTHENTICATED,
    KNOWN_PERMISSIONS,
    REFRESH_COOKIE,
    Session,
    clear_session_cookies,
    client_ip,
    require_permission,
    set_session_cookies,
)
from ..services import audit, mfa, rate_limit, recovery_codes, users
from ..tokens import TokenError, decode, issue_pair, issued_before, truncate_ms

router = APIRouter(tags=["auth"])

MAX_FAILED_ATTEMPTS = 5                 # UC1: 5 consecutive failures ...
LOCKOUT = timedelta(minutes=15)         # ... lock the account for 15 minutes
MSG_INVALID = "Invalid email or password"
MSG_LOCKED = ("Your account has been locked after 5 failed login attempts. "
              "Please try again in 15 minutes or contact your administrator.")
MSG_RATE = "Too many attempts. Please wait a minute and try again."
MSG_MFA_CODE = "That code is not valid. Check your authenticator app and try again."
MSG_RECOVERY_CODE = "That recovery code is not valid or has already been used."
MSG_NEEDS_MFA_SESSION = "Sign in with your authenticator app or a recovery code first."

signed_in = require_permission(AUTHENTICATED, allow_pending_password_change=True)
signed_in_ready = require_permission(AUTHENTICATED)


def _now() -> datetime:
    return datetime.now(UTC)


def _needs_mfa(permissions) -> bool:
    return any(p.startswith("manage_") for p in permissions)


def _user_out(user: dict, mfa_verified: bool) -> UserOut:
    return UserOut(user_id=user["user_id"], username=user["username"], email=user["email"], role=user["role_name"],
                   permissions=sorted(user["permissions"]), must_change_password=user["must_change_password"],
                   mfa_enabled=user["mfa_enabled"], mfa_required=_needs_mfa(user["permissions"]),
                   mfa_verified=mfa_verified)


def _next_step(user: dict, mfa_verified: bool) -> str:
    if user["must_change_password"]:
        return "change_password"
    if _needs_mfa(user["permissions"]) and not mfa_verified:
        return "mfa_verify" if user["mfa_enabled"] else "mfa_setup"
    return "done"


def _rate_limited(retry_after: int) -> AppError:
    return AppError(429, "rate_limited", MSG_RATE, headers={"Retry-After": str(retry_after)})


@router.post("/auth/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, response: Response) -> LoginResponse:
    """UC1 login. Same message, status and roughly the same time for an unknown email
    and a wrong password (SEC-06): an unknown email is checked against a dummy hash."""
    db, settings, ip, now = request.app.state.db, request.app.state.settings, client_ip(request), truncate_ms(_now())
    error: AppError | None = None
    user = None
    with db.transaction() as tx:
        rate_limit.purge_stale(tx, now)
        users.purge_expired_revocations(tx, now)
        allowed, retry_after = rate_limit.hit(tx, rate_limit.LOGIN_PER_IP, ip, now)
        if not allowed:
            audit.record(tx, "login_rate_limited", ip=ip)
            error = _rate_limited(retry_after)
        else:
            user = users.by_email(tx, body.email)
            if user is None:
                verify_password(dummy_hash(), body.password)
                audit.record(tx, "login_failed", ip=ip, detail={"reason": "unknown_email"})
                audit.flag_failed_login_burst(tx, ip)
                error = AppError(401, "invalid_credentials", MSG_INVALID)
            elif user["locked_until"] is not None and user["locked_until"] > now:
                verify_password(dummy_hash(), body.password)   # keep timing uniform; do not test the password
                audit.record(tx, "login_blocked_locked", user_id=user["user_id"], ip=ip)
                error = AppError(423, "account_locked", MSG_LOCKED)
            elif not verify_password(user["password_hash"], body.password):
                attempts = user["failed_attempts"] + 1
                if attempts >= MAX_FAILED_ATTEMPTS:
                    tx.execute("UPDATE users SET failed_attempts = 0, locked_until = ? WHERE user_id = ?",
                               (now + LOCKOUT, user["user_id"]))
                    audit.record(tx, "account_locked", user_id=user["user_id"], ip=ip,
                                 detail={"minutes": int(LOCKOUT.total_seconds() // 60)})
                    error = AppError(423, "account_locked", MSG_LOCKED)
                else:
                    tx.execute("UPDATE users SET failed_attempts = ? WHERE user_id = ?", (attempts, user["user_id"]))
                    error = AppError(401, "invalid_credentials", MSG_INVALID)
                audit.record(tx, "login_failed", user_id=user["user_id"], ip=ip,
                             detail={"reason": "wrong_password", "consecutive_failures": attempts})
                audit.flag_failed_login_burst(tx, ip)
            elif not user["is_active"]:
                audit.record(tx, "login_failed", user_id=user["user_id"], ip=ip, detail={"reason": "deactivated"})
                error = AppError(403, "account_deactivated",
                                 "Your account has been deactivated. Please contact your administrator.")
            else:
                new_hash = user["password_hash"]
                if needs_rehash(new_hash):
                    new_hash = hash_password(body.password)
                tx.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL, last_login_at = ?, "
                           "password_hash = ? WHERE user_id = ?", (now, new_hash, user["user_id"]))
                audit.record(tx, "login_success", user_id=user["user_id"], ip=ip)
    if error:
        raise error
    access, refresh = issue_pair(settings.jwt_secret, user["user_id"], mfa=False, now=now)
    set_session_cookies(request, response, access, refresh)
    return LoginResponse(user=_user_out(user, False), next_step=_next_step(user, False))


@router.post("/auth/refresh", response_model=LoginResponse)
def refresh(request: Request, response: Response) -> LoginResponse:
    """Rotate the refresh token (SEC-08). Presenting an already-used refresh token is
    treated as theft: every session of that user is ended."""
    db, settings, ip, now = request.app.state.db, request.app.state.settings, client_ip(request), truncate_ms(_now())
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise AppError(401, "not_authenticated", "Please log in to continue.")
    try:
        claims = decode(settings.jwt_secret, token, "refresh")
    except TokenError as exc:
        raise AppError(401, "session_expired", "Your session has expired. Please log in again.") from exc
    error: AppError | None = None
    with db.transaction() as tx:
        user = users.by_id(tx, claims.user_id)
        valid_after = user["tokens_valid_after"] if user else None
        if user is None or not user["is_active"]:
            error = AppError(401, "session_expired", "Your session has expired. Please log in again.")
        elif users.is_revoked(tx, claims.jti):
            tx.execute("UPDATE users SET tokens_valid_after = ? WHERE user_id = ?",
                       (truncate_ms(now), user["user_id"]))
            audit.record(tx, "refresh_token_reuse", user_id=user["user_id"], ip=ip)
            error = AppError(401, "session_expired", "Your session has expired. Please log in again.")
        elif issued_before(claims, valid_after):
            error = AppError(401, "session_expired", "Your session has expired. Please log in again.")
        else:
            users.revoke(tx, claims.jti, user["user_id"], claims.expires_at)
    if error:
        clear_session_cookies(request, response)
        raise error
    access, new_refresh = issue_pair(settings.jwt_secret, user["user_id"], mfa=claims.mfa,
                                     refresh_expires=claims.expires_at, now=now)
    set_session_cookies(request, response, access, new_refresh)
    return LoginResponse(user=_user_out(user, claims.mfa), next_step=_next_step(user, claims.mfa))


@router.post("/auth/logout", response_model=OkResponse)
def logout(request: Request, response: Response) -> OkResponse:
    """Revoke whichever tokens the browser holds and clear the cookies. Works even if the
    access token has already expired, so it needs no permission guard (SEC-10 allow-list)."""
    settings, db, ip = request.app.state.settings, request.app.state.db, client_ip(request)
    found = []
    for cookie, kind in ((ACCESS_COOKIE, "access"), (REFRESH_COOKIE, "refresh")):
        token = request.cookies.get(cookie)
        if token:
            try:
                found.append(decode(settings.jwt_secret, token, kind))
            except TokenError:
                pass
    if found:
        with db.transaction() as tx:
            for claims in found:
                users.revoke(tx, claims.jti, claims.user_id, claims.expires_at)
            audit.record(tx, "logout", user_id=found[0].user_id, ip=ip)
    clear_session_cookies(request, response)
    return OkResponse()


@router.post("/auth/change-password", response_model=LoginResponse)
def change_password(body: ChangePasswordRequest, request: Request, response: Response,
                    session: Session = Depends(signed_in)) -> LoginResponse:
    """Forced first-login change and voluntary change (SEC-05). Ends every other session."""
    db, settings, ip, now = request.app.state.db, request.app.state.settings, client_ip(request), truncate_ms(_now())
    error: AppError | None = None
    with db.transaction() as tx:
        allowed, retry_after = rate_limit.hit(tx, rate_limit.PASSWORD_CHANGE_PER_USER, str(session.user_id), now)
        user = users.by_id(tx, session.user_id)
        if not allowed:
            error = _rate_limited(retry_after)
        elif not verify_password(user["password_hash"], body.current_password):
            audit.record(tx, "password_change_failed", user_id=user["user_id"], ip=ip,
                         detail={"reason": "wrong_current"})
            error = AppError(400, "wrong_current_password", "Your current password is incorrect.")
        elif problems := policy_violations(body.new_password, user["username"], user["email"]):
            error = AppError(400, "weak_password", " ".join(problems))
        elif verify_password(user["password_hash"], body.new_password):
            error = AppError(400, "weak_password", "Choose a new password that is different from your current one.")
        else:
            tx.execute("UPDATE users SET password_hash = ?, must_change_password = 0, tokens_valid_after = ? "
                       "WHERE user_id = ?",
                       (hash_password(body.new_password), truncate_ms(now), user["user_id"]))
            users.revoke(tx, session.claims.jti, user["user_id"], session.claims.expires_at)
            audit.record(tx, "password_changed", user_id=user["user_id"], ip=ip)
            user = users.by_id(tx, session.user_id)
    if error:
        raise error
    access, refresh_token = issue_pair(settings.jwt_secret, user["user_id"], mfa=session.claims.mfa, now=now)
    set_session_cookies(request, response, access, refresh_token)
    return LoginResponse(user=_user_out(user, session.claims.mfa), next_step=_next_step(user, session.claims.mfa))


@router.post("/auth/mfa/setup", response_model=MfaSetupResponse)
def mfa_setup(request: Request, session: Session = Depends(signed_in_ready)) -> MfaSetupResponse:
    """Start TOTP enrolment: store a new encrypted secret (not yet enabled) and return
    the QR code. The secret is shown once, over HTTPS, to the signed-in user only."""
    db, settings, ip = request.app.state.db, request.app.state.settings, client_ip(request)
    if session.user["mfa_enabled"]:
        raise AppError(409, "mfa_already_enabled",
                       "Two-factor authentication is already set up. Ask another administrator to reset it.")
    secret = mfa.new_secret()
    with db.transaction() as tx:
        tx.execute("UPDATE users SET mfa_secret_encrypted = ?, mfa_last_used_step = NULL WHERE user_id = ?",
                   (mfa.encrypt_secret(settings.mfa_encryption_key, secret), session.user_id))
        audit.record(tx, "mfa_setup_started", user_id=session.user_id, ip=ip)
    uri, qr = mfa.provisioning(secret, session.user["email"])
    return MfaSetupResponse(otpauth_uri=uri, qr_svg_data_uri=qr, manual_entry_key=secret)


@router.post("/auth/mfa/verify", response_model=MfaVerifyResponse)
def mfa_verify(body: MfaVerifyRequest, request: Request, response: Response,
               session: Session = Depends(signed_in_ready)) -> MfaVerifyResponse:
    """Check a TOTP code. First success enables MFA and returns the first set of recovery
    codes (shown once, D-037); every success upgrades this session to an MFA session
    (needed for any manage_* permission)."""
    db, settings, ip, now = request.app.state.db, request.app.state.settings, client_ip(request), truncate_ms(_now())
    error: AppError | None = None
    codes: list[str] | None = None
    with db.transaction() as tx:
        allowed, retry_after = rate_limit.hit(tx, rate_limit.MFA_VERIFY_PER_USER, str(session.user_id), now)
        user = users.by_id(tx, session.user_id)
        if not allowed:
            error = _rate_limited(retry_after)
        elif not user["mfa_secret_encrypted"]:
            error = AppError(400, "mfa_not_set_up", "Set up two-factor authentication first.")
        else:
            secret = mfa.decrypt_secret(settings.mfa_encryption_key, user["mfa_secret_encrypted"])
            step = mfa.matching_step(secret, body.code, user["mfa_last_used_step"], now.timestamp())
            if step is None:
                audit.record(tx, "mfa_failed", user_id=user["user_id"], ip=ip)
                error = AppError(400, "invalid_mfa_code", MSG_MFA_CODE)
            else:
                first_time = not user["mfa_enabled"]
                tx.execute("UPDATE users SET mfa_last_used_step = ?, mfa_enabled = 1 WHERE user_id = ?",
                           (step, user["user_id"]))
                users.revoke(tx, session.claims.jti, user["user_id"], session.claims.expires_at)
                audit.record(tx, "mfa_enabled" if first_time else "mfa_verified", user_id=user["user_id"], ip=ip)
                if first_time:
                    codes = recovery_codes.replace_set(tx, user["user_id"], now)
                    audit.record(tx, "mfa_recovery_codes_generated", user_id=user["user_id"], ip=ip,
                                 detail={"count": len(codes)})
                user = users.by_id(tx, session.user_id)
    if error:
        raise error
    result = _start_mfa_session(request, response, user, now)
    return MfaVerifyResponse(**result.model_dump(), recovery_codes=codes)


def _start_mfa_session(request: Request, response: Response, user: dict, now: datetime) -> LoginResponse:
    """Replace the session cookies with an MFA session after a second factor was accepted.
    The old refresh token is revoked; the new one keeps its absolute expiry."""
    db, settings = request.app.state.db, request.app.state.settings
    refresh_expires = None
    old_refresh = request.cookies.get(REFRESH_COOKIE)
    if old_refresh:
        try:
            old = decode(settings.jwt_secret, old_refresh, "refresh")
            refresh_expires = old.expires_at
            with db.transaction() as tx:
                users.revoke(tx, old.jti, old.user_id, old.expires_at)
        except TokenError:
            pass
    access, refresh_token = issue_pair(settings.jwt_secret, user["user_id"], mfa=True,
                                       refresh_expires=refresh_expires, now=now)
    set_session_cookies(request, response, access, refresh_token)
    return LoginResponse(user=_user_out(user, True), next_step=_next_step(user, True))


@router.post("/auth/mfa/recovery", response_model=RecoveryLoginResponse)
def mfa_recovery(body: RecoveryCodeRequest, request: Request, response: Response,
                 session: Session = Depends(signed_in_ready)) -> RecoveryLoginResponse:
    """Use a single-use recovery code instead of the authenticator code (D-037). Only for
    accounts that already have 2FA set up, after the password step; shares the
    authenticator's rate limit, so the two cannot be combined to guess faster."""
    db, ip, now = request.app.state.db, client_ip(request), truncate_ms(_now())
    error: AppError | None = None
    left = 0
    with db.transaction() as tx:
        allowed, retry_after = rate_limit.hit(tx, rate_limit.MFA_VERIFY_PER_USER, str(session.user_id), now)
        user = users.by_id(tx, session.user_id)
        if not allowed:
            error = _rate_limited(retry_after)
        elif not user["mfa_enabled"]:
            error = AppError(400, "mfa_not_set_up", "Set up two-factor authentication first.")
        elif not recovery_codes.consume(tx, user["user_id"], body.code, now):
            audit.record(tx, "mfa_recovery_failed", user_id=user["user_id"], ip=ip)
            error = AppError(400, "invalid_recovery_code", MSG_RECOVERY_CODE)
        else:
            left = recovery_codes.remaining(tx, user["user_id"])
            users.revoke(tx, session.claims.jti, user["user_id"], session.claims.expires_at)
            audit.record(tx, "mfa_recovery_used", user_id=user["user_id"], ip=ip, detail={"remaining": left})
    if error:
        raise error
    result = _start_mfa_session(request, response, user, now)
    return RecoveryLoginResponse(**result.model_dump(), recovery_codes_remaining=left)


def _require_mfa_session(session: Session) -> None:
    """New codes, or the code count, only from a session that already passed 2FA."""
    if not (session.user["mfa_enabled"] and session.claims.mfa):
        raise AppError(403, "mfa_required", MSG_NEEDS_MFA_SESSION)


@router.get("/auth/mfa/recovery-codes", response_model=RecoveryStatusResponse)
def recovery_status(request: Request, session: Session = Depends(signed_in_ready)) -> RecoveryStatusResponse:
    """How many unused recovery codes this account has (never the codes themselves)."""
    _require_mfa_session(session)
    with request.app.state.db.transaction() as tx:
        left = recovery_codes.remaining(tx, session.user_id)
    return RecoveryStatusResponse(remaining=left, low=left <= recovery_codes.LOW_WARNING)


@router.post("/auth/mfa/recovery-codes", response_model=RecoveryCodesResponse)
def regenerate_recovery_codes(request: Request,
                              session: Session = Depends(signed_in_ready)) -> RecoveryCodesResponse:
    """Cancel all unused codes and issue a new set, shown once."""
    _require_mfa_session(session)
    ip, now = client_ip(request), truncate_ms(_now())
    error: AppError | None = None
    codes: list[str] = []
    with request.app.state.db.transaction() as tx:
        allowed, retry_after = rate_limit.hit(tx, rate_limit.MFA_VERIFY_PER_USER, str(session.user_id), now)
        if not allowed:
            error = _rate_limited(retry_after)
        else:
            cancelled = recovery_codes.remaining(tx, session.user_id)
            codes = recovery_codes.replace_set(tx, session.user_id, now)
            audit.record(tx, "mfa_recovery_codes_generated", user_id=session.user_id, ip=ip,
                         detail={"count": len(codes), "cancelled": cancelled})
    if error:
        raise error
    return RecoveryCodesResponse(recovery_codes=codes)


@router.get("/auth/check", response_model=CheckResponse)
def check(request: Request, permission: str = Query(max_length=64),
          session: Session = Depends(signed_in_ready)) -> CheckResponse:
    """200 if the signed-in user holds `permission` (MFA rules included), else 403.
    Used by the Node Blob-upload route (§4.5) to authorise client uploads."""
    if permission not in KNOWN_PERMISSIONS:
        raise AppError(422, "unknown_permission", "Unknown permission.")
    require_permission(permission)(request)
    return CheckResponse(allowed=True, permission=permission)


@router.get("/me", response_model=UserOut)
def me(session: Session = Depends(signed_in)) -> UserOut:
    """The signed-in user's own minimal profile (name, email, role: SEC-29)."""
    return _user_out(session.user, session.claims.mfa)
