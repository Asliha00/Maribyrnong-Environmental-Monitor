"""
JSON Web Tokens (SEC-08).

* HS256 only: the algorithm is pinned on decode, so `alg: none` or an RS/HS
  confusion attack is rejected.
* Access token 30 minutes; refresh token 8 hours. A refresh token is rotated on
  every use, and the new one keeps the ORIGINAL expiry, so a session can never
  last longer than 8 hours (DECISIONS.md D-026).
* Every token has a unique `jti` so it can be revoked (`revoked_tokens`), and an
  `iat` checked against `users.tokens_valid_after`.
* `mfa` records whether this session completed TOTP verification (SEC-07).
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

ALGORITHM = "HS256"
ISSUER = "maribyrnong-env-monitor"
AUDIENCE = "maribyrnong-env-monitor-web"
ACCESS_TTL = timedelta(minutes=30)
REFRESH_TTL = timedelta(hours=8)


def to_ms(moment: datetime) -> int:
    """Whole milliseconds since the epoch: the unit used to compare token ages."""
    return round(moment.timestamp() * 1000)


def truncate_ms(moment: datetime) -> datetime:
    """`moment` cut to whole milliseconds, for storing in users.tokens_valid_after."""
    return moment.replace(microsecond=moment.microsecond - moment.microsecond % 1000)


def issued_before(claims: TokenClaims, valid_after: datetime | None) -> bool:
    """True if the token predates users.tokens_valid_after (and must be rejected).
    Compared in integer milliseconds so float rounding cannot shift the result."""
    return valid_after is not None and to_ms(claims.issued_at) < to_ms(valid_after)


class TokenError(Exception):
    """The token is missing, malformed, expired, of the wrong type or tampered with."""


@dataclass(frozen=True)
class TokenClaims:
    user_id: int
    token_type: str          # "access" or "refresh"
    jti: str
    issued_at: datetime
    expires_at: datetime
    mfa: bool


def _encode(secret: str, user_id: int, token_type: str, mfa: bool, now: datetime, expires: datetime) -> str:
    payload = {
        "sub": str(user_id),
        "typ": token_type,
        "jti": secrets.token_urlsafe(16),
        "iat": to_ms(now) / 1000,   # millisecond precision (RFC 7519 allows fractional NumericDate)
        "exp": int(expires.timestamp()),
        "iss": ISSUER,
        "aud": AUDIENCE,
        "mfa": mfa,
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def issue_pair(secret: str, user_id: int, mfa: bool, refresh_expires: datetime | None = None,
               now: datetime | None = None) -> tuple[str, str]:
    """Return (access_token, refresh_token). Pass `refresh_expires` when rotating,
    so the session keeps its original 8-hour limit."""
    now = now or datetime.now(UTC)
    refresh_expires = refresh_expires or now + REFRESH_TTL
    access_expires = min(now + ACCESS_TTL, refresh_expires)
    return (_encode(secret, user_id, "access", mfa, now, access_expires),
            _encode(secret, user_id, "refresh", mfa, now, refresh_expires))


def decode(secret: str, token: str, expected_type: str) -> TokenClaims:
    """Validate signature, algorithm, expiry, issuer, audience and type."""
    try:
        payload = jwt.decode(
            token, secret, algorithms=[ALGORITHM], audience=AUDIENCE, issuer=ISSUER,
            options={"require": ["sub", "typ", "jti", "iat", "exp", "iss", "aud"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("expired") from exc
    except jwt.PyJWTError as exc:
        raise TokenError("invalid") from exc
    if payload.get("typ") != expected_type:
        raise TokenError("wrong token type")
    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError) as exc:
        raise TokenError("invalid subject") from exc
    return TokenClaims(
        user_id=user_id,
        token_type=payload["typ"],
        jti=str(payload["jti"]),
        issued_at=datetime.fromtimestamp(payload["iat"], UTC),
        expires_at=datetime.fromtimestamp(payload["exp"], UTC),
        mfa=bool(payload.get("mfa", False)),
    )
