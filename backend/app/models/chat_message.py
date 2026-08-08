import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ChatMessage(Base):
    """One turn of chat, belonging to either a report or a project thread — never both.

    Per-report chat (`session_id`) predates projects and still works unchanged; project
    threads (`thread_id`) arrived with memory in M17. A CHECK constraint in migration
    0008 enforces exactly one parent, because "both nullable" would silently allow a
    message that appears in no history at all.
    """

    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint(
            "(session_id IS NOT NULL) <> (thread_id IS NOT NULL)",
            name="one_parent",  # rendered as ck_chat_messages_one_parent by the convention
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    thread_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_threads.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False)  # 'user' or 'assistant'
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # For thread messages: the reports this answer cited, as [{marker, session_id, title,
    # created_at}]. Resolved at write time so the citation chips still work after the
    # retrieval that produced them is long gone (docs/14 §5).
    citations: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    session: Mapped["Session | None"] = relationship("Session", back_populates="chat_messages")  # noqa: F821
    thread: Mapped["ChatThread | None"] = relationship("ChatThread", back_populates="messages")  # noqa: F821

    def __repr__(self) -> str:
        return f"<ChatMessage id={self.id} role={self.role}>"
