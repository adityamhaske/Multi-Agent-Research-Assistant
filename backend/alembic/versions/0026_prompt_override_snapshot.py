"""Freeze each run's prompt overrides onto its row, and record when a path ignored them.

Three nullable/defaulted columns, no backfill, nothing existing rewritten. A run that
finished before this migration ran on the shipped prompts — that is a fact about it, not a
gap — so `prompt_overrides_status` stays NULL there rather than being stamped `NONE`, which
would assert that a resolver nobody ran had looked and found nothing.

`effective_prompt_overrides` is a snapshot for the same reason `model_routing` is: a report
has to stay attributable to the configuration that wrote it, and resume must reconstruct
the interrupted run rather than whatever the owner's preferences say by then.

`sessions.prompt_overrides_not_applied` records the legacy path's honest answer. Sessions
do not apply overrides and are not gaining that; a run whose owner configured one is told
so rather than left looking like it complied.

Revision ID: 0026_prompt_override_snapshot
Revises: 0025_revision_report_document
"""

import sqlalchemy as sa
from alembic import op

revision = "0026_prompt_override_snapshot"
down_revision = "0025_revision_report_document"
branch_labels = None
depends_on = None

#: Kept as a literal rather than imported from the model: a migration must keep describing
#: the schema it wrote, and an import would silently re-point it at whatever the vocabulary
#: becomes later.
_STATUSES = "'NONE', 'APPLIED', 'UNUSABLE'"


def upgrade() -> None:
    op.add_column("research_runs", sa.Column("effective_prompt_overrides", sa.JSON(), nullable=True))
    op.add_column("research_runs", sa.Column("prompt_overrides_status", sa.String(16), nullable=True))
    # NULL passes deliberately — it is the value every pre-existing row keeps.
    op.create_check_constraint(
        "ck_run_prompt_overrides_status",
        "research_runs",
        f"prompt_overrides_status IS NULL OR prompt_overrides_status IN ({_STATUSES})",
    )
    op.add_column(
        "sessions",
        sa.Column(
            "prompt_overrides_not_applied",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("sessions", "prompt_overrides_not_applied")
    op.drop_constraint("ck_run_prompt_overrides_status", "research_runs", type_="check")
    op.drop_column("research_runs", "prompt_overrides_status")
    op.drop_column("research_runs", "effective_prompt_overrides")
