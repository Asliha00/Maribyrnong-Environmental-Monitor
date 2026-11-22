"""Start-up settings validation (SEC-02, SEC-14, SEC-16, SEC-25)."""
import pytest
from pydantic import ValidationError

NEON_POOLED = "ep-test-123-pooler.ap-southeast-2.aws.neon.tech/neondb"
STRONG_PW = "Zq8vR3nT6yW1bX4m"


def test_valid_settings_load(make_settings):
    settings = make_settings()
    assert settings.environment == "test"
    assert not settings.uses_postgres


def test_backend_refuses_insecure_db_url(make_settings):
    """SEC-02: a remote URL without sslmode=require must stop start-up."""
    with pytest.raises(ValidationError, match="sslmode"):
        make_settings(app_database_url=f"postgresql://app_user:{STRONG_PW}@{NEON_POOLED}")


def test_backend_refuses_sslmode_disable(make_settings):
    with pytest.raises(ValidationError, match="sslmode"):
        make_settings(app_database_url=f"postgresql://app_user:{STRONG_PW}@{NEON_POOLED}?sslmode=disable")


@pytest.mark.parametrize("user", ["neondb_owner", "postgres", "project_owner"])
def test_backend_refuses_owner_role(make_settings, user):
    """SEC-14: the backend must never connect as a schema owner."""
    with pytest.raises(ValidationError, match="owner role"):
        make_settings(app_database_url=f"postgresql://{user}:{STRONG_PW}@{NEON_POOLED}?sslmode=require")


def test_production_requires_app_user(make_settings):
    with pytest.raises(ValidationError, match="app_user"):
        make_settings(environment="production",
                      app_database_url=f"postgresql://pipeline_user:{STRONG_PW}@{NEON_POOLED}?sslmode=require")


def test_production_requires_database_url(make_settings):
    with pytest.raises(ValidationError, match="APP_DATABASE_URL is required"):
        make_settings(environment="production", app_database_url="")


def test_placeholder_db_url_refused(make_settings):
    """The unedited value from .env.example must not be accepted."""
    url = "postgresql://app_user:PASSWORD@ep-YOUR-ENDPOINT-pooler.ap-southeast-2.aws.neon.tech/neondb?sslmode=require"
    with pytest.raises(ValidationError, match="placeholder"):
        make_settings(app_database_url=url)


def test_secure_app_user_url_accepted(make_settings):
    settings = make_settings(environment="production",
                             app_database_url=f"postgresql://app_user:{STRONG_PW}@{NEON_POOLED}?sslmode=require")
    assert settings.uses_postgres


def test_missing_jwt_secret_fails_startup(make_settings):
    """SEC-16: missing secrets stop start-up."""
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        make_settings(jwt_secret="")


def test_short_jwt_secret_fails_startup(make_settings):
    with pytest.raises(ValidationError, match="at least 32"):
        make_settings(jwt_secret="too-short")


def test_invalid_mfa_key_fails_startup(make_settings):
    with pytest.raises(ValidationError, match="MFA_ENCRYPTION_KEY"):
        make_settings(mfa_encryption_key="not-a-fernet-key")


def test_wildcard_cors_origin_refused(make_settings):
    with pytest.raises(ValidationError, match="never"):
        make_settings(allowed_origins="*")


def test_allowed_origins_parsed_from_comma_list(make_settings):
    settings = make_settings(allowed_origins="http://localhost:5173, http://127.0.0.1:5173")
    assert settings.allowed_origins == ["http://localhost:5173", "http://127.0.0.1:5173"]
