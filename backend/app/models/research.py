"""
V2 research domain: the run and everything it gathers (M2B §2.2–2.5, §2.9).

**These tables are created and nothing reads or writes them yet.** M2D builds the database
contract only; dual-write is M2E and reads are later still (`internal/V2_Migration_Plan_M2C.md`).

Two mechanisms carry most of the invariants, and both were chosen because they work
identically on Postgres and SQLite — triggers and column privileges do not, so immutability
is enforced in the application and by the offline verifier instead (M2B §0, §3).

**Composite foreign keys.** `evidence` references `(source_id, run_id) → sources(id, run_id)`
rather than `source_id → sources(id)`. One `run_id` column must satisfy both the parent
reference and the row's own scoping, so evidence cannot reference another run's source. The
`UNIQUE (id, run_id)` constraints that look redundant in isolation exist to be the targets.

**CHECK constraints encode the three-valued provenance model** (M2A §4). A row cannot claim
attestation without recording when it happened, and cannot be `UNCHECKED` while carrying
evidence that a check ran. That makes the "unmeasured became zero" failure unstorable rather
than merely discouraged.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import JsonType, UuidType

# ── Vocabularies ──────────────────────────────────────────────────────────────────
#
# Kept as module constants so the CHECK constraints and any future application code read
# from one list. A status the database accepts and the application does not know about is
# the drift these prevent.

RUN_STATUSES = (
    "PENDING",
    "RUNNING",
    "AWAITING_PLAN",
    "AWAITING_REVIEW",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
)
RESEARCH_DEPTHS = ("fast", "balanced", "comprehensive")
PLAN_ORIGINS = ("MODEL_PROPOSED", "HUMAN_EDITED", "TEMPLATE", "UNKNOWN")
SOURCE_KINDS = ("WEB", "CORPUS")
RETRIEVAL_STATUSES = ("FETCHED", "SEARCH_RESULT_ONLY", "FAILED", "UNKNOWN")
PROVENANCE_STATES = ("ATTESTED", "UNATTESTED", "UNCHECKED")
ATTESTATION_GRADES = ("FETCHED_BODY", "SEARCH_SNIPPET", "CORPUS_DOCUMENT")
CONTRADICTION_DETECTION = ("DETECTED", "NOT_RUN", "DETECTOR_UNAVAILABLE")
CONTRADICTION_DIMENSIONS = (
    "TIMEFRAME",
    "METHODOLOGY",
    "POPULATION",
    "WORKLOAD",
    "SOURCE_QUALITY",
    "UNCLASSIFIED",
)
CONTRADICTION_REVIEW_STATES = ("UNREVIEWED", "ACKNOWLEDGED", "DISMISSED")


def _in(column: str, values: tuple[str, ...]) -> str:
    """A portable `col IN ('a','b')` fragment. Renders the same on both dialects."""
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


class ResearchRun(Base):
    """One execution of research. The execution record, not the result (M2A §3.12)."""

    __tablename__ = "research_runs"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Denormalised from `projects` so every authorization predicate is single-table. An
    # isolation rule that needs a join is one a future query gets wrong (M2B §9.6).
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    depth: Mapped[str] = mapped_column(String(16), nullable=False)

    corpus_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    skip_plan_gate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    topic_seeds: Mapped[list | None] = mapped_column(JsonType, nullable=True)
    outline_template: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_routing: Mapped[dict | None] = mapped_column(JsonType, nullable=True)

    cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False, default=0)
    tokens_input: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    tokens_output: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    elapsed_seconds: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    # NULL means unmeasured. Never 0 — that is the distinction the product rests on.
    citation_resolution_rate: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Cancellation state is durable and on the row, not a TTL'd cache key (M2A §3.11).
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(_in("status", RUN_STATUSES), name="ck_run_status"),
        CheckConstraint(_in("depth", RESEARCH_DEPTHS), name="ck_run_depth"),
        # A cancelled run without a timestamp, or a timestamp without the status, is not
        # representable. Both sides are booleans on Postgres and 0/1 on SQLite; `=` compares
        # them identically on each.
        CheckConstraint(
            "(status = 'CANCELLED') = (cancelled_at IS NOT NULL)", name="ck_run_cancelled"
        ),
        CheckConstraint(
            "cost_usd >= 0 AND tokens_input >= 0 AND tokens_output >= 0", name="ck_run_metrics"
        ),
        CheckConstraint(
            "citation_resolution_rate IS NULL OR "
            "(citation_resolution_rate >= 0 AND citation_resolution_rate <= 1)",
            name="ck_run_resolution",
        ),
        # The history list: this project, unarchived, newest first (M2B §5).
        Index("ix_run_project_recent", "project_id", "archived_at", "created_at"),
        Index("ix_run_owner_status", "owner_id", "status"),
    )


class ResearchPlan(Base):
    """A versioned, immutable plan proposal or edit (M2A §2.3).

    V1 overwrote `plan_json` with the approved plan, destroying both the model's proposal and
    the diff a human made to it. Versions here are inserted, never updated.
    """

    __tablename__ = "research_plans"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("research_runs.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    tasks: Mapped[list] = mapped_column(JsonType, nullable=False)
    outline_sections: Mapped[list] = mapped_column(JsonType, nullable=False)
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("run_id", "version", name="uq_plan_version"),
        CheckConstraint("version >= 1", name="ck_plan_version"),
        # UNKNOWN exists for migrated V1 rows only — V1 cannot tell a model proposal from a
        # human edit (M2C §13.2). New code must never write it.
        CheckConstraint(_in("origin", PLAN_ORIGINS), name="ck_plan_origin"),
    )


# At most one approved plan per run (M2A §6.2), as a partial unique index.
#
# Declared after the class rather than in `__table_args__` because the predicate needs a
# column object, which does not exist until the mapper has run. Both dialect keywords are
# given: SQLAlchemy emits `postgresql_where` only for Postgres and `sqlite_where` only for
# SQLite, so omitting either silently drops the predicate on that host and turns a partial
# index into a total one — which would forbid a second *unapproved* plan version and break
# the rework loop.
Index(
    "uq_plan_approved",
    ResearchPlan.__table__.c.run_id,
    unique=True,
    postgresql_where=ResearchPlan.__table__.c.approved_at.isnot(None),
    sqlite_where=ResearchPlan.__table__.c.approved_at.isnot(None),
)


class Source(Base):
    """One retrieved document. What a citation resolves to (M2A §2.4)."""

    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("research_runs.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    # New in V2: V1 could not distinguish a fetched page from a search-result mention, and
    # the attestation grade in `evidence` needs that difference (M2A §2.4).
    retrieval_status: Mapped[str] = mapped_column(String(20), nullable=False)
    # NULL means "retrieved but never assigned a citation number" — a real state, reached
    # by a run that gathered evidence and failed before the synthesizer numbered anything,
    # and by a V2-native run that fetches a page it does not cite. Never generated: an
    # index the synthesizer did not assign would be a fabricated historical fact
    # (M2F Amendment §6).
    citation_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Deliberately NOT a foreign key: deleting an uploaded file must not invalidate a
    # historical source record (M2A §10).
    corpus_document_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "normalized_url", name="uq_source_url"),
        # Composite-FK target for evidence. Not redundant with the primary key: it is what
        # lets a child prove same-run membership.
        UniqueConstraint("id", "run_id", name="uq_source_run"),
        CheckConstraint(_in("kind", SOURCE_KINDS), name="ck_source_kind"),
        CheckConstraint(_in("retrieval_status", RETRIEVAL_STATUSES), name="ck_source_ret"),
        CheckConstraint("citation_index IS NULL OR citation_index >= 1", name="ck_source_cidx"),
        CheckConstraint(
            "(kind = 'CORPUS') = (corpus_document_id IS NOT NULL)", name="ck_source_corpus"
        ),
    )


# One source per citation number per run — but only among the sources that HAVE one.
# A total unique constraint would allow at most one uncited source per run, which is the
# opposite of what S3 exists to permit. Both dialect predicates given: SQLAlchemy emits
# `postgresql_where` only for Postgres and `sqlite_where` only for SQLite, and omitting
# either silently makes the index total on that host.
Index(
    "uq_source_index",
    Source.__table__.c.run_id,
    Source.__table__.c.citation_index,
    unique=True,
    postgresql_where=Source.__table__.c.citation_index.isnot(None),
    sqlite_where=Source.__table__.c.citation_index.isnot(None),
)


class Evidence(Base):
    """One immutable extracted snippet with its provenance state (M2A §2.5).

    V1's `verify_evidence_snippets` blanks the snippet in place on failure. This table keeps
    the text and records `UNATTESTED`, because destroying fabricated text makes the
    fabrication unauditable (M2A §3.7).
    """

    __tablename__ = "evidence"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("research_runs.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(UuidType, nullable=False)
    # An ordering value, not a gap-free ordinal (M2B §9.2). `executor_node` gathers
    # concurrently; guaranteeing contiguity would need a lock for no benefit. Order by
    # (sequence, id) — `sequence` alone can tie.
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    task_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    snippet: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    key_fact: Mapped[str | None] = mapped_column(Text, nullable=True)

    provenance_state: Mapped[str] = mapped_column(String(12), nullable=False)
    attested_against: Mapped[str | None] = mapped_column(String(20), nullable=True)
    attestation_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["source_id", "run_id"],
            ["sources.id", "sources.run_id"],
            ondelete="CASCADE",
            name="fk_evidence_source",
        ),
        UniqueConstraint("run_id", "sequence", name="uq_evidence_seq"),
        UniqueConstraint("id", "run_id", name="uq_evidence_run"),
        # The provenance model, made structural (M2A §4).
        CheckConstraint(_in("provenance_state", PROVENANCE_STATES), name="ck_ev_state"),
        CheckConstraint(
            "(provenance_state = 'UNCHECKED') = (attestation_run_at IS NULL)",
            name="ck_ev_unchecked",
        ),
        CheckConstraint(
            "(attested_against IS NOT NULL) = (provenance_state = 'ATTESTED')",
            name="ck_ev_grade",
        ),
        CheckConstraint(
            "attested_against IS NULL OR " + _in("attested_against", ATTESTATION_GRADES),
            name="ck_ev_grade_vocab",
        ),
        CheckConstraint("sequence >= 1", name="ck_ev_seq"),
        Index("ix_evidence_source", "source_id"),
    )


class Contradiction(Base):
    """A detected conflict between two **attributed quotations**. Preserved, never resolved.

    Not "between two pieces of evidence", which is what this said until M2F. V1's detector
    is shown `group_snippets_by_source(evidence)` — a `{source_url: [snippets]}` map — and
    returns a pair naming two source URLs and quoting text from each. It never sees an
    evidence row. Modelling the pair at evidence level therefore asserted a precision V1
    never observed, and `ck_contra_pair` made that assertion mandatory, which is why the
    migration had to write `NOT_RUN` for pairs the detector genuinely found.

    The source anchor is what V1 guarantees; the evidence anchor is a *refinement*, set only
    when a quotation matches exactly one evidence row (M2F Amendment §7).
    """

    __tablename__ = "contradictions"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("research_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The authoritative anchors. `validate_pairs` drops any pair whose URL was not in the
    # detector's input, so for a surviving V1 pair both of these resolve.
    source_a_id: Mapped[uuid.UUID | None] = mapped_column(UuidType, nullable=True)
    source_b_id: Mapped[uuid.UUID | None] = mapped_column(UuidType, nullable=True)
    # The refinement. NULL when the quotation matched no evidence row, or more than one.
    evidence_a_id: Mapped[uuid.UUID | None] = mapped_column(UuidType, nullable=True)
    evidence_b_id: Mapped[uuid.UUID | None] = mapped_column(UuidType, nullable=True)
    # The verbatim text the detector quoted, and its own restatement of each side. Both are
    # authoritative as *what the detector said*, which is not the same as a fact about the
    # world — hence `summary`, not `claim`: a V2 `Claim` is a report sentence.
    quote_a: Mapped[str | None] = mapped_column(Text, nullable=True)
    quote_b: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_a: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_b: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Why the two cannot both be true. V1 records it and renders it into the report's
    # conflict block; until M2F it had no column here and survived only as prose.
    nature: Mapped[str | None] = mapped_column(Text, nullable=True)
    dimension: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # A detector that did not run and a detector that found nothing are different findings.
    detection_state: Mapped[str] = mapped_column(String(24), nullable=False)
    review_state: Mapped[str] = mapped_column(String(16), nullable=False, default="UNREVIEWED")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["source_a_id", "run_id"],
            ["sources.id", "sources.run_id"],
            ondelete="CASCADE",
            name="fk_contra_src_a",
        ),
        ForeignKeyConstraint(
            ["source_b_id", "run_id"],
            ["sources.id", "sources.run_id"],
            ondelete="CASCADE",
            name="fk_contra_src_b",
        ),
        ForeignKeyConstraint(
            ["evidence_a_id", "run_id"],
            ["evidence.id", "evidence.run_id"],
            ondelete="CASCADE",
            name="fk_contra_a",
        ),
        ForeignKeyConstraint(
            ["evidence_b_id", "run_id"],
            ["evidence.id", "evidence.run_id"],
            ondelete="CASCADE",
            name="fk_contra_b",
        ),
        CheckConstraint(_in("detection_state", CONTRADICTION_DETECTION), name="ck_contra_state"),
        CheckConstraint(
            "dimension IS NULL OR " + _in("dimension", CONTRADICTION_DIMENSIONS),
            name="ck_contra_dim",
        ),
        CheckConstraint(_in("review_state", CONTRADICTION_REVIEW_STATES), name="ck_contra_review"),
        # DETECTED means the detector found a pair, at the granularity it works in.
        CheckConstraint(
            "(detection_state = 'DETECTED') = "
            "(source_a_id IS NOT NULL AND source_b_id IS NOT NULL)",
            name="ck_contra_pair",
        ),
        # The refinement is all-or-nothing: half a resolved pair is not a pair.
        CheckConstraint(
            "(evidence_a_id IS NULL) = (evidence_b_id IS NULL)", name="ck_contra_refine"
        ),
        CheckConstraint(
            "source_a_id IS NULL OR source_a_id <> source_b_id", name="ck_contra_src_distinct"
        ),
        CheckConstraint(
            "evidence_a_id IS NULL OR evidence_a_id <> evidence_b_id", name="ck_contra_distinct"
        ),
    )
