"""
Password hashing (SEC-04) and password policy (SEC-05).

Hashing uses argon2id (DECISIONS.md D-025) with argon2-cffi's RFC 9106 "low memory"
profile (time cost 3, 64 MiB, parallelism 4), which is stronger than OWASP's
minimum for argon2id. Plaintext passwords are never stored, logged or returned.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_LENGTH = 12
MAX_LENGTH = 128  # bounds hashing work per request; generous for passphrases
COMMON_PASSWORDS_FILE = Path(__file__).resolve().parent / "data" / "common_passwords_10k.txt"

_hasher = PasswordHasher()  # argon2id, RFC 9106 low-memory profile


def hash_password(password: str) -> str:
    """Return an argon2id hash (salt and parameters are encoded in the string)."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """True if the password matches. Never raises for a wrong password or a malformed hash."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True if the hash was made with weaker parameters than the current ones."""
    return _hasher.check_needs_rehash(password_hash)


@lru_cache
def dummy_hash() -> str:
    """A real hash of a random value. Verifying against it costs the same time as a
    real login, so an unknown email is not detectable by timing (SEC-06)."""
    import secrets

    return hash_password(secrets.token_urlsafe(32))


@lru_cache
def common_passwords() -> frozenset[str]:
    """The bundled top-10,000 list (backend/app/data/README.md), lower-cased."""
    lines = COMMON_PASSWORDS_FILE.read_text(encoding="utf-8").splitlines()
    return frozenset(line.strip().lower() for line in lines if line.strip())


def policy_violations(password: str, username: str = "", email: str = "") -> list[str]:
    """User-facing reasons the password is not acceptable; empty list means it passes."""
    problems: list[str] = []
    if len(password) < MIN_LENGTH:
        problems.append(f"Use at least {MIN_LENGTH} characters.")
    if len(password) > MAX_LENGTH:
        problems.append(f"Use at most {MAX_LENGTH} characters.")
    lowered = password.lower()
    if lowered in common_passwords():
        problems.append("This password is too common. Choose something less predictable.")
    personal = {username.lower(), email.lower(), email.split("@")[0].lower()} - {""}
    if any(len(p) >= 3 and p in lowered for p in personal):
        problems.append("Do not include your username or email address in your password.")
    return problems
