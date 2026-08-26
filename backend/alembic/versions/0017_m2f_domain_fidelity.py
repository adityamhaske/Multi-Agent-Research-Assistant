"""domain fidelity: review target, artifact gate, source recovery, contradiction quotations

Five schema items, as one revision because the first two must not exist apart: relaxing
`reviews.revision_id` without pinning the artifact's gate would let a PLAN approval
authorize a `research_artifacts` row, and "approval is a database fact" is the strongest
property this schema has.

| Item | Change |
|---|---|
| 1 | `reviews.revision_id` nullable + `ck_review_report` — a PLAN review targets a plan |
| 2 | `research_artifacts.review_gate` + composite FK to `reviews(id, decision, gate)` |
| 3 | `sources.citation_index` nullable + partial unique — retrieved is not cited |
| 4 | `contradictions` gains source anchors, quotations and `nature`; pair becomes source-level |
| 5 | `reviews.run_id` + `sequence` — a review belongs to a run and has a position |

**These tables were empty in every environment when this shipped** — they had been created
and nothing wrote them yet — so the NOT NULL columns added here need no backfill and the
`ALTER` path is not exercised against real rows. That is stated rather than assumed: the
upgrade drops and recreates the two constraint-bearing tables' constraints only, and adds
columns as NOT NULL with a server default where the dialect requires one.

Revision ID: 0017_m2f_domain_fidelity
Revises: 0016_migration_ledger
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017_m2f_domain_fidelity"
down_revision: str | None = "0016_migration_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = sa.Uuid().with_variant(sa.UUID(), "postgresql")


def upgrade() -> None:
    bind = op.get_bind()
    sqlite = bind.dialect.name == "sqlite"

    # The artifact FK targets `uq_review_decision`, so Postgres refuses to drop that
    # constraint while the FK exists. Release it first and rebuild it against the wider
    # (id, decision, gate) target below — the window in between is inside one transaction.
    with op.batch_alter_table("research_artifacts", schema=None) as batch:
        batch.drop_constraint("fk_artifact_review", type_="foreignkey")

    # ── S1 + S5: reviews ──────────────────────────────────────────────────────────
    #
    # `batch_alter_table` on both dialects: SQLite cannot ALTER a constraint at all and
    # rebuilds the table, and using the same path on Postgres keeps one code path rather
    # than two that drift (the trap this repository keeps rediscovering).
    with op.batch_alter_table("reviews", schema=None) as batch:
        batch.add_column(sa.Column("run_id", UUID, nullable=False))
        batch.add_column(sa.Column("sequence", sa.Integer(), nullable=False))
        batch.alter_column("revision_id", existing_type=UUID, nullable=True)
        batch.drop_constraint("uq_review_decision", type_="unique")
        batch.create_unique_constraint("uq_review_decision", ["id", "decision", "gate"])
        batch.create_unique_constraint("uq_review_sequence", ["run_id", "sequence"])
        batch.create_check_constraint(
            "ck_review_report", "(gate = 'REPORT') = (revision_id IS NOT NULL)"
        )
        batch.create_check_constraint("ck_review_sequence", "sequence >= 1")
        batch.create_foreign_key(
            "fk_review_run", "research_runs", ["run_id"], ["id"], ondelete="RESTRICT"
        )
    op.create_index("ix_review_run", "reviews", ["run_id", "sequence"])

    # ── S2: research_artifacts ────────────────────────────────────────────────────
    with op.batch_alter_table("research_artifacts", schema=None) as batch:
        batch.add_column(
            sa.Column(
                "review_gate", sa.String(length=8), nullable=False, server_default="REPORT"
            )
        )
        batch.create_foreign_key(
            "fk_artifact_review",
            "reviews",
            ["review_id", "review_decision", "review_gate"],
            ["id", "decision", "gate"],
            ondelete="SET NULL",
        )
        batch.create_check_constraint("ck_artifact_gate", "review_gate = 'REPORT'")

    # ── S3: sources ───────────────────────────────────────────────────────────────
    with op.batch_alter_table("sources", schema=None) as batch:
        batch.alter_column("citation_index", existing_type=sa.Integer(), nullable=True)
        batch.drop_constraint("uq_source_index", type_="unique")
        batch.drop_constraint("ck_source_cidx", type_="check")
        batch.create_check_constraint(
            "ck_source_cidx", "citation_index IS NULL OR citation_index >= 1"
        )
    # Partial, so many uncited sources may coexist in one run. Both dialects take the same
    # `postgresql_where`/`sqlite_where` pair — omitting one makes the index total there.
    op.create_index(
        "uq_source_index",
        "sources",
        ["run_id", "citation_index"],
        unique=True,
        postgresql_where=sa.text("citation_index IS NOT NULL"),
        sqlite_where=sa.text("citation_index IS NOT NULL"),
    )

    # ── S4: contradictions ────────────────────────────────────────────────────────
    with op.batch_alter_table("contradictions", schema=None) as batch:
        batch.add_column(sa.Column("source_a_id", UUID, nullable=True))
        batch.add_column(sa.Column("source_b_id", UUID, nullable=True))
        batch.add_column(sa.Column("quote_a", sa.Text(), nullable=True))
        batch.add_column(sa.Column("quote_b", sa.Text(), nullable=True))
        batch.add_column(sa.Column("nature", sa.Text(), nullable=True))
        batch.drop_constraint("ck_contra_pair", type_="check")
        batch.create_check_constraint(
            "ck_contra_pair",
            "(detection_state = 'DETECTED') = "
            "(source_a_id IS NOT NULL AND source_b_id IS NOT NULL)",
        )
        batch.create_check_constraint(
            "ck_contra_refine", "(evidence_a_id IS NULL) = (evidence_b_id IS NULL)"
        )
        batch.create_check_constraint(
            "ck_contra_src_distinct", "source_a_id IS NULL OR source_a_id <> source_b_id"
        )
        batch.create_foreign_key(
            "fk_contra_src_a",
            "sources",
            ["source_a_id", "run_id"],
            ["id", "run_id"],
            ondelete="CASCADE",
        )
        batch.create_foreign_key(
            "fk_contra_src_b",
            "sources",
            ["source_b_id", "run_id"],
            ["id", "run_id"],
            ondelete="CASCADE",
        )

    if not sqlite:
        # The server default existed only to make the NOT NULL column addable; the
        # application always supplies the value.
        op.alter_column("research_artifacts", "review_gate", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("contradictions", schema=None) as batch:
        batch.drop_constraint("fk_contra_src_b", type_="foreignkey")
        batch.drop_constraint("fk_contra_src_a", type_="foreignkey")
        batch.drop_constraint("ck_contra_src_distinct", type_="check")
        batch.drop_constraint("ck_contra_refine", type_="check")
        batch.drop_constraint("ck_contra_pair", type_="check")
        batch.create_check_constraint(
            "ck_contra_pair",
            "(detection_state = 'DETECTED') = "
            "(evidence_a_id IS NOT NULL AND evidence_b_id IS NOT NULL)",
        )
        for column in ("nature", "quote_b", "quote_a", "source_b_id", "source_a_id"):
            batch.drop_column(column)

    op.drop_index("uq_source_index", table_name="sources")
    with op.batch_alter_table("sources", schema=None) as batch:
        batch.drop_constraint("ck_source_cidx", type_="check")
        batch.create_check_constraint("ck_source_cidx", "citation_index >= 1")
        batch.create_unique_constraint("uq_source_index", ["run_id", "citation_index"])
        batch.alter_column("citation_index", existing_type=sa.Integer(), nullable=False)

    with op.batch_alter_table("research_artifacts", schema=None) as batch:
        batch.drop_constraint("ck_artifact_gate", type_="check")
        batch.drop_constraint("fk_artifact_review", type_="foreignkey")
        batch.drop_column("review_gate")

    op.drop_index("ix_review_run", table_name="reviews")
    with op.batch_alter_table("reviews", schema=None) as batch:
        batch.drop_constraint("fk_review_run", type_="foreignkey")
        batch.drop_constraint("ck_review_sequence", type_="check")
        batch.drop_constraint("ck_review_report", type_="check")
        batch.drop_constraint("uq_review_sequence", type_="unique")
        batch.drop_constraint("uq_review_decision", type_="unique")
        batch.create_unique_constraint("uq_review_decision", ["id", "decision"])
        batch.alter_column("revision_id", existing_type=UUID, nullable=False)
        batch.drop_column("sequence")
        batch.drop_column("run_id")

    with op.batch_alter_table("research_artifacts", schema=None) as batch:
        batch.create_foreign_key(
            "fk_artifact_review",
            "reviews",
            ["review_id", "review_decision"],
            ["id", "decision"],
            ondelete="SET NULL",
        )
