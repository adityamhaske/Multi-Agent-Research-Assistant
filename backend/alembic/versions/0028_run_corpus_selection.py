"""Record the frozen selection of a selected-files run.

One nullable JSON column, no backfill. A run created before selections existed read the
whole corpus of its project, and NULL says exactly that; inventing a selection for it would
claim a restriction that never applied (internal/rfcs/V3.1-corpus-scope.md §7.2).

Additive and nullable, so a 3.0.x server ignores it and the downgrade drops it cleanly.

Revision ID: 0028_run_corpus_selection
Revises: 0027_run_prompt_provenance
"""

import sqlalchemy as sa
from alembic import op

revision = "0028_run_corpus_selection"
down_revision = "0027_run_prompt_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("research_runs", sa.Column("corpus_selection", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("research_runs", "corpus_selection")
