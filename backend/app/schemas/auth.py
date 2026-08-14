from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, EmailStr, Field, field_validator

from app.services.passwords import MIN_LENGTH


class RegisterRequest(BaseModel):
    email: EmailStr
    # Policy enforced in the service (breached-list + byte limit); length floor here.
    password: str = Field(min_length=MIN_LENGTH, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: UUID
    email: str
    is_active: bool
    created_at: datetime

    # ── Profile ────────────────────────────────────────────────────────────────
    display_name: str | None = None
    avatar_url: str | None = None
    monthly_token_limit: int = 0

    # ── BYOK status (never the key itself) ─────────────────────────────────────
    api_key_provider: str | None = None
    api_key_base_url: str | None = None
    api_key_hint: str | None = None
    api_key_set_at: datetime | None = None

    model_config = {"from_attributes": True}


class ProfileUpdate(BaseModel):
    """Editable profile fields. Omitted fields are left unchanged."""

    model_config = {"str_strip_whitespace": True}

    display_name: str | None = Field(default=None, max_length=80)
    avatar_url: str | None = Field(default=None, max_length=2000)
    monthly_token_limit: int | None = Field(default=None, ge=0)

    @field_validator("avatar_url")
    @classmethod
    def avatar_must_be_http(cls, v: str | None) -> str | None:
        """Avatars are rendered in an <img>; only allow http(s) so a javascript:
        or data: URL can't be stored and echoed back into the page."""
        if v is None or v == "":
            return None
        if not v.startswith(("http://", "https://")):
            raise ValueError("Avatar URL must start with http:// or https://")
        return v


class PasswordChangeRequest(BaseModel):
    """Change the account password. Proving knowledge of the current one is what
    stops a stolen session cookie from being escalated into a permanent takeover."""

    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=MIN_LENGTH, max_length=200)


class ApiKeyRequest(BaseModel):
    """User-supplied provider key (BYOK). Stored encrypted, never returned."""

    model_config = {"str_strip_whitespace": True}

    provider: Literal["google", "anthropic", "openai", "openrouter", "custom"]
    api_key: str = Field(min_length=8, max_length=500)
    api_base_url: AnyHttpUrl | None = Field(default=None)


class UsageWindow(BaseModel):
    tokens_input: int = 0
    tokens_output: int = 0
    tokens_total: int = 0
    cost_usd: float = 0.0
    sessions: int = 0


class UsageResponse(BaseModel):
    """Token/cost usage for the profile page (docs/07)."""

    month: UsageWindow  # current calendar month — the window the limit applies to
    week: UsageWindow  # rolling 7 days
    last_session: UsageWindow  # most recent session only
    monthly_token_limit: int = 0  # 0 = unlimited
    limit_remaining: int | None = None  # None when unlimited
    limit_reached: bool = False
