from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, EmailStr, Field, field_validator

from app.services.passwords import MIN_LENGTH
from research_engine.prompt_composition import ROLES


class ConnectionVerdict(BaseModel):
    """The API shape of `app.services.provider_health.Verdict` (internal/07 Phase 2a).

    Three states, never a bare boolean (AGENTS.md, "Honest three-state status"): `ok`,
    `degraded` (the server answered but rejected the key / hit quota / had an outage —
    a different fix than "nothing answered"), and `failed` (no response at all).
    """

    state: Literal["ok", "degraded", "failed"]
    reason: str
    checked_at: str
    model_count: int | None = None


class RegisterRequest(BaseModel):
    email: EmailStr
    # Policy enforced in the service (breached-list + byte limit); length floor here.
    password: str = Field(min_length=MIN_LENGTH, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


#: Longest replacement prompt a user may store, per role (scope freeze §7, D-2).
#:
#: 2,500 because the largest prompt this product ships is `SYNTHESIZER_PROMPT_V2` at 2,431
#: characters — a user who cannot write something of comparable length cannot really replace
#: it. Context is not the binding constraint (five roles at this size is ~1.5% of the
#: smallest catalogue context window); bundle size is, which is why the limit is per role and
#: there is deliberately no total across the five.
MAX_PROMPT_OVERRIDE_CHARS = 2500


class UserPreferences(BaseModel):
    """The settings IA's customization surface (internal/07 Phase 3).

    Every field is optional and `None` means "use the default" — the same value
    today's behaviour already produces, so an account that has never touched Settings
    is indistinguishable from one with every preference explicitly set to the default.
    A field declared here with no consumer yet (`density`) is still validated and
    stored now so Settings has somewhere real to write it; it is not decorative, it is
    ahead of the UI that reads it.
    """

    model_config = {"extra": "forbid"}

    retrieval_k: int | None = Field(default=None, ge=1, le=20)
    min_sources_per_task: int | None = Field(default=None, ge=0, le=20)
    snippet_max_chars: int | None = Field(default=None, ge=100, le=500)
    density: Literal["comfortable", "compact"] | None = None
    tavily_api_key: str | None = Field(default=None, max_length=200)
    brave_api_key: str | None = Field(default=None, max_length=200)

    #: Replacement system prompts, one per agent role (scope freeze §7). Absent means the
    #: shipped prompt, which is what every account that never opens the editor gets.
    #:
    #: **Keyed on the five public roles, never on a purpose.** Which of a role's prompts an
    #: override may actually reach is decided by
    #: `research_engine.prompt_composition.is_overridable`, and three of `critic`'s prompts
    #: are protected — so the key space here is the product surface, not the security
    #: boundary. Nothing reads this field yet.
    prompt_overrides: dict[str, str | None] | None = None

    @field_validator("prompt_overrides", mode="before")
    @classmethod
    def _validate_prompt_overrides(cls, value: object) -> object:
        """Reject anything that is not a role a user may edit, with a text they may set.

        Hand-rolled rather than left to the annotation because the two hosts must refuse
        identically: the desktop validates through this same model, and a client that sees
        pydantic's generic message on one host and a named role list on the other has two
        contracts. Every refusal below names what was wrong and what is allowed.
        """
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("prompt_overrides must be an object keyed by agent role")
        for role, text in value.items():
            if role not in ROLES:
                raise ValueError(f"unknown agent role {role!r}; valid roles are {', '.join(ROLES)}")
            if text is None:
                continue  # the documented reset: the role goes back to its shipped prompt
            if not isinstance(text, str):
                raise ValueError(f"prompt override for {role!r} must be a string or null")
            if not text.strip():
                raise ValueError(
                    f"prompt override for {role!r} is empty; send null to reset it to the "
                    "shipped prompt"
                )
            if len(text) > MAX_PROMPT_OVERRIDE_CHARS:
                raise ValueError(
                    f"prompt override for {role!r} is {len(text)} characters; the maximum "
                    f"is {MAX_PROMPT_OVERRIDE_CHARS}"
                )
        return value


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
    api_key_label: str | None = None
    api_key_set_at: datetime | None = None
    # Set only by `PUT /me/api-key` — saving a key tests it in the same request, so the
    # UI never shows a stale "connected" for a key nobody has actually probed since it
    # changed. `None` on every other endpoint returning this schema (internal/07 Phase 2a).
    connection_verdict: ConnectionVerdict | None = None

    preferences: UserPreferences = Field(default_factory=UserPreferences)

    model_config = {"from_attributes": True}

    @field_validator("preferences", mode="before")
    @classmethod
    def preferences_default_when_unset(cls, v: dict | None) -> dict:
        """The ORM column is NULL for every account that has never touched Settings —
        map that to an all-defaults object rather than a validation error, so the
        response always carries a complete, well-formed `preferences`."""
        return v or {}


class ProfileUpdate(BaseModel):
    """Editable profile fields. Omitted fields are left unchanged."""

    model_config = {"str_strip_whitespace": True}

    display_name: str | None = Field(default=None, max_length=80)
    avatar_url: str | None = Field(default=None, max_length=2000)
    monthly_token_limit: int | None = Field(default=None, ge=0)
    # Merged into the stored preferences, not replaced — a page that only exposes the
    # "Research" section must not silently blank "Appearance"'s density choice.
    preferences: UserPreferences | None = None

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


class ApiKeyLabelRequest(BaseModel):
    """Rename the active BYOK connection. Separate from `ApiKeyRequest` on purpose —
    a nickname does not require re-proving the key, and saving one must not re-probe
    the provider (internal/07 Phase 2a's probe is a "test", not a rename)."""

    model_config = {"str_strip_whitespace": True}

    # Blank clears the nickname back to the catalog label ("Custom Endpoint"), the
    # same convention `ProfileUpdate.avatar_url` uses for "unset this".
    label: str | None = Field(default=None, max_length=60)

    @field_validator("label")
    @classmethod
    def blank_clears(cls, v: str | None) -> str | None:
        return v or None


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
