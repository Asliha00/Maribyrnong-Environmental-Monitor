"""Pydantic request and response models (validated input only, SEC-19)."""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from .variables import MAX_SENSOR_IDS, DeviceFamily, LandUse, Resolution, Variable

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=EMAIL_PATTERN)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class MfaVerifyRequest(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


class UserOut(BaseModel):
    """What the browser may know about the signed-in user: name, email, role (SEC-29)."""
    user_id: int
    username: str
    email: str
    role: str
    permissions: list[str]
    must_change_password: bool
    mfa_enabled: bool
    mfa_required: bool          # this role must use MFA (has a manage_* permission)
    mfa_verified: bool          # this session passed MFA


class LoginResponse(BaseModel):
    user: UserOut
    next_step: str              # "change_password" | "mfa_setup" | "mfa_verify" | "done"


class MfaSetupResponse(BaseModel):
    otpauth_uri: str
    qr_svg_data_uri: str
    manual_entry_key: str


class MfaVerifyResponse(LoginResponse):
    """After the FIRST successful code (enrolment), the new recovery codes, shown once (D-037)."""
    recovery_codes: list[str] | None = None


class RecoveryCodeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)   # XXXX-XXXX-XXXX-XXXX; spaces/case ignored


class RecoveryLoginResponse(LoginResponse):
    recovery_codes_remaining: int


class RecoveryCodesResponse(BaseModel):
    recovery_codes: list[str]


class RecoveryStatusResponse(BaseModel):
    remaining: int
    low: bool


class OkResponse(BaseModel):
    ok: bool = True


class CheckResponse(BaseModel):
    allowed: bool
    permission: str


class ExportRequest(BaseModel):
    """UC3 export: the dashboard's applied filters plus a format. Same allow-lists and bounds
    as GET /api/readings; unknown fields are rejected."""
    model_config = {"extra": "forbid"}

    format: Literal["csv", "pdf"]
    variable: Variable
    resolution: Resolution = "day"
    start: date
    end: date
    land_use: list[LandUse] = Field(default_factory=list, max_length=5)
    sensor_ids: list[Annotated[int, Field(ge=1, le=1_000_000)]] = Field(default_factory=list,
                                                                        max_length=MAX_SENSOR_IDS)
    exclude_flagged: bool = True
    confirm_large: bool = False   # set after the user confirms the >50,000-row warning


# ---------- Administration (Phase 5) ----------
SENSOR_CODE_PATTERN = r"^[A-Z0-9][A-Z0-9-]{1,19}$"
NO_CONTROL_CHARS = r"^[^\x00-\x1f\x7f]+$"


class SensorCreate(BaseModel):
    """Register a sensor (UC5). Coordinates are range-checked against the municipality in the
    router so the UC5 message can be returned; types and lengths are checked here."""
    model_config = {"extra": "forbid"}

    sensor_code: str = Field(pattern=SENSOR_CODE_PATTERN)
    sensor_name: str = Field(min_length=3, max_length=80, pattern=NO_CONTROL_CHARS)
    device_family: DeviceFamily
    land_use: LandUse
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    installation_date: date | None = None
    notes: str | None = Field(default=None, max_length=500, pattern=r"^[^\x00\x7f]*$")
    sensitive_receptor: bool = False   # e.g. childcare, school, aged care (Insights equity lens)

    @field_validator("sensor_name", "notes")
    @classmethod
    def _strip_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class SensorUpdate(BaseModel):
    """Edit a sensor: only the fields sent are changed. Status 'Active' reactivates a
    decommissioned sensor; decommissioning is DELETE (soft)."""
    model_config = {"extra": "forbid"}

    sensor_name: str | None = Field(default=None, min_length=3, max_length=80, pattern=NO_CONTROL_CHARS)
    land_use: LandUse | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    location_verified: bool | None = None
    installation_date: date | None = None
    notes: str | None = Field(default=None, max_length=500, pattern=r"^[^\x00\x7f]*$")
    status: Literal["Active"] | None = None
    sensitive_receptor: bool | None = None

    @field_validator("sensor_name", "notes")
    @classmethod
    def _strip_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


USERNAME_PATTERN = r"^[a-z0-9][a-z0-9_.-]{2,39}$"
# Environmental Analyst, System Administrator (01_schema.sql). Role 1 "General User" is retired
# (D-035): its row stays for old records, but it can no longer be given to anyone.
RoleId = Literal[2, 3]


class UserCreate(BaseModel):
    """Create an account. The system generates the temporary password (shown once)."""
    model_config = {"extra": "forbid"}

    username: str = Field(pattern=USERNAME_PATTERN)
    email: str = Field(min_length=3, max_length=254, pattern=EMAIL_PATTERN)
    role_id: RoleId

    @field_validator("email")
    @classmethod
    def _normalise_email(cls, value: str) -> str:
        return value.strip().lower()


class UserUpdate(BaseModel):
    """Change a user's role and/or activate or deactivate the account."""
    model_config = {"extra": "forbid"}

    role_id: RoleId | None = None
    is_active: bool | None = None


class ThresholdUpdate(BaseModel):
    """New value for a threshold, with the reason (kept in threshold_history, risk R24)."""
    model_config = {"extra": "forbid"}

    value: float = Field(ge=0, le=100_000, allow_inf_nan=False)
    reason: str = Field(min_length=10, max_length=500, pattern=NO_CONTROL_CHARS)

    @field_validator("reason")
    @classmethod
    def _strip_reason(cls, value: str) -> str:
        return value.strip()
