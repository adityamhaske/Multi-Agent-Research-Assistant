"""
The real engine, into the V2 domain, to a bundle the standalone verifier accepts.

This is the milestone's stop condition, and it is deliberately **not** a synthetic
`RunOutcome`. Every test here calls `research_engine.runner.run` — the same function the V1
worker calls, with the same LangGraph graph, the same executor, the same critic loop and the
same synthesizer — against a real `AsyncSqliteSaver`. Only the models and retrievers are
scripted, which is what `llm_mode="fake"` already does for a demo run in production.

    question → runner.run → RunOutcome + checkpoint → v2_execution.persist_outcome
            → Sources + Evidence → Revision → Claims → Links → Contradictions
            → REPORT Review → Artifact → bundle → verify_bundle PASS

A test that injected a hand-built `RunOutcome` would prove the adapter can read a shape the
test wrote. What has to be proven is that the adapter can read what the *engine* writes —
including that evidence lives in the checkpoint and not in the outcome, which is the one thing
a synthetic fixture would quietly get right by construction.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, insert, select

from app import v2_bundle, v2_execution, v2_runtime
from app.models.project import Project
from app.models.research import Contradiction, Evidence, Source
from app.models.review import ResearchArtifact
from app.models.revision import Claim, ClaimEvidenceLink, Revision
from app.models.user import User
from research_engine import runner, verify_bundle
from research_engine.runconfig import RunConfig
from tests.migration_support import open_db

QUESTION = "What did recent work find about retrieval-augmented generation?"


@pytest.fixture
async def db(tmp_path):
    async with open_db(tmp_path / "exec.sqlite") as maker, maker() as session:
        yield session


@pytest.fixture
async def owner(db):
    now = datetime(2026, 8, 18, tzinfo=UTC)
    uid, pid = uuid.uuid4(), uuid.uuid4()
    await db.execute(
        insert(User).values(
            id=uid, email=f"{uid}@x.invalid", hashed_pw="x", is_active=True, created_at=now
        )
    )
    await db.execute(
        insert(Project).values(id=pid, user_id=uid, name="RAG", created_at=now, updated_at=now)
    )
    await db.commit()
    return {"user_id": uid, "project_id": pid}


@pytest.fixture
async def saver(tmp_path):
    """A real LangGraph checkpointer. The evidence the adapter reads comes from here."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "graph.sqlite")) as s:
        yield s


def fake_config(**overrides) -> RunConfig:
    """The engine's own demo configuration: scripted models, fixture retrievers, no egress.

    `llm_mode="fake"` is not a test seam — it is the production demo path (docs/17 §6.2),
    which is why using it here exercises real graph topology rather than a stub of it.
    """
    import dataclasses

    base = RunConfig(llm_mode="fake", demo=True, skip_plan_gate=True)
    return dataclasses.replace(base, **overrides)


async def execute(db, owner, saver, *, config=None, question=QUESTION) -> dict:
    """Create a V2 run, drive the REAL graph, and persist the outcome into V2."""
    run = await v2_runtime.create_run(
        db,
        owner_id=owner["user_id"],
        project_id=owner["project_id"],
        question=question,
        depth="fast",
        demo=True,
        skip_plan_gate=True,
    )
    await db.commit()

    outcome = await runner.run(
        checkpointer=saver,
        session_id=str(run.id),
        user_id=str(owner["user_id"]),
        query=question,
        depth="fast",
        run_config=config or fake_config(),
    )
    result = await v2_execution.persist_outcome(db, run, outcome, saver=saver)
    await db.commit()
    return {"run": run, "outcome": outcome, "result": result}


async def _count(db, model, **where) -> int:
    q = select(func.count()).select_from(model)
    for key, value in where.items():
        q = q.where(getattr(model, key) == value)
    return (await db.execute(q)).scalar_one()


# ── The stop condition ────────────────────────────────────────────────────────────


async def test_a_real_run_reaches_a_verifiable_artifact(db, owner, saver):
    """REAL QUESTION → REAL ENGINE → V2 → ARTIFACT → BUNDLE → VERIFIER PASS."""
    state = await execute(db, owner, saver)
    run, result = state["run"], state["result"]

    # The engine actually ran: it produced a report and gathered evidence, and the adapter
    # read that evidence out of the checkpoint rather than out of the outcome.
    assert result.evidence_outcome == "READ", result
    assert result.evidence_count > 0, "the real graph gathered no evidence"
    assert result.source_count > 0
    assert result.revision_version == 1
    assert result.claim_count > 0
    assert run.status == "AWAITING_REVIEW", run.status

    # Everything landed in the V2 domain.
    assert await _count(db, Source, run_id=run.id) == result.source_count
    assert await _count(db, Evidence, run_id=run.id) == result.evidence_count
    assert await _count(db, Revision, run_id=run.id) == 1
    assert await _count(db, Claim, run_id=run.id) == result.claim_count
    assert await _count(db, ClaimEvidenceLink, run_id=run.id) == result.link_count

    # Approve at the REPORT gate and freeze the artifact.
    revision = (await db.execute(select(Revision).where(Revision.run_id == run.id))).scalars().one()
    await v2_runtime.record_report_review(
        db, run, revision, reviewer_id=owner["user_id"], decision="APPROVED"
    )
    await v2_runtime.set_status(db, run, "COMPLETED")
    artifact = await v2_runtime.create_artifact(db, run)
    await db.commit()

    assert artifact.review_gate == "REPORT"
    assert artifact.payload["report_hash"] == revision.report_hash

    # The standalone verifier — the shipped script, not a private copy.
    manifest = await v2_bundle.assemble(db, run.id)
    verdict = verify_bundle.verify(manifest)
    failed = [c.name for c in verdict.checks if not c.passed]
    assert verdict.passed, f"the verifier rejected a real V2-native artifact: {failed}"
    assert {c.name for c in verdict.checks} >= {
        "bundle_integrity",
        "report_integrity",
        "evidence_integrity",
        "citation_resolution",
        "claim_evidence_linkage",
        "approval_chain",
    }


async def test_the_frozen_payload_verifies_without_the_database(db, owner, saver):
    """An artifact is a snapshot handed to someone who does not trust this database."""
    state = await execute(db, owner, saver)
    run = state["run"]
    revision = (await db.execute(select(Revision).where(Revision.run_id == run.id))).scalars().one()
    await v2_runtime.record_report_review(
        db, run, revision, reviewer_id=owner["user_id"], decision="APPROVED"
    )
    artifact = await v2_runtime.create_artifact(db, run)
    await db.commit()

    from research_engine.bundle import BundleManifest

    assert verify_bundle.verify(BundleManifest.model_validate(artifact.payload)).passed


# ── Provenance rules, on real engine output ───────────────────────────────────────


async def test_real_evidence_lands_unchecked_with_a_matching_content_hash(db, owner, saver):
    await execute(db, owner, saver)
    rows = (await db.execute(select(Evidence))).scalars().all()
    assert rows
    for e in rows:
        assert e.provenance_state == "UNCHECKED"
        assert e.attested_against is None and e.attestation_run_at is None
        assert e.content_hash == v2_runtime.content_hash(e.snippet)
        assert e.sequence >= 1


async def test_every_real_source_is_reachable_and_cited_ones_are_numbered(db, owner, saver):
    """The engine numbers what it cites; anything else keeps a NULL index."""
    state = await execute(db, owner, saver)
    numbered = {s["url"] for s in state["outcome"].sources if s.get("url")}
    rows = (await db.execute(select(Source))).scalars().all()
    assert rows
    for s in rows:
        assert s.url, "no source may be created without a URL"
        if s.url in numbered:
            assert s.citation_index is not None
        else:
            assert s.citation_index is None, "retrieved is not cited"


async def test_a_retrieved_but_uncited_source_keeps_a_null_index(db, owner, saver):
    """Persist the same evidence again with no numbered list — the second source is uncited."""
    state = await execute(db, owner, saver)
    run = state["run"]
    before = await _count(db, Source, run_id=run.id)

    await v2_runtime.record_evidence(
        db,
        run,
        evidence=[
            {
                "task_id": 99,
                "source_url": "https://example.invalid/never-cited",
                "source_title": "Uncited",
                "snippet": "A passage the synthesizer did not use.",
                "key_fact": "unused",
            }
        ],
        numbered_sources=None,
    )
    await db.commit()

    assert await _count(db, Source, run_id=run.id) == before + 1
    uncited = (
        await db.execute(select(Source).where(Source.url == "https://example.invalid/never-cited"))
    ).scalar_one()
    assert uncited.citation_index is None


async def test_contradictions_from_the_real_detector_are_source_anchored(db, owner, saver):
    """Whatever the detector found, a DETECTED row must carry both source anchors."""
    await execute(db, owner, saver)
    rows = (await db.execute(select(Contradiction))).scalars().all()
    for c in rows:
        if c.detection_state == "DETECTED":
            assert c.source_a_id is not None and c.source_b_id is not None
        # And the refinement is all-or-nothing, never half a pair.
        assert (c.evidence_a_id is None) == (c.evidence_b_id is None)


# ── Failure, idempotency, rework ──────────────────────────────────────────────────


async def test_an_execution_failure_lands_FAILED_with_no_artifact(db, owner, saver):
    """A budget of one cent stops the real graph mid-run; the run must fail, not hang."""
    run = await v2_runtime.create_run(
        db,
        owner_id=owner["user_id"],
        project_id=owner["project_id"],
        question=QUESTION,
        depth="fast",
        demo=True,
        skip_plan_gate=True,
    )
    await db.commit()

    outcome = await runner.run(
        checkpointer=saver,
        session_id=str(run.id),
        user_id=str(owner["user_id"]),
        query=QUESTION,
        depth="fast",
        # A guard that fires must say which one and by how much — `failer_node`'s job.
        run_config=fake_config(max_input_tokens=1),
    )
    result = await v2_execution.persist_outcome(db, run, outcome, saver=saver)
    await db.commit()

    assert outcome.status == "failed", outcome.status
    assert result.status == "FAILED"
    assert run.status == "FAILED"
    assert run.error_message, "a guard that fires must say which one"
    assert await _count(db, Revision, run_id=run.id) == 0
    assert await _count(db, ResearchArtifact) == 0

    with pytest.raises(v2_runtime.LifecycleError):
        await v2_runtime.create_artifact(db, run)


async def test_a_completed_run_with_no_report_fails_closed(db, owner, saver):
    """`COMPLETED` with nothing to review is not completed."""
    run = await v2_runtime.create_run(
        db, owner_id=owner["user_id"], project_id=owner["project_id"], question=QUESTION
    )
    await db.commit()
    from research_engine.runner import RunOutcome

    result = await v2_execution.persist_outcome(
        db, run, RunOutcome(status="completed", final_report=None), state={"evidence": []}
    )
    await db.commit()
    assert result.status == "FAILED"
    assert run.status == "FAILED"


async def test_persisting_the_same_outcome_twice_duplicates_no_domain_objects(db, owner, saver):
    """Re-delivery is a real risk with Celery. A second persist must not double the rows.

    Evidence is append-only by sequence, so this asserts the property that matters: the
    *sources* do not duplicate, and the second revision is a new immutable version rather
    than a mutation of the first — which is what a redelivered message would otherwise
    produce as a silent second copy.
    """
    state = await execute(db, owner, saver)
    run, outcome = state["run"], state["outcome"]
    sources_before = await _count(db, Source, run_id=run.id)

    await v2_execution.persist_outcome(db, run, outcome, saver=saver)
    await db.commit()

    assert await _count(db, Source, run_id=run.id) == sources_before, (
        "a redelivered outcome created duplicate sources"
    )
    revisions = (
        (
            await db.execute(
                select(Revision).where(Revision.run_id == run.id).order_by(Revision.version)
            )
        )
        .scalars()
        .all()
    )
    assert [r.version for r in revisions] == [1, 2]
    assert revisions[0].report_hash == revisions[1].report_hash
    assert revisions[0].id != revisions[1].id, "revision 1 must not have been mutated"


async def test_rework_through_the_real_graph_produces_a_second_immutable_revision(db, owner, saver):
    """The rework loop, with the engine resuming from the checkpoint rather than re-running."""
    state = await execute(db, owner, saver)
    run = state["run"]
    first = (await db.execute(select(Revision).where(Revision.run_id == run.id))).scalars().one()
    first_hash, first_id = first.report_hash, first.id

    await v2_runtime.record_report_review(
        db,
        run,
        first,
        reviewer_id=owner["user_id"],
        decision="REWORK_REQUESTED",
        feedback="Add the benchmark size.",
    )
    await db.commit()

    outcome = await runner.resume(
        checkpointer=saver,
        session_id=str(run.id),
        approved=False,
        feedback="Add the benchmark size.",
        run_config=fake_config(),
    )
    result = await v2_execution.persist_outcome(db, run, outcome, saver=saver)
    await db.commit()

    assert result.revision_version == 2
    revisions = (
        (
            await db.execute(
                select(Revision).where(Revision.run_id == run.id).order_by(Revision.version)
            )
        )
        .scalars()
        .all()
    )
    assert [r.version for r in revisions] == [1, 2]
    assert revisions[0].id == first_id and revisions[0].report_hash == first_hash, (
        "revision 1 was mutated by the rework"
    )
    # Claims belong to their own revision; nothing was carried across.
    for revision in revisions:
        assert await _count(db, Claim, revision_id=revision.id) > 0
    assert all(c.lineage_id is None for c in (await db.execute(select(Claim))).scalars())


# ── The authorization rule, on real output ────────────────────────────────────────


async def test_a_plan_approval_on_a_real_run_creates_no_artifact(db, owner, saver):
    """The plan gate, driven by the real graph, then approved — and still no artifact."""
    run = await v2_runtime.create_run(
        db,
        owner_id=owner["user_id"],
        project_id=owner["project_id"],
        question=QUESTION,
        depth="fast",
        demo=True,
        skip_plan_gate=False,
    )
    await db.commit()

    outcome = await runner.run(
        checkpointer=saver,
        session_id=str(run.id),
        user_id=str(owner["user_id"]),
        query=QUESTION,
        depth="fast",
        run_config=fake_config(skip_plan_gate=False),
    )
    assert outcome.status == "awaiting_plan", outcome.status
    result = await v2_execution.persist_outcome(db, run, outcome, saver=saver)
    await db.commit()

    assert result.status == "AWAITING_PLAN"
    assert run.status == "AWAITING_PLAN"
    plan = (await db.execute(select(v2_runtime.ResearchPlan))).scalar_one()
    assert plan.origin == "MODEL_PROPOSED"
    assert plan.approved_at is None, "the proposal is not a decision"
    assert plan.tasks, "the real planner produced no tasks"

    review = await v2_runtime.record_plan_review(db, run, plan, reviewer_id=owner["user_id"])
    await db.commit()
    assert review.revision_id is None
    with pytest.raises(v2_runtime.LifecycleError, match="no APPROVED REPORT review"):
        await v2_runtime.create_artifact(db, run)
    assert await _count(db, ResearchArtifact) == 0


async def test_a_cross_run_claim_evidence_link_is_rejected(db, owner, saver):
    from sqlalchemy.exc import IntegrityError

    first = await execute(db, owner, saver)
    second = await execute(db, owner, saver)

    claim = (
        (await db.execute(select(Claim).where(Claim.run_id == first["run"].id))).scalars().first()
    )
    foreign = (
        (await db.execute(select(Evidence).where(Evidence.run_id == second["run"].id)))
        .scalars()
        .first()
    )
    assert claim is not None and foreign is not None

    with pytest.raises(IntegrityError):
        await db.execute(
            insert(ClaimEvidenceLink).values(
                id=uuid.uuid4(),
                run_id=first["run"].id,
                claim_id=claim.id,
                evidence_id=foreign.id,
                stance="SUPPORTS",
                origin="CITATION_MARKER",
            )
        )
    await db.rollback()


async def test_a_tampered_approved_report_fails_verification(db, owner, saver):
    """The check that makes the artifact worth producing."""
    state = await execute(db, owner, saver)
    run = state["run"]
    revision = (await db.execute(select(Revision).where(Revision.run_id == run.id))).scalars().one()
    await v2_runtime.record_report_review(
        db, run, revision, reviewer_id=owner["user_id"], decision="APPROVED"
    )
    await db.commit()

    # Rewrite the approved bytes without touching the hash.
    revision.report_markdown = revision.report_markdown + "\n\nAn inserted sentence.\n"
    await db.commit()

    manifest = await v2_bundle.assemble(db, run.id)
    verdict = verify_bundle.verify(manifest)
    assert not verdict.passed
    failed = {c.name for c in verdict.checks if not c.passed}
    assert "approval_chain" in failed or "report_integrity" in failed


# ── The tri-state, in the execution path ──────────────────────────────────────────


async def test_an_unreadable_checkpoint_is_not_persisted_as_no_evidence(db, owner, saver):
    """A run whose evidence cannot be read has an unknown amount, not zero."""
    state = await execute(db, owner, saver)
    run2 = await v2_runtime.create_run(
        db, owner_id=owner["user_id"], project_id=owner["project_id"], question=QUESTION
    )
    await db.commit()

    # No checkpoint for this thread at all.
    result = await v2_execution.persist_outcome(db, run2, state["outcome"], saver=saver)
    await db.commit()
    assert result.evidence_outcome == "CHECKPOINT_MISSING"
    assert result.evidence_count == 0
    assert await _count(db, Evidence, run_id=run2.id) == 0
    # A revision is still written — the report exists — but it cites nothing, and the
    # verifier says so rather than the domain pretending the evidence was empty.
    manifest = await v2_bundle.assemble(db, run2.id)
    assert manifest is None or not verify_bundle.verify(manifest).passed


async def test_the_lifecycle_event_uses_the_existing_vocabulary(db, owner, saver):
    """No second event architecture: the same four names both hosts' stop-lists know."""
    state = await execute(db, owner, saver)
    event = v2_execution.lifecycle_event(state["result"])
    assert event["type"] == "HITL_READY"
    assert event["data"]["revision_version"] == 1

    from app.v2_execution import PersistResult

    assert v2_execution.lifecycle_event(PersistResult("FAILED", "NOT_READ"))["type"] == "FAILED"
    assert (
        v2_execution.lifecycle_event(PersistResult("AWAITING_PLAN", "NOT_READ"))["type"]
        == "PLAN_READY"
    )
    done = v2_execution.lifecycle_event(PersistResult("COMPLETED", "CHECKPOINT_MISSING"))
    assert done["type"] == "COMPLETED"
    # The tri-state reaches the client: "no evidence" and "evidence unknown" differ.
    assert done["data"]["evidence_outcome"] == "CHECKPOINT_MISSING"
