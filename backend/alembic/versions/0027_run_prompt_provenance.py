"""Record the system prompt each purpose actually ran under.

One nullable JSON column, no backfill. A run that finished before this column existed has
no record of what it composed, and nothing can honestly recreate one: re-composing at export
would report what today's code produces, which for a protected purpose is the constant
shipped *now* rather than the one that ran. So historical runs keep NULL and keep emitting
bundle v1 — an absent record, not an invented one.

Only the purposes that executed are stored. Three of the seven research purposes are
conditional (`critic.citation_verify`, `critic.contradiction_detector`, `synthesizer.repair`),
which the frozen scope freeze anticipates by asking for "each applicable purpose".

Revision ID: 0027_run_prompt_provenance
Revises: 0026_prompt_override_snapshot
"""

import sqlalchemy as sa
from alembic import op

revision = "0027_run_prompt_provenance"
down_revision = "0026_prompt_override_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("research_runs", sa.Column("effective_prompt_provenance", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("research_runs", "effective_prompt_provenance")
