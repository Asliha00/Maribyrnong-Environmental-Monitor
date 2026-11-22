"""
Backend settings, read from environment variables (and `.env` locally).

Start-up fails fast when a secret is missing, still a placeholder, or when the
database URL is insecure or uses the owner role (SEC-02, SEC-14, SEC-16). A
misconfigured deployment therefore refuses to start rather than running unsafely.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse

from cryptography.fernet import Fernet
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from data_pipeline.db import validate_postgres_url

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE_PATH = ROOT / "data" / "processed" / "environment.db"

# Roles that can alter the schema; the app must never connect as one of them.
FORBIDDEN_DB_USERS = {"neondb_owner", "postgres"}
# Fragments that show a value was copied from .env.example and never filled in.
PLACEHOLDER_MARKERS = ("PASSWORD", "YOUR-ENDPOINT", "changeme", "change-me", "<")
MIN_JWT_SECRET_LENGTH = 32


class ConfigError(ValueError):
    """Raised at start-up when the configuration is unsafe or incomplete."""


def _is_placeholder(value: str) -> bool:
    return any(marker.lower() in value.lower() for marker in PLACEHOLDER_MARKERS)


def check_app_database_url(url: str, environment: str) -> None:
    """Refuse database URLs the backend must not use (SEC-02, SEC-14)."""
    validate_postgres_url(url)  # TLS required + no default password (shared with the pipeline)
    if _is_placeholder(url):
        raise ConfigError("APP_DATABASE_URL still contains placeholder values from .env.example.")
    user = urlparse(url).username or ""
    if user in FORBIDDEN_DB_USERS or user.endswith("_owner"):
        raise ConfigError(
            f"APP_DATABASE_URL connects as '{user}', a schema owner role. "
            "The backend must connect as app_user (see database/README.md).")
    if environment == "production" and user != "app_user":
        raise ConfigError("In production the backend must connect as app_user.")


class Settings(BaseSettings):
    """All backend configuration. Field names map to upper-case environment variables."""

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    app_database_url: str = ""
    sqlite_path: Path = DEFAULT_SQLITE_PATH
    jwt_secret: str = ""
    mfa_encryption_key: str = ""
    allowed_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [o.strip() for o in value.split(",") if o.strip()]
        return value

    @model_validator(mode="after")
    def _validate(self) -> Settings:
        if not self.jwt_secret or _is_placeholder(self.jwt_secret):
            raise ConfigError("JWT_SECRET is missing. Generate one with "
                              "python -c \"import secrets; print(secrets.token_urlsafe(48))\"")
        if len(self.jwt_secret) < MIN_JWT_SECRET_LENGTH:
            raise ConfigError(f"JWT_SECRET must be at least {MIN_JWT_SECRET_LENGTH} characters.")
        # One Fernet key, or several comma-separated (newest first) during a rotation
        keys = [k.strip() for k in self.mfa_encryption_key.split(",") if k.strip()]
        try:
            if not keys:
                raise ValueError("empty")
            for key in keys:
                Fernet(key.encode())
        except (ValueError, TypeError) as exc:
            raise ConfigError("MFA_ENCRYPTION_KEY is missing or not a valid Fernet key.") from exc
        if "*" in self.allowed_origins:
            raise ConfigError("ALLOWED_ORIGINS must list explicit origins, never '*' (SEC-25).")
        if self.app_database_url:
            check_app_database_url(self.app_database_url, self.environment)
        elif self.environment == "production":
            raise ConfigError("APP_DATABASE_URL is required in production.")
        return self

    @property
    def uses_postgres(self) -> bool:
        return bool(self.app_database_url)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    """Settings singleton, created on first use."""
    return Settings()
