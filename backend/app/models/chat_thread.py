"""
A chat thread scoped to a project (docs/14 §3).

Per-report chat answers questions about one report. A thread answers questions about
everything the project has *approved*, which is the difference between a follow-up and a
research memory. Threads are parallel and independent — the same project can hold one
per line of enquiry.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.types import UuidType

# Titles are derived from the first message rather than asked for: naming a thread before
# writing in it is a chore, and a model call to summarise it would be spend for cosmetics.
TITLE_MAX_CHARS = 60


class ChatThread(Base):
    __tablename__ = "chat_threads"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UuidType,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Ordering key for the thread list — a thread is "recent" when it was last *used*,
    # not when it was created.
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    project: Mapped["Project"] = relationship("Project", back_populates="chat_threads")  # noqa: F821
    messages: Mapped[list["ChatMessage"]] = relationship(  # noqa: F821
        "ChatMessage",
        back_populates="thread",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<ChatThread id={self.id} title={self.title!r}>"


def derive_title(first_message: str) -> str:
    """A thread title from its opening message, truncated on a word boundary."""
    cleaned = " ".join((first_message or "").split()) or "New chat"
    if len(cleaned) <= TITLE_MAX_CHARS:
        return cleaned
    cut = cleaned.rfind(" ", 0, TITLE_MAX_CHARS)
    return cleaned[: cut if cut > TITLE_MAX_CHARS // 2 else TITLE_MAX_CHARS].rstrip() + "…"
