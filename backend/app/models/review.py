"""
Human review, artifacts, and the audit log.

Three decisions are load-bearing here.

**`reviews` is the only approval authority**. A partial unique index allows at
most one approving report review per revision. Claim-level feedback lives in
`claim_annotations`, which has no `decision` column and therefore cannot be mistaken for a
second approval system.

**An artifact exists only because an approving review exists.** `research_artifacts` carries
a denormalised `review_decision` constrained to `'APPROVED'` and a *composite* foreign key to
`reviews(id, decision)`. An artifact referencing a rework request is unrepresentable — the
strongest available form of the rule, and portable, unlike a trigger.

**`audit_events` has no foreign key to its subject.** That is not a limitation; an FK would
delete the audit record together with the thing it documents, which is exactly when the
record matters most.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
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
from app.models.types import BigIntAutoType, JsonType, UuidType

REVIEW_GATES = ("PLAN", "REPORT")
REVIEW_DECISIONS = ("APPROVED", "REWORK_REQUESTED", "REJECTED")
ANNOTATION_KINDS = ("FLAG_UNSUPPORTED", "REQUEST_EVIDENCE", "COMMENT")


class Review(Base):
    """A human decision about a specific versioned object — the trust boundary.

    `ON DELETE RESTRICT` rather than CASCADE, deliberately: a Review outlives its
    subject, because deleting a run must not silently erase the record that a human approved
    something. The restrict chain is also what stops the ordinary delete path from destroying
    approved research — `DELETE run → CASCADE revisions → RESTRICT reviews` fails
    at the restrict, and the application's only job is to turn that into a helpful message.
    """

    __tablename__ = "reviews"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    # A review belongs to the RUN, not only to whichever versioned object it judged
    # . Without this, a run's approval chain cannot be collected at
    # all: PLAN reviews hang off `research_plans` and REPORT reviews off `revisions`, so a
    # single-parent read would silently omit every plan approval.
    run_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("research_runs.id", ondelete="RESTRICT"), nullable=False
    )
    # The total order of decisions within a run. Not `created_at` (the clock guarantees no
    # distinctness and two gates can share a timestamp) and not insertion order (ids are
    # uuid5, so id order is arbitrary). Migrated from the rank of `audit_log.id`.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    # NULL for a PLAN review: `submit_plan` runs at AWAITING_PLAN, before any draft exists,
    # so a plan approval with no revision to point at is normal.
    revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidType, ForeignKey("revisions.id", ondelete="RESTRICT"), nullable=True
    )
    reviewer_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    plan_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidType, ForeignKey("research_plans.id", ondelete="RESTRICT"), nullable=True
    )
    gate: Mapped[str] = mapped_column(String(8), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The hash's meaning follows `gate`, rather than one overloaded `draft_hash`. At the report
    # gate it hashes `Revision.report_markdown`; at the plan gate, the plan's canonical
    # serialisation — which used to share that one column, where nothing ever verified it.
    reviewed_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # Composite-FK target for `research_artifacts`. Carries `gate` as well as
        # `decision`: once a PLAN review can exist without a revision, constraining only
        # the decision would let a plan approval authorize an artifact.
        UniqueConstraint("id", "decision", "gate", name="uq_review_decision"),
        UniqueConstraint("run_id", "sequence", name="uq_review_sequence"),
        CheckConstraint(_in("gate", REVIEW_GATES), name="ck_review_gate"),
        CheckConstraint(_in("decision", REVIEW_DECISIONS), name="ck_review_decision"),
        CheckConstraint("length(reviewed_hash) = 64", name="ck_review_hash"),
        CheckConstraint("(gate = 'PLAN') = (plan_version_id IS NOT NULL)", name="ck_review_plan"),
        # The mirror of ck_review_plan, and the whole of S1: a REPORT review must have a
        # revision, a PLAN review must not.
        CheckConstraint("(gate = 'REPORT') = (revision_id IS NOT NULL)", name="ck_review_report"),
        CheckConstraint("sequence >= 1", name="ck_review_sequence"),
        Index("ix_review_revision", "revision_id", "created_at"),
        Index("ix_review_run", "run_id", "sequence"),
    )


# At most one approving report review per revision. Declared
# after the class because the predicate needs column objects. Both dialect keywords given —
# omitting one silently makes the index total on that host, which would forbid a second
# *rework* review and break the loop.
Index(
    "uq_review_approval",
    Review.__table__.c.revision_id,
    unique=True,
    postgresql_where=(Review.__table__.c.decision == "APPROVED")
    & (Review.__table__.c.gate == "REPORT"),
    sqlite_where=(Review.__table__.c.decision == "APPROVED")
    & (Review.__table__.c.gate == "REPORT"),
)


class ClaimAnnotation(Base):
    """A reviewer's note on one claim. Advisory; carries no approval authority.

        Deliberately not a third `Review.gate` value: a row with no `decision` column cannot be
        mistaken for an approval. Cascades with its claim, which means annotations do **not**
        carry forward across revisions — the accepted cost of not manufacturing claim lineage
    , visible here in the schema rather than hidden in a service.
    """

    __tablename__ = "claim_annotations"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    claim_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (CheckConstraint(_in("kind", ANNOTATION_KINDS), name="ck_annotation_kind"),)


class ResearchArtifact(Base):
    """The immutable, self-contained, hash-verifiable approved record.

    `payload` is a frozen snapshot, not a set of joins. Reading an artifact never
    touches live tables, so a later project rename or run deletion cannot change it — which
    is the property that makes it worth handing to someone who does not trust this database.

    `owner_id` is the survival anchor. `run_id`, `project_id`, `revision_id` and `review_id`
    all become NULL when their subject is deleted; without an owner the artifact would be
    orphaned outside every tenant boundary.
    """

    __tablename__ = "research_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidType, ForeignKey("research_runs.id", ondelete="SET NULL"), nullable=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidType, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidType, ForeignKey("revisions.id", ondelete="SET NULL"), nullable=True
    )
    review_id: Mapped[uuid.UUID | None] = mapped_column(UuidType, nullable=True)
    review_decision: Mapped[str] = mapped_column(String(20), nullable=False)
    # Denormalised beside `review_decision` for the same reason and by the same technique:
    # it makes "this artifact was authorized by a plan approval" unrepresentable rather
    # than merely discouraged.
    review_gate: Mapped[str] = mapped_column(String(8), nullable=False, default="REPORT")

    # `research_engine.bundle`'s format, unchanged — one schema, one verifier.
    format_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    payload: Mapped[dict] = mapped_column(JsonType, nullable=False)
    artifact_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # The load-bearing constraint of the whole schema: approval as a database fact.
        ForeignKeyConstraint(
            ["review_id", "review_decision", "review_gate"],
            ["reviews.id", "reviews.decision", "reviews.gate"],
            ondelete="SET NULL",
            name="fk_artifact_review",
        ),
        CheckConstraint("review_decision = 'APPROVED'", name="ck_artifact_approved"),
        # A PLAN approval can never reach here: the FK forces (decision, gate) to match a
        # real review's pair, and this pins the gate to REPORT.
        CheckConstraint("review_gate = 'REPORT'", name="ck_artifact_gate"),
        UniqueConstraint("artifact_hash", name="uq_artifact_hash"),
        CheckConstraint("format_version >= 1", name="ck_artifact_format"),
        CheckConstraint("length(artifact_hash) = 64", name="ck_artifact_hashlen"),
        # Artifacts survive project deletion, so they cannot be reached by project.
        Index("ix_artifact_owner", "owner_id", "created_at"),
    )


# At most one artifact per run. Partial, so multiple orphaned artifacts stay legal after a
# run is deleted and their `run_id` goes NULL.
Index(
    "uq_artifact_run",
    ResearchArtifact.__table__.c.run_id,
    unique=True,
    postgresql_where=ResearchArtifact.__table__.c.run_id.isnot(None),
    sqlite_where=ResearchArtifact.__table__.c.run_id.isnot(None),
)


class AuditEvent(Base):
    """Append-only accountability log. Not the record of a decision — that is `Review`.

    `(subject_type, subject_id)` is polymorphic and has no foreign key, deliberately: an
    audit event may reference a row that has since been deleted, and that is precisely when
    it is most needed. Nothing cascades into this table, so nothing deletes an event as a
    side effect of deleting something else.
    """

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(BigIntAutoType, primary_key=True, autoincrement=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidType, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UuidType, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JsonType, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_audit_subject", "subject_type", "subject_id", "id"),
        Index("ix_audit_actor", "actor_id", "occurred_at"),
    )
