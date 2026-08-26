"""research_runs.evidence_outcome, and the end of the migration ledger

Whether a run's evidence was ever read out of its checkpoint is the difference between a
measured zero and an unmeasured one, and until now only *migrated* runs recorded it — in
`migration_ledger`, written by the one-shot import tool. A run executed by this product
carried the same tri-state through `persist_outcome` and then dropped it into a log line,
so a run whose checkpoint could not be decoded produced a bundle that numbered citations
against an empty evidence table and asserted a quality nobody observed.

The column moves the fact onto the row that owns it. `run_bundle` reads it there, for every
run, instead of consulting a table that only ever had rows on a migrated deployment.

Existing rows backfill to `READ`: every row present at this revision was written by the
native runtime, which only records evidence on the `READ` branch — `NOT_READ` would claim
these runs' evidence was never recovered, which is the opposite of what happened, and the
two failure states would be inventing a fault. The ledger is then dropped; the import tool
it served is gone, and a table nothing reads is a table that misleads.

Revision ID: 0021_run_evidence_outcome
Revises: 0020_api_key_label
Create Date: 2026-08-25
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0021_run_evidence_outcome"
down_revision: Union[str, None] = "0020_api_key_label"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OUTCOMES = ("NOT_READ", "READ", "CHECKPOINT_MISSING", "CHECKPOINT_UNREADABLE")


def upgrade() -> None:
    op.add_column(
        "research_runs",
        sa.Column(
            "evidence_outcome",
            sa.String(length=24),
            nullable=False,
            server_default="READ",
        ),
    )
    # The backfill default was "READ" (see the module docstring); new rows are written
    # explicitly by `persist_outcome`, and the resting default is the honest one.
    op.alter_column("research_runs", "evidence_outcome", server_default="NOT_READ")
    op.create_check_constraint(
        "ck_run_evidence_outcome",
        "research_runs",
        "evidence_outcome IN (" + ", ".join(f"'{v}'" for v in _OUTCOMES) + ")",
    )
    op.drop_table("migration_ledger")


def downgrade() -> None:
    op.create_table(
        "migration_ledger",
        sa.Column("session_id", sa.Uuid(), primary_key=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("v2_run_id", sa.Uuid(), nullable=True),
        sa.Column("failure_category", sa.String(length=48), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("evidence_outcome", sa.String(length=24), nullable=True),
        sa.Column("revision_outcome", sa.String(length=24), nullable=True),
        sa.Column("artifact_outcome", sa.String(length=24), nullable=True),
        sa.Column("bundle_result", sa.String(length=24), nullable=True),
        sa.Column("rows_written", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("session_id", name="uq_ledger_session"),
    )
    op.drop_constraint("ck_run_evidence_outcome", "research_runs", type_="check")
    op.drop_column("research_runs", "evidence_outcome")
