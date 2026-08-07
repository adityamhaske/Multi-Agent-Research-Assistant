"""Archivable sessions.

Adds `sessions.archived_at`. Archiving is reversible and keeps every row; deleting a
session is a separate, hard action handled by the API (and cascades to logs, chat, and
audit rows via existing FKs).

Revision ID: 0004_session_archive
Revises: 0003_model_routing
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_session_archive"
down_revision: str | None = "0003_model_routing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    # The active list is "not archived, newest first" — the hot query for History.
    op.create_index(
        "ix_sessions_user_active",
        "sessions",
        ["user_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("archived_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_sessions_user_active", table_name="sessions")
    op.drop_column("sessions", "archived_at")
