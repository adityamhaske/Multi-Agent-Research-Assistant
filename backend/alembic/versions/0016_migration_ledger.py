"""import ledger (superseded by 0021)

The audit record of the one-shot tool that brought session-pipeline research into the
research domain tables: one row per session considered, where absence meant "not
processed" and never "empty".

**Dropped again in `0021_run_evidence_outcome`**, which moves the one fact the product
actually read — whether a run's evidence was recovered — onto `research_runs` itself,
where it covers every run rather than only imported ones. This revision stays because the
chain does; a deployment that upgrades straight past it creates and drops the table in the
same session, which is correct and cheap.

Revision ID: 0016_migration_ledger
Revises: eafdf189af24
Create Date: 2026-08-17
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0016_migration_ledger"
down_revision: Union[str, None] = "eafdf189af24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "migration_ledger",
        # The session id IS the identity: a second import pass finds the existing
        # row rather than writing a competing terminal outcome.
        sa.Column("session_id", sa.Uuid().with_variant(sa.UUID(), "postgresql"), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("v2_run_id", sa.Uuid().with_variant(sa.UUID(), "postgresql"), nullable=True),
        sa.Column("failure_category", sa.String(length=48), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("evidence_outcome", sa.String(length=24), nullable=True),
        sa.Column("revision_outcome", sa.String(length=24), nullable=True),
        sa.Column("artifact_outcome", sa.String(length=24), nullable=True),
        sa.Column("bundle_result", sa.String(length=24), nullable=True),
        sa.Column("rows_written", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("session_id"),
        sa.UniqueConstraint("session_id", name="uq_ledger_session"),
    )
    # No foreign key to `sessions`, deliberately: the ledger must survive the deletion of
    # the row it describes, for the same reason `audit_events` has no FK to its subject
    # An import record that vanishes with its session cannot answer "what
    # happened to that run?", which is the only question it exists to answer.


def downgrade() -> None:
    op.drop_table("migration_ledger")
