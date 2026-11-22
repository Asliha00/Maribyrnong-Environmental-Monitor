"""
Single-use 2FA recovery codes for administrators (SEC-07, DECISIONS.md D-037).

A recovery code replaces the 6-digit authenticator code, never the password, so a sign-in
still needs two factors. It is a NIST SP 800-63B "look-up secret":

* 10 codes per set, each 16 characters of Crockford base32 (no I, L, O or U; typed
  O/I/L are read as 0/1/1), shown as XXXX-XXXX-XXXX-XXXX. The first 4 characters are a selector that only finds the
  row; the other 12 (60 bits from `secrets`) are the secret.
* Only an argon2id hash of the secret is stored (salted, slow: NIST requires this for
  secrets under 112 bits). Thanks to the selector, checking a code costs one hash.
* A code is marked used by a conditional UPDATE (`used_at IS NULL`), so two simultaneous
  attempts cannot both succeed. Codes are never deleted: used and replaced codes keep
  their timestamps, and app_user may update only those two columns (02_security.sql).
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime

from ..db import Transaction
from ..passwords import dummy_hash, hash_password, verify_password

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"   # Crockford base32: 32 symbols, no I/L/O/U
LOOK_ALIKES = str.maketrans("OIL", "011")       # what people mistype, read as intended
CODES_PER_SET = 10
SELECTOR_LEN = 4
SECRET_LEN = 12                                   # 12 x 5 bits = 60 bits
LOW_WARNING = 3                                   # tell the admin when this few remain


def _random(n: int) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(n))


def format_code(raw: str) -> str:
    return "-".join(raw[i:i + 4] for i in range(0, len(raw), 4))


def normalise(code: str) -> str | None:
    """Upper-case, drop spaces and hyphens, read O/I/L as 0/1/1. None if it cannot be a code."""
    raw = re.sub(r"[\s-]", "", code).upper().translate(LOOK_ALIKES)
    if len(raw) != SELECTOR_LEN + SECRET_LEN or any(c not in ALPHABET for c in raw):
        return None
    return raw


def remaining(tx: Transaction, user_id: int) -> int:
    row = tx.fetch_one("SELECT COUNT(*) AS n FROM mfa_recovery_codes WHERE user_id = ? "
                      "AND used_at IS NULL AND revoked_at IS NULL", (user_id,))
    return int(row["n"])


def revoke_all(tx: Transaction, user_id: int, now: datetime) -> int:
    """Cancel every unused code of this user (new set, or 2FA reset)."""
    return tx.execute("UPDATE mfa_recovery_codes SET revoked_at = ? WHERE user_id = ? "
                      "AND used_at IS NULL AND revoked_at IS NULL", (now, user_id))


def replace_set(tx: Transaction, user_id: int, now: datetime) -> list[str]:
    """Cancel the old codes and store a new set. Returns the codes in readable form; this is
    the only time they exist outside the user's own copy."""
    revoke_all(tx, user_id, now)
    selectors: set[str] = set()
    codes: list[str] = []
    while len(codes) < CODES_PER_SET:
        selector = _random(SELECTOR_LEN)
        if selector in selectors:          # unique within the set, so one code = one row
            continue
        selectors.add(selector)
        secret = _random(SECRET_LEN)
        tx.execute("INSERT INTO mfa_recovery_codes (user_id, selector, code_hash, created_at) VALUES (?, ?, ?, ?)",
                   (user_id, selector, hash_password(secret), now))
        codes.append(format_code(selector + secret))
    return codes


def consume(tx: Transaction, user_id: int, code: str, now: datetime) -> bool:
    """Use one code. True only if it is valid, unused and not replaced, and this call
    marked it used. A wrong code costs the same hashing work as a right one."""
    raw = normalise(code)
    rows = tx.fetch_all(
        "SELECT code_id, code_hash FROM mfa_recovery_codes WHERE user_id = ? AND selector = ? "
        "AND used_at IS NULL AND revoked_at IS NULL",
        (user_id, raw[:SELECTOR_LEN] if raw else ""))
    if not rows:
        verify_password(dummy_hash(), raw or "x")   # same timing as a selector hit
        return False
    secret = raw[SELECTOR_LEN:]
    for row in rows:
        if verify_password(row["code_hash"], secret):
            marked = tx.execute("UPDATE mfa_recovery_codes SET used_at = ? WHERE code_id = ? "
                                "AND used_at IS NULL AND revoked_at IS NULL", (now, row["code_id"]))
            return marked == 1
    return False
