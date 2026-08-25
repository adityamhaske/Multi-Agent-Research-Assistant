import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.types import JsonType, UuidType


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_pw: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # ── Profile ────────────────────────────────────────────────────────────────
    # The public identity. `id` above is the unique user ID shown in the UI.
    display_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Optional avatar. When absent the UI falls back to derived initials, so this
    # is never required to render a complete profile.
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── BYOK provider key (docs/06 §1) ─────────────────────────────────────────
    # Fernet ciphertext — never plaintext, never returned by any endpoint. The
    # hint is a display-only tail ("…aB3d") so users can tell which key is stored.
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_key_provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    api_key_base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_key_hint: Mapped[str | None] = mapped_column(String(16), nullable=True)
    api_key_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # User-chosen display name for the active connection ("OmniRoute", "Work vLLM") —
    # distinct from `api_key_provider`, which is the fixed catalog label ("Custom
    # Endpoint") and stays the same across every gateway a user ever points it at.
    # NULL means "show the catalog label", the default every account had before this
    # column existed. Cleared alongside the key in `delete_api_key` — a nickname
    # describes a connection that no longer exists once the key is gone.
    api_key_label: Mapped[str | None] = mapped_column(String(60), nullable=True)

    # ── Usage limit ────────────────────────────────────────────────────────────
    # Rolling-month ceiling on total tokens. 0 = unlimited (the default for
    # self-hosted single-user installs).
    monthly_token_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── Model routing (docs/12 M8) ─────────────────────────────────────────────
    # Per-role "provider:model" map, e.g. {"planner": "anthropic:claude-opus-5", …}.
    # NULL means "use the deployment's MODEL_* routing" — the default, and what every
    # existing user keeps until they choose otherwise. Validated against the catalog
    # on write, so an unroutable or unpriced model can never be persisted here.
    model_routing: Mapped[dict | None] = mapped_column(JsonType, nullable=True)

    # ── Research/UI preferences (docs/07 §2, Phase 3) ──────────────────────────
    # Free-form JSON, validated shape-side by `app.schemas.auth.UserPreferences` —
    # a column per setting would mean a migration for every future knob. NULL means
    # "every preference is unset", which every reader treats as "use the default",
    # same convention `model_routing`'s NULL already uses.
    preferences: Mapped[dict | None] = mapped_column(JsonType, nullable=True)

    sessions: Mapped[list["Session"]] = relationship(  # noqa: F821
        "Session",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email}>"
