"""Record whether a run asked for the Offline guarantee.

A boolean with a server default of false, so every existing run reads as "not Offline",
which is what it was: before this column there was no Offline guarantee to ask for
(internal/rfcs/V3.1-corpus-scope.md §6.2, §7.2). Additive, so a 3.0.x server ignores it.

Revision ID: 0029_run_offline
Revises: 0028_run_corpus_selection
"""

import sqlalchemy as sa
from alembic import op

revision = "0029_run_offline"
down_revision = "0028_run_corpus_selection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "research_runs",
        sa.Column("offline", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("research_runs", "offline")
