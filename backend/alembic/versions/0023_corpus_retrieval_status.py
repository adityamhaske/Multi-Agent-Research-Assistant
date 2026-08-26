"""sources.retrieval_status gains CORPUS_DOCUMENT — record_evidence already writes it

`record_evidence` has always written `retrieval_status="CORPUS_DOCUMENT"` for a source whose
URL starts with `corpus://`, and the frontend already renders it as a label
(`SourcesPanel.tsx`). Only `RETRIEVAL_STATUSES` and the `ck_source_ret` CHECK constraint it
generates were never given the member, so the insert was illegal from the day corpus mode
shipped — silent until the first corpus-mode run actually produced evidence and
`record_evidence` raised `IntegrityError` on a value the write path had assumed was valid
all along.

Revision ID: 0023_corpus_retrieval_status
Revises: 0022_memory_chunks_polymorphic
Create Date: 2026-08-26
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0023_corpus_retrieval_status"
down_revision: Union[str, None] = "0022_memory_chunks_polymorphic"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD = ("FETCHED", "SEARCH_RESULT_ONLY", "FAILED", "UNKNOWN")
_NEW = _OLD + ("CORPUS_DOCUMENT",)


def _constraint_sql(values: tuple[str, ...]) -> str:
    return "retrieval_status IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.drop_constraint("ck_source_ret", "sources", type_="check")
    op.create_check_constraint("ck_source_ret", "sources", _constraint_sql(_NEW))


def downgrade() -> None:
    # A row already carrying CORPUS_DOCUMENT makes the old, narrower constraint
    # unsatisfiable — not this migration's call to resolve, so it fails loudly rather than
    # silently deleting or reclassifying real evidence rows.
    op.drop_constraint("ck_source_ret", "sources", type_="check")
    op.create_check_constraint("ck_source_ret", "sources", _constraint_sql(_OLD))
