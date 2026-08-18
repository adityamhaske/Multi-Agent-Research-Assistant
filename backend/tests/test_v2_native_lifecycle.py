"""
One complete V2-native research lifecycle, end to end, with no migration engine involved.

    question → ResearchRun → ResearchPlan → Sources + Evidence → Revision
             → Claims → ClaimEvidenceLinks → Contradictions → REPORT Review
             → rework → Revision 2 → approval → ResearchArtifact → bundle → verifier PASS

The research engine is not exercised here — it is unchanged, and its own suites cover it.
What is under test is the **persistence and domain integration**: that the outcome of a run
lands in the V2 tables with the invariants the M2F Amendment made explicit, and that the
artifact a native run produces passes the same standalone verifier a migrated one does.

The dangerous cases sit beside the happy path on purpose. A lifecycle test that only proves
the happy path proves that the code can succeed, not that it cannot lie.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError

from app import v2_bundle, v2_runtime
from app.models.project import Project
from app.models.research import Contradiction, Evidence, ResearchRun, Source
from app.models.review import ResearchArtifact, Review
from app.models.revision import Claim, ClaimEvidenceLink, Revision
from app.models.user import User
from research_engine import verify_bundle
from research_engine.graph import _number_sources
from tests.migration_support import open_db

QUESTION = "Does retrieval-augmented generation improve factual accuracy?"

#: What the executor hands back. Shape is `EvidenceChunk`, verbatim — this is the contract
#: the engine already produces, not a shape invented for the test.
EVIDENCE = [
    {
        "task_id": 1,
        "source_url": "https://example.invalid/paper-a",
        "source_title": "Paper A",
        "snippet": "Retrieval grounding raised factual accuracy by nine points.",
        "key_fact": "accuracy up nine points",
    },
    {
        "task_id": 1,
        "source_url": "https://example.invalid/paper-b",
        "source_title": "Paper B",
        "snippet": "Grounding reduced accuracy on the adversarial split.",
        "key_fact": "accuracy down on adversarial",
    },
    {
        "task_id": 2,
        "source_url": "https://example.invalid/paper-a",
        "source_title": "Paper A",
        "snippet": "The benchmark covered twelve thousand questions.",
        "key_fact": "benchmark size",
    },
]

CONTRADICTION = {
    "claim_a": "grounding improves accuracy",
    "snippet_a": EVIDENCE[0]["snippet"],
    "source_a": "https://example.invalid/paper-a",
    "claim_b": "grounding harms accuracy",
    "snippet_b": EVIDENCE[1]["snippet"],
    "source_b": "https://example.invalid/paper-b",
    "nature": "the two cannot both hold for the same benchmark",
}

DRAFT = (
    "# Findings\n\n"
    "Retrieval grounding raised factual accuracy on the main split [1]. "
    "The same technique reduced accuracy on the adversarial split [2].\n\n"
    "## Sources\n\n1. https://example.invalid/paper-a\n2. https://example.invalid/paper-b\n"
)
FINAL = DRAFT.replace("# Findings", "# Findings (revised)")


@pytest.fixture
async def db(tmp_path):
    async with open_db(tmp_path / "native.sqlite") as maker, maker() as session:
        yield session


@pytest.fixture
async def owner(db):
    """A user and a project — the only V1 tables a native run touches, and it only reads."""
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


async def _count(db, model, **where) -> int:
    q = select(func.count()).select_from(model)
    for key, value in where.items():
        q = q.where(getattr(model, key) == value)
    return (await db.execute(q)).scalar_one()


async def drive_lifecycle(db, owner, *, approve: bool = True) -> dict:
    """The whole slice, in the order a real run reaches it.

    Returned so the dangerous-case tests can stop partway and poke at the state, rather than
    re-deriving a fixture that has drifted from the happy path.
    """
    run = await v2_runtime.create_run(
        db,
        owner_id=owner["user_id"],
        project_id=owner["project_id"],
        question=QUESTION,
        depth="balanced",
        skip_plan_gate=False,
        model_routing={"planner": "google:gemini-2.5-flash"},
    )

    # 1–2. plan proposed, then approved at the PLAN gate
    await v2_runtime.set_status(db, run, "AWAITING_PLAN")
    plan = await v2_runtime.record_plan(
        db,
        run,
        tasks=[{"id": 1, "query": "rag accuracy"}, {"id": 2, "query": "benchmark size"}],
        outline_sections=["Findings", "Limitations"],
        origin="MODEL_PROPOSED",
    )
    plan_review = await v2_runtime.record_plan_review(db, run, plan, reviewer_id=owner["user_id"])
    await v2_runtime.set_status(db, run, "RUNNING")

    # 3. evidence and the sources it names
    numbered, _ = _number_sources(EVIDENCE)
    written = await v2_runtime.record_evidence(
        db, run, evidence=EVIDENCE, numbered_sources=numbered
    )

    # 4–6. revision 1, its claims, and their links
    first = await v2_runtime.record_revision(db, run, report_markdown=DRAFT, evidence_index=written)

    # 7. contradictions
    await v2_runtime.record_contradictions(db, run, pairs=[CONTRADICTION], evidence_index=written)

    await v2_runtime.record_metrics(
        db, run, cost_usd=0.0123, tokens_input=4321, tokens_output=1234, elapsed_seconds=42.5
    )
    await v2_runtime.set_status(db, run, "AWAITING_REVIEW")
    await db.commit()

    # 8. rework, then a second immutable revision
    rework = await v2_runtime.record_report_review(
        db,
        run,
        first.revision,
        reviewer_id=owner["user_id"],
        decision="REWORK_REQUESTED",
        feedback="Say which split.",
    )
    second = await v2_runtime.record_revision(db, run, report_markdown=FINAL)
    await db.commit()

    result = {
        "run": run,
        "plan": plan,
        "plan_review": plan_review,
        "written": written,
        "revision_1": first.revision,
        "revision_2": second.revision,
        "rework": rework,
    }
    if not approve:
        return result

    # 9–10. approval, artifact, bundle
    approval = await v2_runtime.record_report_review(
        db, run, second.revision, reviewer_id=owner["user_id"], decision="APPROVED"
    )
    await v2_runtime.set_status(db, run, "COMPLETED")
    artifact = await v2_runtime.create_artifact(db, run)
    await db.commit()
    return result | {"approval": approval, "artifact": artifact}


# ── The happy path, step by step ──────────────────────────────────────────────────


async def test_a_native_run_walks_the_whole_lifecycle(db, owner):
    state = await drive_lifecycle(db, owner)
    run = state["run"]

    assert run.status == "COMPLETED"
    assert await _count(db, ResearchRun) == 1
    assert await _count(db, Source, run_id=run.id) == 2
    assert await _count(db, Evidence, run_id=run.id) == 3
    assert await _count(db, Revision, run_id=run.id) == 2
    assert await _count(db, Contradiction, run_id=run.id) == 1
    assert await _count(db, Review, run_id=run.id) == 3  # plan, rework, approval
    assert await _count(db, ResearchArtifact, run_id=run.id) == 1
    assert await _count(db, Claim, run_id=run.id) >= 2
    assert await _count(db, ClaimEvidenceLink, run_id=run.id) >= 2


async def test_sources_keep_retrieved_and_cited_apart(db, owner):
    """A source the synthesizer never numbered is retrieved, not cited."""
    state = await drive_lifecycle(db, owner, approve=False)
    run = state["run"]

    # An extra source reached by the executor but absent from the numbered list.
    extra = dict(EVIDENCE[0])
    extra["source_url"] = "https://example.invalid/paper-c"
    extra["source_title"] = "Paper C"
    extra["snippet"] = "An uncited aside."
    await v2_runtime.record_evidence(db, run, evidence=[extra], numbered_sources=None)
    await db.commit()

    sources = {s.url: s for s in (await db.execute(select(Source))).scalars()}
    assert sources["https://example.invalid/paper-a"].citation_index == 1
    assert sources["https://example.invalid/paper-b"].citation_index == 2
    assert sources["https://example.invalid/paper-c"].citation_index is None
    # And the uncited source is not silently given a number to fill the gap.
    assert await _count(db, Source, run_id=run.id) == 3


async def test_evidence_is_never_born_attested(db, owner):
    """V1's snippet check records nothing per item, so a native run inherits that absence."""
    await drive_lifecycle(db, owner, approve=False)
    rows = (await db.execute(select(Evidence))).scalars().all()
    assert rows
    for e in rows:
        assert e.provenance_state == "UNCHECKED"
        assert e.attested_against is None and e.attestation_run_at is None
        assert e.content_hash == v2_runtime.content_hash(e.snippet)


async def test_rework_appends_a_revision_and_never_overwrites(db, owner):
    await drive_lifecycle(db, owner)
    revisions = (await db.execute(select(Revision).order_by(Revision.version))).scalars().all()
    assert [r.version for r in revisions] == [1, 2]
    assert revisions[0].report_markdown == DRAFT, "revision 1 must survive the rework"
    assert revisions[1].report_markdown == FINAL
    assert revisions[0].report_hash != revisions[1].report_hash
    # The watermark is a threshold over evidence visible at synthesis, and both revisions
    # synthesized from the same three items.
    assert revisions[0].evidence_watermark == revisions[1].evidence_watermark == 3


async def test_claims_belong_to_their_revision_and_carry_no_lineage(db, owner):
    state = await drive_lifecycle(db, owner)
    for revision in (state["revision_1"], state["revision_2"]):
        claims = (
            (await db.execute(select(Claim).where(Claim.revision_id == revision.id)))
            .scalars()
            .all()
        )
        assert claims, f"revision {revision.version} derived no claims"
        for c in claims:
            assert c.extraction_method == "DERIVED_FROM_REPORT"
            assert c.verification_state == "UNCHECKED"
            assert c.verification_method == "NOT_RUN"
            assert c.lineage_id is None, "no semantic lineage may be invented across revisions"


async def test_claim_evidence_links_resolve_the_citation_markers(db, owner):
    await drive_lifecycle(db, owner)
    links = (await db.execute(select(ClaimEvidenceLink))).scalars().all()
    assert links
    evidence_ids = {e.id for e in (await db.execute(select(Evidence))).scalars()}
    for link in links:
        assert link.evidence_id in evidence_ids
        assert link.stance == "SUPPORTS"
        assert link.origin == "CITATION_MARKER"


async def test_a_contradiction_is_two_attributed_quotations(db, owner):
    await drive_lifecycle(db, owner)
    row = (await db.execute(select(Contradiction))).scalar_one()

    assert row.detection_state == "DETECTED"
    assert row.source_a_id is not None and row.source_b_id is not None
    assert row.quote_a == EVIDENCE[0]["snippet"]
    assert row.quote_b == EVIDENCE[1]["snippet"]
    assert row.nature == CONTRADICTION["nature"]
    assert row.summary_a and row.summary_b
    # Both quotations are unique within their source, so the refinement resolves.
    assert row.evidence_a_id is not None and row.evidence_b_id is not None
    assert row.dimension == "UNCLASSIFIED"


async def test_reviews_carry_their_gate_target_and_position(db, owner):
    state = await drive_lifecycle(db, owner)
    reviews = (await db.execute(select(Review).order_by(Review.sequence))).scalars().all()

    assert [r.sequence for r in reviews] == [1, 2, 3]
    plan, rework, approval = reviews
    assert plan.gate == "PLAN" and plan.revision_id is None and plan.plan_version_id
    assert rework.gate == "REPORT" and rework.decision == "REWORK_REQUESTED"
    assert rework.revision_id == state["revision_1"].id
    assert approval.gate == "REPORT" and approval.decision == "APPROVED"
    assert approval.revision_id == state["revision_2"].id
    # The approval binds to the exact bytes reviewed.
    assert approval.reviewed_hash == state["revision_2"].report_hash


async def test_the_artifact_binds_to_the_approved_revision(db, owner):
    state = await drive_lifecycle(db, owner)
    artifact = state["artifact"]

    assert artifact.review_gate == "REPORT"
    assert artifact.review_decision == "APPROVED"
    assert artifact.review_id == state["approval"].id
    assert artifact.revision_id == state["revision_2"].id
    assert artifact.payload["report_hash"] == state["revision_2"].report_hash
    assert artifact.artifact_hash == artifact.payload["bundle_hash"]


# ── The bundle, checked by the shipped standalone verifier ────────────────────────


async def test_a_native_artifact_passes_the_standalone_verifier(db, owner):
    """The success criterion of the milestone, and the only one a third party can check.

    `verify_bundle.verify` is the shipped script, imported rather than reimplemented — a
    private copy of the checks would verify the artifact against its own idea of validity.
    """
    state = await drive_lifecycle(db, owner)
    manifest = await v2_bundle.assemble(db, state["run"].id)
    assert manifest is not None

    result = verify_bundle.verify(manifest)
    failed = [c.name for c in result.checks if not c.passed]
    assert result.passed, f"the verifier rejected a native artifact: {failed}"
    # Every check, named, so a future regression says which property broke.
    assert {c.name for c in result.checks} >= {
        "bundle_integrity",
        "report_integrity",
        "evidence_integrity",
        "citation_resolution",
        "claim_evidence_linkage",
        "approval_chain",
    }


async def test_the_frozen_payload_verifies_on_its_own(db, owner):
    """An artifact is a snapshot, so it must verify without touching live tables."""
    state = await drive_lifecycle(db, owner)
    from research_engine.bundle import BundleManifest

    manifest = BundleManifest.model_validate(state["artifact"].payload)
    assert verify_bundle.verify(manifest).passed


async def test_the_plan_approval_is_in_the_chain_but_authorizes_nothing(db, owner):
    state = await drive_lifecycle(db, owner)
    manifest = await v2_bundle.assemble(db, state["run"].id)
    actions = [a.action for a in manifest.approval_chain]

    assert actions == ["plan_approved", "rework_requested", "approved"]
    assert actions.count("approved") == 1, "the plan approval must not become a second one"
    # And the verifier agrees the only authorization is the report approval.
    assert verify_bundle._check_approval_chain(manifest).passed


# ── Dangerous cases ───────────────────────────────────────────────────────────────


async def test_a_plan_approval_cannot_create_an_artifact(db, owner):
    run = await v2_runtime.create_run(
        db, owner_id=owner["user_id"], project_id=owner["project_id"], question=QUESTION
    )
    plan = await v2_runtime.record_plan(
        db, run, tasks=[{"id": 1}], outline_sections=[], origin="MODEL_PROPOSED"
    )
    await v2_runtime.record_plan_review(db, run, plan, reviewer_id=owner["user_id"])
    await db.commit()

    with pytest.raises(v2_runtime.LifecycleError, match="no APPROVED REPORT review"):
        await v2_runtime.create_artifact(db, run)
    assert await _count(db, ResearchArtifact) == 0


async def test_a_rework_request_cannot_create_an_artifact(db, owner):
    state = await drive_lifecycle(db, owner, approve=False)
    with pytest.raises(v2_runtime.LifecycleError, match="no APPROVED REPORT review"):
        await v2_runtime.create_artifact(db, state["run"])
    assert await _count(db, ResearchArtifact) == 0


async def test_an_artifact_cannot_be_frozen_against_an_unapproved_revision(db, owner):
    """The approval binds to bytes. A third revision after approval must not be frozen.

    `create_artifact` assembles from the LATEST revision, so writing another one after the
    approval makes the report hash disagree with what was approved — and that must fail
    closed rather than freeze an unreviewed report.
    """
    state = await drive_lifecycle(db, owner, approve=False)
    run = state["run"]
    await v2_runtime.record_report_review(
        db, run, state["revision_2"], reviewer_id=owner["user_id"], decision="APPROVED"
    )
    await v2_runtime.record_revision(db, run, report_markdown=FINAL + "\nAn unreviewed edit.\n")
    await db.commit()

    with pytest.raises(v2_runtime.LifecycleError, match="does not match the approved"):
        await v2_runtime.create_artifact(db, run)
    assert await _count(db, ResearchArtifact) == 0


async def test_a_claim_cannot_link_to_another_runs_evidence(db, owner):
    """The composite FKs share one `run_id`, so cross-run contamination is unrepresentable."""
    first = await drive_lifecycle(db, owner, approve=False)
    second = await drive_lifecycle(db, owner, approve=False)

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


async def test_evidence_without_a_source_url_is_refused_not_invented(db, owner):
    run = await v2_runtime.create_run(
        db, owner_id=owner["user_id"], project_id=owner["project_id"], question=QUESTION
    )
    await db.commit()
    with pytest.raises(v2_runtime.LifecycleError, match="no source_url"):
        await v2_runtime.record_evidence(
            db,
            run,
            evidence=[{"task_id": 1, "source_url": "", "snippet": "unattributable"}],
        )
    await db.rollback()
    assert await _count(db, Source) == 0


async def test_a_contradiction_cannot_claim_unsupported_evidence_precision(db, owner):
    """Two evidence rows carrying the same quotation: the refinement must decline."""
    run = await v2_runtime.create_run(
        db, owner_id=owner["user_id"], project_id=owner["project_id"], question=QUESTION
    )
    duplicated = [EVIDENCE[0], dict(EVIDENCE[0], task_id=9), EVIDENCE[1]]
    numbered, _ = _number_sources(duplicated)
    written = await v2_runtime.record_evidence(
        db, run, evidence=duplicated, numbered_sources=numbered
    )
    await v2_runtime.record_contradictions(db, run, pairs=[CONTRADICTION], evidence_index=written)
    await db.commit()

    row = (await db.execute(select(Contradiction))).scalar_one()
    assert row.detection_state == "DETECTED", "the sources resolve, so the pair is real"
    assert row.evidence_a_id is None, "an ambiguous quotation must not pick a row"
    assert row.evidence_b_id is None, "and half a resolved pair is not a pair"


async def test_a_pair_naming_an_unknown_source_is_not_detected(db, owner):
    state = await drive_lifecycle(db, owner, approve=False)
    await v2_runtime.record_contradictions(
        db,
        state["run"],
        pairs=[dict(CONTRADICTION, source_b="https://elsewhere.invalid/x")],
        evidence_index=state["written"],
    )
    await db.commit()

    rows = (await db.execute(select(Contradiction))).scalars().all()
    unanchored = [r for r in rows if r.detection_state == "NOT_RUN"]
    assert len(unanchored) == 1
    assert unanchored[0].source_a_id is None and unanchored[0].source_b_id is None
    # The quotations survive: dropping a V1/V2 fact to satisfy a constraint is the other
    # failure mode, and it is no better than inventing one.
    assert unanchored[0].quote_a and unanchored[0].nature


async def test_an_unavailable_detector_is_recorded_not_omitted(db, owner):
    """A detector that did not run and a run with no conflicts are different findings."""
    state = await drive_lifecycle(db, owner, approve=False)
    await v2_runtime.record_contradictions(db, state["run"], pairs=[], detector_ran=False)
    await db.commit()

    states = {r.detection_state for r in (await db.execute(select(Contradiction))).scalars()}
    assert "DETECTOR_UNAVAILABLE" in states


async def test_a_native_plan_may_not_claim_unknown_origin(db, owner):
    """`UNKNOWN` exists for migrated V1 rows, which could not tell proposal from edit."""
    run = await v2_runtime.create_run(
        db, owner_id=owner["user_id"], project_id=owner["project_id"], question=QUESTION
    )
    with pytest.raises(v2_runtime.LifecycleError, match="migrated V1 plans only"):
        await v2_runtime.record_plan(db, run, tasks=[], outline_sections=[], origin="UNKNOWN")


async def test_cancellation_must_carry_its_timestamp(db, owner):
    """`ck_run_cancelled` ties the status to the time, so there is one entry point."""
    run = await v2_runtime.create_run(
        db, owner_id=owner["user_id"], project_id=owner["project_id"], question=QUESTION
    )
    with pytest.raises(v2_runtime.LifecycleError, match="request_cancel"):
        await v2_runtime.set_status(db, run, "CANCELLED")

    await v2_runtime.request_cancel(db, run, by=owner["user_id"])
    await db.commit()
    assert run.status == "CANCELLED" and run.cancelled_at is not None


async def test_a_run_with_no_revision_yields_no_bundle(db, owner):
    """Fails closed: no report means no bundle, not an empty one."""
    run = await v2_runtime.create_run(
        db, owner_id=owner["user_id"], project_id=owner["project_id"], question=QUESTION
    )
    await db.commit()
    manifest, reason = await v2_bundle.assemble_with_reason(db, run.id)
    assert manifest is None
    assert reason == "V2_NO_REVISION"


async def test_the_citation_resolution_rate_stays_null_until_measured(db, owner):
    run = await v2_runtime.create_run(
        db, owner_id=owner["user_id"], project_id=owner["project_id"], question=QUESTION
    )
    await v2_runtime.record_metrics(db, run, cost_usd=0, tokens_input=0, tokens_output=0)
    await db.commit()
    assert run.citation_resolution_rate is None, "unmeasured is NULL, never 0.0"
