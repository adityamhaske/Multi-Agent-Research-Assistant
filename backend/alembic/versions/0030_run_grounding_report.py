"""Record a selected-files run's claim-level grounding report.

One nullable JSON column, no backfill: runs before 3.1 were never validated claim by claim,
and NULL says so rather than inventing a record (internal/rfcs/V3.1-corpus-scope.md §9.6).
Additive, so a 3.0.x server ignores it.

Revision ID: 0030_run_grounding_report
Revises: 0029_run_offline
"""

import sqlalchemy as sa
from alembic import op

revision = "0030_run_grounding_report"
down_revision = "0029_run_offline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("research_runs", sa.Column("grounding_report", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("research_runs", "grounding_report")
