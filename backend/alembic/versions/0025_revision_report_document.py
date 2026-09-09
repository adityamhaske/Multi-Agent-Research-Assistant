"""Store a typed view of each report revision alongside its Markdown.

One nullable JSON column, and nothing else moves. `report_markdown` stays the model's own
bytes and `report_hash` stays `sha256(report_markdown)`, so `reviews.reviewed_hash`,
`research_artifacts.artifact_hash` and the bundle verifier's approval-chain check all pin
exactly what they pinned before — every artifact approved before this migration verifies
byte-for-byte after it.

Existing revisions keep NULL. No backfill: a document derived now would be derived by
today's parser from a report written by an older synthesizer, and stamping that onto a
historical revision would assert a structure nobody observed at the time.

Revision ID: 0025_revision_report_document
Revises: 0024_run_corpus_snapshot
"""

import sqlalchemy as sa
from alembic import op

revision = "0025_revision_report_document"
down_revision = "0024_run_corpus_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("revisions", sa.Column("report_document", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("revisions", "report_document")
