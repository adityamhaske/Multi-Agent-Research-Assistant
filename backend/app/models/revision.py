"""
V2 report versions and the claim graph (M2B §2.6–2.8).

**Created, not yet used.** M2D builds the contract; nothing writes these tables.

`revisions` has **zero mutable columns** (M2B §9.1). `state` and `superseded_by_id` were
removed once both were shown to derive from reviews, run status and version position —
`state` had been mixing generation lifecycle, review decision, approval and supersession in
one field. A table with no mutable columns cannot drift from facts it does not hold.

`claim_evidence_links` is where the claim graph becomes a graph, and it is **authoritative**:
the `[n]` markers in report prose are a rendering of this table, not the other way round
(M2A C7). That inversion is the single most important difference from V1, where the markers
*were* the data.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.research import _in
from app.models.types import UuidType

CLAIM_EXTRACTION_METHODS = ("DERIVED_FROM_REPORT", "MODEL_STRUCTURED", "HUMAN_EDITED")
CLAIM_VERIFICATION_STATES = (
    "SUPPORTED",
    "UNSUPPORTED",
    "INSUFFICIENT_EVIDENCE",
    "UNCHECKED",
)
CLAIM_VERIFICATION_METHODS = ("NUMERIC_GROUNDING", "MODEL_JUDGE", "NOT_RUN")
LINK_STANCES = ("SUPPORTS", "CONTRADICTS", "CONTEXT")
LINK_ORIGINS = ("CITATION_MARKER", "MODEL_ASSERTED", "HUMAN_ASSERTED")


class Revision(Base):
    """One report version. Not a research-state snapshot (M2A §13.1).

    Evidence and Sources belong to the Run, because rework re-synthesizes from the same
    evidence — `graph.route_after_gate` sends a rejected draft back to the synthesizer, not
    the executor.
    """

    __tablename__ = "revisions"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("research_runs.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # The bytes a human approves. Immutable, which is what makes
    # `Review.reviewed_hash == report_hash` a permanent property rather than a coincidence
    # that survived until the next rework.
    report_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    report_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # The last `evidence.sequence` visible at synthesis. A threshold, not a count, so gaps
    # in the sequence do not affect it. Not a foreign key: pointing it at a row would imply
    # that row is special. 0 is legal — a failed run can synthesize against no evidence.
    evidence_watermark: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("run_id", "version", name="uq_revision_version"),
        UniqueConstraint("id", "run_id", name="uq_revision_run"),
        CheckConstraint("version >= 1", name="ck_revision_version"),
        CheckConstraint("length(report_hash) = 64", name="ck_revision_hash"),
        CheckConstraint("evidence_watermark >= 0", name="ck_revision_wm"),
        # Latest revision for a run — the hot read on every session detail page.
        Index("ix_revision_run_version", "run_id", "version"),
    )


class Claim(Base):
    """One persisted assertion belonging to one revision (M2A §2.6).

    `lineage_id` is reserved and **NULL in every row V2 initially writes** (M2A §13.3).
    Claims are derived from prose today, and nothing in that process observes that a
    sentence in revision 2 *is* the assertion from revision 1. Assigning lineage by fuzzy
    text matching would manufacture a relationship the system never observed — the same
    error as marking migrated evidence ATTESTED because it looks fine. It is populated only
    once the synthesizer emits structured claims, and never backfilled by matching.
    """

    __tablename__ = "claims"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    revision_id: Mapped[uuid.UUID] = mapped_column(UuidType, nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UuidType, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    extraction_method: Mapped[str] = mapped_column(String(24), nullable=False)
    verification_state: Mapped[str] = mapped_column(String(24), nullable=False)
    verification_method: Mapped[str] = mapped_column(String(20), nullable=False)
    lineage_id: Mapped[uuid.UUID | None] = mapped_column(UuidType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["revision_id", "run_id"],
            ["revisions.id", "revisions.run_id"],
            ondelete="CASCADE",
            name="fk_claim_revision",
        ),
        UniqueConstraint("revision_id", "position", name="uq_claim_position"),
        UniqueConstraint("id", "run_id", name="uq_claim_run"),
        CheckConstraint("position >= 0", name="ck_claim_position"),
        CheckConstraint(
            _in("extraction_method", CLAIM_EXTRACTION_METHODS), name="ck_claim_extract"
        ),
        CheckConstraint(
            _in("verification_state", CLAIM_VERIFICATION_STATES), name="ck_claim_state"
        ),
        CheckConstraint(
            _in("verification_method", CLAIM_VERIFICATION_METHODS), name="ck_claim_method"
        ),
        # The same unmeasured-vs-measured coherence as evidence: a claim cannot be
        # UNCHECKED while recording that a verification method ran.
        CheckConstraint(
            "(verification_state = 'UNCHECKED') = (verification_method = 'NOT_RUN')",
            name="ck_claim_unchecked",
        ),
        # No index on `lineage_id`: it is NULL in every row V2 writes, so an index would be
        # pure write cost. It arrives with the first non-NULL writer (M2B §5).
    )


class ClaimEvidenceLink(Base):
    """The claim↔evidence relation. Authoritative; `[n]` is presentation (M2A C7).

    The two composite foreign keys share this row's single `run_id`, so one value must
    satisfy both parents. A claim therefore cannot link to another run's evidence — the
    contamination is unrepresentable rather than merely detected (M2B §9.6).
    """

    __tablename__ = "claim_evidence_links"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UuidType, nullable=False)
    claim_id: Mapped[uuid.UUID] = mapped_column(UuidType, nullable=False)
    evidence_id: Mapped[uuid.UUID] = mapped_column(UuidType, nullable=False)
    stance: Mapped[str] = mapped_column(String(12), nullable=False)
    # CITATION_MARKER says plainly that a link came from a typographic marker rather than a
    # considered judgement. V1 has only this kind and cannot say so.
    origin: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["claim_id", "run_id"],
            ["claims.id", "claims.run_id"],
            ondelete="CASCADE",
            name="fk_link_claim",
        ),
        ForeignKeyConstraint(
            ["evidence_id", "run_id"],
            ["evidence.id", "evidence.run_id"],
            ondelete="CASCADE",
            name="fk_link_evidence",
        ),
        UniqueConstraint("claim_id", "evidence_id", name="uq_link"),
        CheckConstraint(_in("stance", LINK_STANCES), name="ck_link_stance"),
        CheckConstraint(_in("origin", LINK_ORIGINS), name="ck_link_origin"),
        Index("ix_link_claim", "claim_id"),
        # The reverse direction — "which claims cite this evidence?" — is what the evidence
        # drawer asks, and the question V1 cannot answer at all.
        Index("ix_link_evidence", "evidence_id"),
    )
