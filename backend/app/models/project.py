"""
Projects — the container a user's research lives in (docs/14 §3).

A project owns sessions today and will own chat threads and memory in M17. Deleting
one deletes the research inside it, which is why the API treats it as a destructive
action rather than a tidy-up.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.types import UuidType


class Project(Base):
    __tablename__ = "projects"
    # Names are unique per user. "Thesis" and "thesis" as two separate projects would be
    # a UI trap rather than a feature, so the migration enforces this case-insensitively
    # with a functional index; this constraint documents the intent on the model.
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_projects_user_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Same reversible-vs-destructive split as sessions: archive hides, delete removes.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    sessions: Mapped[list["Session"]] = relationship(  # noqa: F821
        "Session",
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="select",
    )
    # Memory follows the project it belongs to. The database enforces this too (0007's
    # ON DELETE CASCADE); "no orphan vectors after a delete" is a DoD item, so it is
    # guaranteed in both layers rather than trusted to either.
    memory_chunks: Mapped[list["MemoryChunk"]] = relationship(  # noqa: F821
        "MemoryChunk",
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="select",
    )
    chat_threads: Mapped[list["ChatThread"]] = relationship(  # noqa: F821
        "ChatThread",
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<Project id={self.id} name={self.name!r}>"
