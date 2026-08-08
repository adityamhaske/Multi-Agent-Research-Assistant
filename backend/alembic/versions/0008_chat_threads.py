"""Project-scoped chat threads (docs/14 §3, §7).

Chat stops being bound to a single report. A thread belongs to a *project* and reads that
project's memory, while the existing per-report chat keeps working exactly as it does
today — that compatibility is a Definition of Done item (docs/14 §9), so this migration
widens the table rather than replacing it:

- `chat_messages.thread_id` is added, nullable.
- `chat_messages.session_id` is *relaxed* to nullable. Existing rows keep theirs and
  remain per-report chat; new project-thread messages carry a `thread_id` instead.
- A CHECK enforces exactly one of the two. Without it, "nullable both" quietly permits an
  orphan message belonging to neither conversation, and the first sign of it would be a
  message that never appears in any history.

Revision ID: 0008_chat_threads
Revises: 0007_memory_chunks
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008_chat_threads"
down_revision: str | None = "0007_memory_chunks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ONE_OF = "(session_id IS NOT NULL) <> (thread_id IS NOT NULL)"


def upgrade() -> None:
    op.create_table(
        "chat_threads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_message_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    # The project sidebar's query: this project's threads, most recently used first.
    op.create_index(
        "ix_chat_threads_project_last_message",
        "chat_threads",
        ["project_id", sa.text("last_message_at DESC")],
    )

    op.add_column(
        "chat_messages",
        sa.Column(
            "thread_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat_threads.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index("ix_chat_messages_thread_created", "chat_messages", ["thread_id", "created_at"])
    # Which reports an answer cited, resolved at write time. Storing it means the chips
    # still resolve when the history is re-read, without re-running retrieval.
    op.add_column("chat_messages", sa.Column("citations", postgresql.JSONB(), nullable=True))

    # Legacy rows all have a session_id, so this widening is safe on a populated table.
    op.alter_column("chat_messages", "session_id", existing_type=postgresql.UUID(), nullable=True)
    # Bare name: the metadata naming convention renders it as
    # `ck_chat_messages_one_parent`. Passing the full name here would double the prefix.
    op.create_check_constraint("one_parent", "chat_messages", _ONE_OF)


def downgrade() -> None:
    op.drop_constraint("ck_chat_messages_one_parent", "chat_messages", type_="check")
    # Thread messages have no session to belong to, so they cannot survive the narrowing.
    op.execute("DELETE FROM chat_messages WHERE session_id IS NULL")
    op.alter_column("chat_messages", "session_id", existing_type=postgresql.UUID(), nullable=False)
    op.drop_index("ix_chat_messages_thread_created", table_name="chat_messages")
    op.drop_column("chat_messages", "citations")
    op.drop_column("chat_messages", "thread_id")
    op.drop_index("ix_chat_threads_project_last_message", table_name="chat_threads")
    op.drop_table("chat_threads")
