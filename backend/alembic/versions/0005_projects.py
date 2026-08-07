"""Projects as containers for research (docs/14 §3, §7).

Three-phase so it is safe on a database that already holds research:

1. create `projects`,
2. add `sessions.project_id` as NULLABLE, then backfill every existing session into a
   per-user "General" project,
3. only then set the column NOT NULL.

Doing it in one shot would fail on any non-empty `sessions` table. Each phase is
idempotent (IF NOT EXISTS / ON CONFLICT / WHERE NULL) so a half-applied run can be
re-run rather than hand-repaired.

Revision ID: 0005_projects
Revises: 0004_session_archive
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_projects"
down_revision: str | None = "0004_session_archive"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_PROJECT_NAME = "General"


def upgrade() -> None:
    # ── Phase 1: the container ────────────────────────────────────────────────────
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_projects_user_id", "projects", ["user_id"])
    # Case-insensitive uniqueness per user: "Thesis" and "thesis" must not coexist.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_projects_user_name "
        "ON projects (user_id, lower(name))"
    )

    # ── Phase 2: nullable column, then backfill ───────────────────────────────────
    op.add_column("sessions", sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True))

    # One "General" project per user that actually owns sessions. gen_random_uuid() is
    # built in from Postgres 13, so no extension is required.
    op.execute(
        f"""
        INSERT INTO projects (id, user_id, name, description)
        SELECT gen_random_uuid(), u.id, '{DEFAULT_PROJECT_NAME}',
               'Research created before projects existed.'
        FROM users u
        WHERE EXISTS (SELECT 1 FROM sessions s WHERE s.user_id = u.id)
        ON CONFLICT DO NOTHING
        """
    )

    # Move every orphan session into its owner's General project.
    op.execute(
        f"""
        UPDATE sessions s
        SET project_id = p.id
        FROM projects p
        WHERE p.user_id = s.user_id
          AND lower(p.name) = lower('{DEFAULT_PROJECT_NAME}')
          AND s.project_id IS NULL
        """
    )

    # ── Phase 3: enforce the invariant ────────────────────────────────────────────
    op.alter_column("sessions", "project_id", nullable=False)
    op.create_foreign_key(
        "fk_sessions_project_id",
        "sessions",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_sessions_project_id", "sessions", ["project_id"])
    # The hot History query is now "this project, active, newest first".
    op.create_index(
        "ix_sessions_project_active",
        "sessions",
        ["project_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("archived_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_sessions_project_active", table_name="sessions")
    op.drop_index("ix_sessions_project_id", table_name="sessions")
    op.drop_constraint("fk_sessions_project_id", "sessions", type_="foreignkey")
    op.drop_column("sessions", "project_id")
    op.execute("DROP INDEX IF EXISTS uq_projects_user_name")
    op.drop_index("ix_projects_user_id", table_name="projects")
    op.drop_table("projects")
