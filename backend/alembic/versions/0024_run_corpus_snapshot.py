"""Record which corpus state a run read.

A run in corpus mode cites `corpus://<version-id>#chars=...`, which resolves to exact bytes
but says nothing about *which corpus* those bytes came from or what state it was in. On the
desktop there was not even a path to name, because one flat corpus serves the whole app. So
"reproduce this research" could not be answered for the airgapped tier at all.

Two nullable columns, no backfill, no constraint: a run that predates this genuinely does
not know, and NULL is the honest record of that. Deliberately not the wider provenance work
— nothing here touches the bundle, which stays at format version 1 so every existing
artifact keeps verifying byte-for-byte.

Revision ID: 0024_run_corpus_snapshot
Revises: 0023_corpus_retrieval_status
"""

from alembic import op
import sqlalchemy as sa

revision = "0024_run_corpus_snapshot"
down_revision = "0023_corpus_retrieval_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("research_runs", sa.Column("corpus_id", sa.Text(), nullable=True))
    op.add_column("research_runs", sa.Column("corpus_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("research_runs", "corpus_version")
    op.drop_column("research_runs", "corpus_id")
