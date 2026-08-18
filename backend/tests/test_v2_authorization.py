"""
Artifact authorization, at all four layers (M2F Amendment §5, F2).

> Only an **APPROVED REPORT** review may authorize a `ResearchArtifact`.

Each layer catches what the others cannot reach, so each is tested separately rather than
through whichever one happens to fire first:

| Layer | Under test here |
|---|---|
| database | the composite FK and `ck_artifact_gate` reject a PLAN approval |
| application | `app.authorization` raises rather than letting the database explain |
| serialization | a PLAN approval never becomes `"approved"` in a bundle |
| verifier | `verify_bundle` does not count a plan approval as report authorization |

The serialization layer is the one that matters most and is easiest to lose: the verifier's
load-bearing check is `action == "approved"`, and no database constraint reaches a JSON file.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from app.authorization import (
    NotAuthorizing,
    approval_chain,
    approving_report_review,
    artifact_authorization_values,
    may_authorize_artifact,
)
from app.models.project import Project
from app.models.research import ResearchPlan, ResearchRun
from app.models.review import ResearchArtifact, Review
from app.models.revision import Revision
from app.models.user import User
from research_engine import bundle as bundle_mod
from research_engine import verify_bundle
from tests.migration_support import open_db

HASH64 = "a" * 64


@pytest.fixture
async def db(tmp_path):
    async with open_db(tmp_path / "auth.sqlite") as maker, maker() as session:
        yield session


async def _scaffold(db) -> dict:
    """One run with a plan and a revision — the two things a review can target."""
    now = datetime(2026, 8, 18, tzinfo=UTC)
    ids = {k: uuid.uuid4() for k in ("user", "project", "run", "plan", "revision")}
    await db.execute(
        insert(User).values(
            id=ids["user"],
            email=f"{ids['user']}@x.invalid",
            hashed_pw="x",
            is_active=True,
            created_at=now,
        )
    )
    await db.execute(
        insert(Project).values(
            id=ids["project"], user_id=ids["user"], name="P", created_at=now, updated_at=now
        )
    )
    await db.execute(
        insert(ResearchRun).values(
            id=ids["run"],
            project_id=ids["project"],
            owner_id=ids["user"],
            question="q",
            status="COMPLETED",
            depth="fast",
            corpus_mode=False,
            demo=False,
            skip_plan_gate=False,
            cost_usd=0,
            tokens_input=0,
            tokens_output=0,
            created_at=now,
            updated_at=now,
        )
    )
    await db.execute(
        insert(ResearchPlan).values(
            id=ids["plan"],
            run_id=ids["run"],
            version=1,
            tasks=[],
            outline_sections=[],
            origin="UNKNOWN",
            created_at=now,
        )
    )
    await db.execute(
        insert(Revision).values(
            id=ids["revision"],
            run_id=ids["run"],
            version=1,
            report_markdown="# r",
            report_hash=HASH64,
            evidence_watermark=0,
            created_at=now,
        )
    )
    ids["now"] = now
    await db.commit()
    return ids


async def _review(db, ids, *, gate, decision, sequence):
    rid = uuid.uuid4()
    await db.execute(
        insert(Review).values(
            id=rid,
            run_id=ids["run"],
            sequence=sequence,
            revision_id=ids["revision"] if gate == "REPORT" else None,
            plan_version_id=ids["plan"] if gate == "PLAN" else None,
            reviewer_id=ids["user"],
            gate=gate,
            decision=decision,
            reviewed_hash=HASH64,
            created_at=ids["now"],
        )
    )
    await db.commit()
    return (await db.execute(select(Review).where(Review.id == rid))).scalar_one()


async def _artifact(db, ids, review_id, decision, *, gate: str):
    # Plain values, not a live ORM object: after the first IntegrityError below the session
    # rolls back and every loaded instance is expired, so touching an attribute would
    # attempt lazy IO outside the greenlet context.
    await db.execute(
        insert(ResearchArtifact).values(
            id=uuid.uuid4(),
            owner_id=ids["user"],
            run_id=ids["run"],
            project_id=ids["project"],
            revision_id=ids["revision"],
            review_id=review_id,
            review_decision=decision,
            review_gate=gate,
            format_version=1,
            payload={},
            artifact_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            demo=False,
            created_at=ids["now"],
        )
    )
    await db.commit()


# ── Layer 1: the database ────────────────────────────────────────────────────────


async def test_a_plan_approval_cannot_authorize_an_artifact_in_the_database(db):
    ids = await _scaffold(db)
    plan_review = await _review(db, ids, gate="PLAN", decision="APPROVED", sequence=1)
    review_id, decision = plan_review.id, plan_review.decision

    # Declaring REPORT does not help: the composite FK requires (id, decision, gate) to
    # match a real review, and this review's gate is PLAN.
    with pytest.raises(IntegrityError):
        await _artifact(db, ids, review_id, decision, gate="REPORT")
    await db.rollback()

    # Telling the truth does not help either: ck_artifact_gate forbids it.
    with pytest.raises(IntegrityError):
        await _artifact(db, ids, review_id, decision, gate="PLAN")
    await db.rollback()


async def test_an_approved_report_review_does_authorize_an_artifact(db):
    ids = await _scaffold(db)
    review = await _review(db, ids, gate="REPORT", decision="APPROVED", sequence=1)
    await _artifact(db, ids, review.id, review.decision, gate="REPORT")
    assert (await db.execute(select(ResearchArtifact))).scalars().all()


async def test_a_plan_review_cannot_carry_a_revision(db):
    """`ck_review_report` is the mirror of `ck_review_plan`, and both must hold."""
    ids = await _scaffold(db)
    with pytest.raises(IntegrityError):
        await db.execute(
            insert(Review).values(
                id=uuid.uuid4(),
                run_id=ids["run"],
                sequence=1,
                revision_id=ids["revision"],
                plan_version_id=ids["plan"],
                reviewer_id=ids["user"],
                gate="PLAN",
                decision="APPROVED",
                reviewed_hash=HASH64,
                created_at=ids["now"],
            )
        )
    await db.rollback()


async def test_a_report_review_must_carry_a_revision(db):
    ids = await _scaffold(db)
    with pytest.raises(IntegrityError):
        await db.execute(
            insert(Review).values(
                id=uuid.uuid4(),
                run_id=ids["run"],
                sequence=1,
                revision_id=None,
                reviewer_id=ids["user"],
                gate="REPORT",
                decision="APPROVED",
                reviewed_hash=HASH64,
                created_at=ids["now"],
            )
        )
    await db.rollback()


# ── Layer 2: the application ─────────────────────────────────────────────────────


async def test_the_accessor_refuses_a_plan_approval_before_the_database_has_to(db):
    ids = await _scaffold(db)
    plan_review = await _review(db, ids, gate="PLAN", decision="APPROVED", sequence=1)

    assert may_authorize_artifact(plan_review) is False
    with pytest.raises(NotAuthorizing):
        artifact_authorization_values(plan_review)

    # A caller that has to read a CHECK constraint's error to learn it passed a plan
    # approval has been told too late.
    assert await approving_report_review(db, ids["run"]) is None


async def test_the_accessor_finds_only_the_report_approval(db):
    ids = await _scaffold(db)
    await _review(db, ids, gate="PLAN", decision="APPROVED", sequence=1)
    await _review(db, ids, gate="REPORT", decision="REWORK_REQUESTED", sequence=2)
    approved = await _review(db, ids, gate="REPORT", decision="APPROVED", sequence=3)

    found = await approving_report_review(db, ids["run"])
    assert found is not None and found.id == approved.id
    assert artifact_authorization_values(found)["review_gate"] == "REPORT"


# ── Layer 3: serialization ───────────────────────────────────────────────────────


def test_a_plan_approval_serialized_as_approved_would_satisfy_the_verifier():
    """Why layer 3 exists at all: the verifier cannot tell, so the assembler must not lie.

    This is the planted failure standing on its own — a bundle whose only approval is a
    plan approval, mislabelled, passes `approval_chain`. Nothing in the database can reach
    a JSON file, so the guard has to live in the assembler.
    """
    report = "# Findings\n\nA sentence [1].\n"
    manifest = bundle_mod.assemble(
        session_id=str(uuid.uuid4()),
        query="q",
        report=report,
        evidence=[],
        sources=[],
        approval_chain=[
            {
                "action": "approved",  # the lie
                "draft_hash": bundle_mod.content_hash(report),
                "timestamp": "2026-08-18T00:00:00+00:00",
            }
        ],
    )
    assert verify_bundle._check_approval_chain(manifest).passed is True


def test_the_same_bundle_labelled_truthfully_is_rejected():
    report = "# Findings\n\nA sentence [1].\n"
    manifest = bundle_mod.assemble(
        session_id=str(uuid.uuid4()),
        query="q",
        report=report,
        evidence=[],
        sources=[],
        approval_chain=[
            {
                "action": "plan_approved",
                "draft_hash": bundle_mod.content_hash(report),
                "timestamp": "2026-08-18T00:00:00+00:00",
            }
        ],
    )
    result = verify_bundle._check_approval_chain(manifest)
    assert result.passed is False
    assert "never approved" in (result.detail or "")


# ── Layer 4: the verifier's vocabulary is explicit ───────────────────────────────


def test_the_verifier_names_the_plan_actions_it_excludes():
    """It rejected `plan_approved` by string inequality before; now it says so."""
    assert verify_bundle.REPORT_APPROVAL_ACTION == "approved"
    assert "plan_approved" in verify_bundle.PLAN_GATE_ACTIONS
    assert verify_bundle.REPORT_APPROVAL_ACTION not in verify_bundle.PLAN_GATE_ACTIONS


# ── Review ordering (S5, I9) ─────────────────────────────────────────────────────


async def test_a_runs_approval_chain_includes_both_gates_in_order(db):
    """Before `reviews.run_id`, this query could not be written at all.

    A PLAN review has no `revision_id`, so a read through `revisions` would silently omit
    every plan approval from the chain.
    """
    ids = await _scaffold(db)
    await _review(db, ids, gate="REPORT", decision="APPROVED", sequence=3)
    await _review(db, ids, gate="PLAN", decision="APPROVED", sequence=1)
    await _review(db, ids, gate="REPORT", decision="REWORK_REQUESTED", sequence=2)

    chain = await approval_chain(db, ids["run"])
    assert [r.sequence for r in chain] == [1, 2, 3]
    assert [r.gate for r in chain] == ["PLAN", "REPORT", "REPORT"]


async def test_two_reviews_of_one_run_cannot_share_a_position(db):
    ids = await _scaffold(db)
    await _review(db, ids, gate="REPORT", decision="REWORK_REQUESTED", sequence=1)
    with pytest.raises(IntegrityError):
        await _review(db, ids, gate="REPORT", decision="APPROVED", sequence=1)
    await db.rollback()


async def test_ordering_does_not_depend_on_the_timestamp(db):
    """V1 guarantees no distinctness on `created_at`, so ordering must not rest on it."""
    ids = await _scaffold(db)
    await _review(db, ids, gate="REPORT", decision="REWORK_REQUESTED", sequence=2)
    await _review(db, ids, gate="PLAN", decision="APPROVED", sequence=1)

    chain = await approval_chain(db, ids["run"])
    assert [r.gate for r in chain] == ["PLAN", "REPORT"]
    assert len({r.created_at for r in chain}) == 1, "the fixture must share a timestamp"
