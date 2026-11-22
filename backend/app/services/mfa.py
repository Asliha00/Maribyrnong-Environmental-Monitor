"""
TOTP multi-factor authentication for administrators (SEC-07).

* Secrets are encrypted at rest with Fernet (AES-128-CBC + HMAC-SHA256) before they
  reach `users.mfa_secret_encrypted`. MFA_ENCRYPTION_KEY may hold several
  comma-separated keys, newest first (MultiFernet), so the key can be rotated
  without locking administrators out (docs/security/secret_rotation.md).
* A code is accepted for the current 30-second step or one step either side (clock
  drift), and each step can be used once: `users.mfa_last_used_step` must increase.
"""
from __future__ import annotations

import base64
import hmac
import os
import time

import pyotp
import segno
from cryptography.fernet import Fernet, MultiFernet

ISSUER_NAME = "Maribyrnong Environmental Monitor"
STEP_SECONDS = 30
DRIFT_STEPS = 1


def cipher(key_setting: str) -> MultiFernet:
    """MultiFernet from 'newest_key,older_key,...'. Encrypts with the first key."""
    keys = [k.strip() for k in key_setting.split(",") if k.strip()]
    return MultiFernet([Fernet(k.encode()) for k in keys])


def new_secret() -> str:
    return pyotp.random_base32()


def encrypt_secret(key_setting: str, secret: str) -> str:
    return cipher(key_setting).encrypt(secret.encode()).decode()


def decrypt_secret(key_setting: str, token: str) -> str:
    return cipher(key_setting).decrypt(token.encode()).decode()


def issuer_name(vercel_env: str | None = None) -> str:
    """Name shown in the authenticator app. Production and Preview have separate accounts with
    the same email, so non-production entries carry the environment and cannot be mixed up."""
    env = vercel_env if vercel_env is not None else os.environ.get("VERCEL_ENV", "")
    if not env:   # not on Vercel, or the variable is not exposed: never mislabel production
        env = "production" if os.environ.get("ENVIRONMENT") == "production" else "development"
    return ISSUER_NAME if env == "production" else f"Maribyrnong Monitor ({env.capitalize()})"


def provisioning(secret: str, account_name: str) -> tuple[str, str]:
    """(otpauth URI, QR code as an SVG data URI) for an authenticator app."""
    uri = pyotp.TOTP(secret).provisioning_uri(name=account_name, issuer_name=issuer_name())
    svg = segno.make(uri, error="m").svg_inline(scale=5, dark="#000", light="#fff")
    return uri, "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def matching_step(secret: str, code: str, last_used_step: int | None, now: float | None = None) -> int | None:
    """The time step this code belongs to, or None if it is wrong, too old, or already used."""
    if not (len(code) == 6 and code.isdigit()):
        return None
    totp = pyotp.TOTP(secret)
    current = int((now if now is not None else time.time()) // STEP_SECONDS)
    for step in range(current - DRIFT_STEPS, current + DRIFT_STEPS + 1):
        if hmac.compare_digest(totp.at(step * STEP_SECONDS), code):
            if last_used_step is not None and step <= last_used_step:
                return None   # replay of a code already used
            return step
    return None
