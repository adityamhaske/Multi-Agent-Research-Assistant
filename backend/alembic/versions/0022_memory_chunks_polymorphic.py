"""memory_chunks.source_report_id becomes polymorphic across both run tables

Project memory only ever indexed reports approved through the earlier session pipeline,
because `source_session_id` carried a foreign key to `sessions` and a foreign key can only
point at one table. Every report produced by the current runtime was therefore invisible to
project chat: `memory/status` counted it under "approved" and nothing could ever index it,
so the number of pending reports only grew and the Chat surface answered from nothing.

Same shape and the same trade-off as `0018_agent_logs_polymorphic`: the column identifies
"the report this text came from", there are two tables that can own one, so the reference is
polymorphic and carries no foreign key. Deletion is handled by the ORM relationships on
`Session` and `ResearchRun`, and by the surviving `project_id` cascade, which is what makes
"delete this project removes its memory" true at the database level regardless.

The column is renamed with the constraint drop rather than left as `source_session_id`: a
name that says `session` on a column holding either kind of id is the sort of half-truth
that gets read as a guarantee.

Revision ID: 0022_memory_chunks_polymorphic
Revises: 0021_run_evidence_outcome
Create Date: 2026-08-25
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0022_memory_chunks_polymorphic"
down_revision: Union[str, None] = "0021_run_evidence_outcome"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _fk_names(bind, table: str, referred: str) -> list[str]:
    """Reflected, never hardcoded — `0018` failed on exactly that guess."""
    return [
        fk["name"]
        for fk in sa.inspect(bind).get_foreign_keys(table)
        if fk.get("referred_table") == referred and fk.get("name")
    ]


def upgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("memory_chunks")}
    if "source_session_id" not in columns:
        # Already polymorphic — a database built from the current models by `create_all`.
        return

    names = _fk_names(bind, "memory_chunks", "sessions")
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("memory_chunks", schema=None) as batch:
            for name in names:
                batch.drop_constraint(name, type_="foreignkey")
            batch.alter_column("source_session_id", new_column_name="source_report_id")
        return

    for name in names:
        op.drop_constraint(name, "memory_chunks", type_="foreignkey")
    op.alter_column("memory_chunks", "source_session_id", new_column_name="source_report_id")


def downgrade() -> None:
    # Reinstating the FK fails if any run from the current pipeline has been indexed, which
    # is correct: those rows reference `research_runs`, and the constraint would be a lie.
    op.alter_column("memory_chunks", "source_report_id", new_column_name="source_session_id")
    op.create_foreign_key(
        "fk_memory_chunks_source_session_id_sessions",
        "memory_chunks",
        "sessions",
        ["source_session_id"],
        ["id"],
        ondelete="CASCADE",
    )
