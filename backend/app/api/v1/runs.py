"""
The read and review surface for a research run.

**One aggregate GET, three actions.** The next milestone builds nine UI surfaces — Overview,
Research, Evidence, Claims, Sources, Contradictions, Review, Artifacts, History — and every
one of them needs a slice of the same run graph. Nine endpoints would mean nine round trips
for one page and nine places for the run-scoping predicate to be got wrong; one projection
means the authorization check happens once, in one place.

The shapes here are deliberately thin over the domain: no field is renamed, nothing is
flattened, and the three-valued vocabularies (`provenance_state`, `detection_state`,
`verification_state`) travel as they are stored. A UI that wants to render "⚠ unverified"
must be able to tell `UNCHECKED` from `UNATTESTED`, and collapsing them here to save a few
bytes would put the product's central claim behind a translation layer.

**`citation_index` is nullable and that is load-bearing.** A source with no index was
retrieved and never cited. The UI must not number it.

Actions are the two gates and the artifact. `POST /plan-review` and `POST /report-review` go
through `app.run_lifecycle`, which goes through `app.authorization` — so the rule that only an
approved report review authorizes an artifact is not restated here.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator

import structlog
from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import run_bundle, run_lifecycle
from app.db.base import AsyncSessionLocal, get_db
from app.db.redis import get_redis
from app.dependencies import get_current_user
from app.errors import Conflict, NotFound, Unprocessable
from app.models.agent_log import AgentLog
from app.models.project import Project
from app.models.research import (
    RESEARCH_DEPTHS,
    Contradiction,
    Evidence,
    ResearchPlan,
    ResearchRun,
    Source,
)
from app.models.review import ResearchArtifact, Review
from app.models.revision import Claim, ClaimEvidenceLink, Revision
from app.models.user import User
from app.run_dispatch import RunDispatcher

# Request bodies live in app/schemas/runs.py so the desktop sidecar can import the exact
# same contract without this module's `app.config` chain (#50). Re-exported here: this
# is where the routes and their tests have always referred to them.
from app.schemas.runs import (  # noqa: F401  (re-export)
    CreateRunRequest,
    PlanReviewRequest,
    ReportReviewRequest,
)
from app.services import model_routing
from app.services.event_stream import sse_frames
from app.services.sse import SSE_HEADERS
from app.workers.dispatch import get_run_dispatcher
from research_engine.bundle import render_model_attribution_md, stamp_demo_md

logger = structlog.get_logger()
router = APIRouter(prefix="/runs", tags=["Runs"])

#: Events after which the stream closes: two terminals plus the two gates. A graph
#: suspended at an interrupt publishes nothing more until a human acts, so a connection
#: held open there waits on no one. Mirrors the session stream's stop-list and
#: `sidecar._TERMINAL_EVENTS`.
_TERMINAL_EVENTS = ("COMPLETED", "FAILED", "HITL_READY", "PLAN_READY")

#: Events after which *replay* stops — only the true terminals, deliberately NOT the gates.
#:
#: The distinction matters and this route originally missed it. `_TERMINAL_EVENTS` is the right
#: rule for the live tail: a graph suspended at an interrupt publishes nothing more, so
#: holding the socket open waits on no one. Applying it to the backlog is a different
#: statement — "stop reading history at the first gate" — and it is wrong. A client that
#: reconnects without a `Last-Event-ID` (a fresh EventSource, which is what a status
#: change creates) replays from id 0, hits the `PLAN_READY` row left over from the design
#: gate, and returns: everything the run did *after* the gate is never delivered, and the
#: live tail is never reached either. The session stream stops replay on
#: `("COMPLETED", "FAILED")` only, for exactly this reason; this route copied the tail's list into
#: both places.
_REPLAY_STOP_EVENTS = ("COMPLETED", "FAILED")

#: Run states in which nothing further will be published until a human acts, so the stream
#: closes after replaying the backlog instead of tailing.
#:
#: This is the check that `_TERMINAL_EVENTS` used to perform accidentally, by stopping the
#: *replay* at a gate. Doing it on the run's current status instead separates the two
#: questions properly: "has history moved past a gate" (it may have, and the client needs
#: what came after) versus "is the run sitting at one right now" (then there is nobody to
#: wait for). Without this, removing the gates from the replay rule would leave a client
#: reconnecting to a gate-parked run holding a socket nothing will ever write to.
_SUSPENDED_STATUSES = ("COMPLETED", "FAILED", "CANCELLED", "AWAITING_PLAN", "AWAITING_REVIEW")


async def _run_or_404(db: AsyncSession, run_id: uuid.UUID, owner_id: uuid.UUID) -> ResearchRun:
    """Ownership is a single-table predicate, which is why `owner_id` is denormalised.

    A run belonging to someone else is a 404 rather than a 403: the difference between
    "does not exist" and "exists and is not yours" is itself information.
    """
    run = (
        await db.execute(
            select(ResearchRun).where(ResearchRun.id == run_id, ResearchRun.owner_id == owner_id)
        )
    ).scalar_one_or_none()
    if run is None:
        raise NotFound("Run not found.")
    return run


async def project_run(db: AsyncSession, run: ResearchRun) -> dict:
    """The whole run graph, host-agnostic so the desktop sidecar serves the same shape."""
    plans = (
        (
            await db.execute(
                select(ResearchPlan)
                .where(ResearchPlan.run_id == run.id)
                .order_by(ResearchPlan.version.asc())
            )
        )
        .scalars()
        .all()
    )
    sources = (
        (
            await db.execute(
                select(Source)
                .where(Source.run_id == run.id)
                # Uncited sources sort last rather than being hidden: "retrieved but not
                # cited" is a state the UI should be able to show.
                .order_by(Source.citation_index.is_(None), Source.citation_index.asc())
            )
        )
        .scalars()
        .all()
    )
    evidence = (
        (
            await db.execute(
                select(Evidence)
                .where(Evidence.run_id == run.id)
                .order_by(Evidence.sequence.asc(), Evidence.id.asc())
            )
        )
        .scalars()
        .all()
    )
    revisions = (
        (
            await db.execute(
                select(Revision).where(Revision.run_id == run.id).order_by(Revision.version.asc())
            )
        )
        .scalars()
        .all()
    )
    claims = (
        (
            await db.execute(
                select(Claim).where(Claim.run_id == run.id).order_by(Claim.position.asc())
            )
        )
        .scalars()
        .all()
    )
    links = (
        (await db.execute(select(ClaimEvidenceLink).where(ClaimEvidenceLink.run_id == run.id)))
        .scalars()
        .all()
    )
    contradictions = (
        (await db.execute(select(Contradiction).where(Contradiction.run_id == run.id)))
        .scalars()
        .all()
    )
    reviews = (
        (
            await db.execute(
                select(Review).where(Review.run_id == run.id).order_by(Review.sequence.asc())
            )
        )
        .scalars()
        .all()
    )
    artifact = (
        await db.execute(select(ResearchArtifact).where(ResearchArtifact.run_id == run.id))
    ).scalar_one_or_none()

    return {
        "run": {
            "id": str(run.id),
            "project_id": str(run.project_id),
            "question": run.question,
            "status": run.status,
            "depth": run.depth,
            "corpus_mode": run.corpus_mode,
            "demo": run.demo,
            "skip_plan_gate": run.skip_plan_gate,
            "model_routing": run.model_routing,
            "cost_usd": float(run.cost_usd),
            "tokens_input": run.tokens_input,
            "tokens_output": run.tokens_output,
            "elapsed_seconds": float(run.elapsed_seconds) if run.elapsed_seconds else None,
            # NULL means unmeasured. Never rendered as 0 — that distinction is the product.
            "citation_resolution_rate": (
                float(run.citation_resolution_rate)
                if run.citation_resolution_rate is not None
                else None
            ),
            "error_message": run.error_message,
            "cancelled_at": run.cancelled_at.isoformat() if run.cancelled_at else None,
            "created_at": run.created_at.isoformat(),
            "updated_at": run.updated_at.isoformat(),
        },
        "plans": [
            {
                "id": str(p.id),
                "version": p.version,
                "tasks": p.tasks,
                "outline_sections": p.outline_sections,
                "origin": p.origin,
                "approved_at": p.approved_at.isoformat() if p.approved_at else None,
            }
            for p in plans
        ],
        "sources": [
            {
                "id": str(s.id),
                "url": s.url,
                "title": s.title,
                "kind": s.kind,
                "retrieval_status": s.retrieval_status,
                # None means "retrieved but never cited". The UI must not number it.
                "citation_index": s.citation_index,
                "corpus_document_id": s.corpus_document_id,
            }
            for s in sources
        ],
        "evidence": [
            {
                "id": str(e.id),
                "source_id": str(e.source_id),
                "sequence": e.sequence,
                "task_id": e.task_id,
                "snippet": e.snippet,
                "content_hash": e.content_hash,
                "key_fact": e.key_fact,
                # Three-valued and passed through: UNCHECKED is not UNATTESTED.
                "provenance_state": e.provenance_state,
                "attested_against": e.attested_against,
                "attestation_run_at": (
                    e.attestation_run_at.isoformat() if e.attestation_run_at else None
                ),
            }
            for e in evidence
        ],
        "revisions": [
            {
                "id": str(r.id),
                "version": r.version,
                "report_markdown": r.report_markdown,
                "report_hash": r.report_hash,
                "evidence_watermark": r.evidence_watermark,
                "created_at": r.created_at.isoformat(),
            }
            for r in revisions
        ],
        "claims": [
            {
                "id": str(c.id),
                "revision_id": str(c.revision_id),
                "position": c.position,
                "text": c.text,
                "extraction_method": c.extraction_method,
                "verification_state": c.verification_state,
                "verification_method": c.verification_method,
                "lineage_id": str(c.lineage_id) if c.lineage_id else None,
            }
            for c in claims
        ],
        "claim_evidence_links": [
            {
                "id": str(link.id),
                "claim_id": str(link.claim_id),
                "evidence_id": str(link.evidence_id),
                "stance": link.stance,
                "origin": link.origin,
            }
            for link in links
        ],
        "contradictions": [
            {
                "id": str(c.id),
                # Source anchors are what a detection means; evidence anchors are a
                # refinement and are often NULL.
                "source_a_id": str(c.source_a_id) if c.source_a_id else None,
                "source_b_id": str(c.source_b_id) if c.source_b_id else None,
                "evidence_a_id": str(c.evidence_a_id) if c.evidence_a_id else None,
                "evidence_b_id": str(c.evidence_b_id) if c.evidence_b_id else None,
                "quote_a": c.quote_a,
                "quote_b": c.quote_b,
                "summary_a": c.summary_a,
                "summary_b": c.summary_b,
                "nature": c.nature,
                "dimension": c.dimension,
                "detection_state": c.detection_state,
                "review_state": c.review_state,
            }
            for c in contradictions
        ],
        "reviews": [
            {
                "id": str(r.id),
                "sequence": r.sequence,
                "gate": r.gate,
                "decision": r.decision,
                "revision_id": str(r.revision_id) if r.revision_id else None,
                "plan_version_id": str(r.plan_version_id) if r.plan_version_id else None,
                "feedback": r.feedback,
                "reviewed_hash": r.reviewed_hash,
                "created_at": r.created_at.isoformat(),
            }
            for r in reviews
        ],
        "artifact": (
            {
                "id": str(artifact.id),
                "artifact_hash": artifact.artifact_hash,
                "format_version": artifact.format_version,
                "review_id": str(artifact.review_id) if artifact.review_id else None,
                "review_gate": artifact.review_gate,
                "review_decision": artifact.review_decision,
                "revision_id": str(artifact.revision_id) if artifact.revision_id else None,
                "demo": artifact.demo,
                "created_at": artifact.created_at.isoformat(),
            }
            if artifact
            else None
        ),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_run(
    body: CreateRunRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    dispatcher: RunDispatcher = Depends(get_run_dispatcher),
):
    """Open a run.

    Creates the domain row only. Execution is still the existing pipeline — this milestone
    changes where a run's results are *persisted*, not how research is performed, so there
    is deliberately no second executor here.
    """
    project = (
        await db.execute(
            select(Project).where(Project.id == body.project_id, Project.user_id == current_user.id)
        )
    ).scalar_one_or_none()
    if project is None:
        raise NotFound("Project not found.")
    if body.depth not in RESEARCH_DEPTHS:
        raise Unprocessable("Unknown depth.")

    # Refused here rather than repaired: a routing that survives `validate` is startable,
    # so a run cannot die halfway through on a model that was never routable. Stamping the
    # snapshot at creation is what makes the choice durable — `run_config_for_run` treats a
    # present `model_routing` as authoritative, so every role, every resume and the report's
    # own model attribution read the models this request named.
    routing = None
    if body.model_routing is not None:
        try:
            routing = model_routing.validate(body.model_routing)
        except model_routing.InvalidRouting as exc:
            raise Unprocessable(str(exc)) from exc

    run = await run_lifecycle.create_run(
        db,
        owner_id=current_user.id,
        project_id=project.id,
        question=body.question,
        depth=body.depth,
        corpus_mode=body.corpus_mode,
        skip_plan_gate=body.skip_plan_gate,
        topic_seeds=body.topic_seeds,
        outline_template=body.outline_template,
        model_routing=routing,
    )
    # Committed BEFORE dispatch: a worker that picks the message up first and cannot find
    # the row would fail a run that was about to exist.
    await db.commit()

    if body.dispatch:
        await dispatcher.start(str(run.id), str(current_user.id))
    return {"run_id": str(run.id), "status": run.status, "dispatched": body.dispatch}


@router.get("")
async def list_runs(
    project_id: uuid.UUID | None = None,
    archived: bool = False,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """This owner's runs, newest first, optionally scoped to one project.

    A summary rather than the graph: History renders a list, and shipping the full
    projection per row would carry every report's markdown to draw a table.
    """
    query = select(ResearchRun).where(ResearchRun.owner_id == current_user.id)
    if project_id is not None:
        query = query.where(ResearchRun.project_id == project_id)
    if archived:
        query = query.where(ResearchRun.archived_at.is_not(None))
    else:
        query = query.where(ResearchRun.archived_at.is_(None))
    runs = (
        (await db.execute(query.order_by(ResearchRun.created_at.desc()).limit(min(limit, 200))))
        .scalars()
        .all()
    )
    artifacts = {
        a.run_id
        for a in (
            await db.execute(
                select(ResearchArtifact).where(ResearchArtifact.owner_id == current_user.id)
            )
        )
        .scalars()
        .all()
    }
    return {
        "runs": [
            {
                "id": str(r.id),
                "project_id": str(r.project_id),
                "question": r.question,
                "status": r.status,
                "depth": r.depth,
                "demo": r.demo,
                "cost_usd": float(r.cost_usd),
                "citation_resolution_rate": (
                    float(r.citation_resolution_rate)
                    if r.citation_resolution_rate is not None
                    else None
                ),
                "has_artifact": r.id in artifacts,
                "archived_at": r.archived_at.isoformat() if r.archived_at else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in runs
        ]
    }


@router.get("/{run_id}")
async def get_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The whole run graph in one response — see the module docstring for why."""
    return await project_run(db, await _run_or_404(db, run_id, current_user.id))


@router.post("/{run_id}/plan-review", status_code=status.HTTP_201_CREATED)
async def submit_plan_review(
    run_id: uuid.UUID,
    body: PlanReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    dispatcher: RunDispatcher = Depends(get_run_dispatcher),
):
    """A decision about the latest plan version. It authorizes no artifact, ever."""
    run = await _run_or_404(db, run_id, current_user.id)
    plan = (
        (
            await db.execute(
                select(ResearchPlan)
                .where(ResearchPlan.run_id == run.id)
                .order_by(ResearchPlan.version.desc())
            )
        )
        .scalars()
        .first()
    )
    if plan is None:
        raise Conflict("This run has no plan to review.")
    # `None` means "unedited, use the proposal" — not the same as `[]`, which is a reviewer
    # who excluded everything and gets the 422 below.
    proposed = plan.tasks or []
    tasks = body.tasks if body.tasks is not None else proposed
    kept = [t for t in tasks if t.get("include", True)]

    # Refused before the decision is recorded, not after: an approval that selects nothing
    # authorizes a run that can only produce an evidence-free report, and a recorded
    # APPROVED review is evidence in its own right.
    #
    # The session gate (`research.submit_plan`) has always enforced this; this one shipped without it,
    # which is how a run whose four subtopics were *all* proposed `include: false` was
    # approved, searched nothing, and still reached the report gate with eleven claims and
    # zero evidence. One rule, one wording, both paths — the desktop host imports this same
    # handler, so it is fixed there by construction (AGENTS.md, "two hosts, one contract").
    if body.decision == "APPROVED" and not kept:
        raise Unprocessable(
            "Keep at least one task — a plan with nothing in it researches nothing."
        )

    # An edit becomes its own plan version rather than overwriting the proposal, so the
    # design a run actually executed stays readable next to what the model suggested —
    # `origin` is what tells those two apart, and a single overwritten plan column never could. The
    # review is then recorded against the version it approved, not the one it replaced.
    if body.decision == "APPROVED" and body.tasks is not None and kept != proposed:
        plan = await run_lifecycle.record_plan(
            db,
            run,
            tasks=kept,
            outline_sections=plan.outline_sections,
            origin="HUMAN_EDITED",
        )

    review = await run_lifecycle.record_plan_review(
        db, run, plan, reviewer_id=current_user.id, decision=body.decision, feedback=body.feedback
    )
    if body.decision == "APPROVED" and body.dispatch:
        # Move to RUNNING in the SAME transaction as the decision, before the task is
        # queued. The worker sets it too, but a client that refetches on the mutation's
        # success would otherwise read AWAITING_PLAN, conclude nothing is live, keep its
        # event stream closed and never learn the run had resumed — a workspace that goes
        # stale the moment you approve a plan. Found by the plan-gate journey.
        await run_lifecycle.set_status(db, run, "RUNNING")
    await db.commit()

    # An approved plan resumes the suspended graph from the design gate — the same
    # `runner.resume(plan=…)` the session path uses, so research the user already paid for is
    # not re-run.
    if body.decision == "APPROVED" and body.dispatch:
        # `kept`, not `plan.tasks`: the executor is handed exactly what was approved. The
        # graph filters `include: false` again at the gate, but relying on that would mean
        # the resume payload and the recorded plan disagreed about what the run is doing.
        await dispatcher.resume_plan(
            str(run.id),
            str(current_user.id),
            {"tasks": kept, "sections": plan.outline_sections},
        )
    return {"review_id": str(review.id), "gate": "PLAN", "decision": review.decision}


@router.post("/{run_id}/report-review", status_code=status.HTTP_201_CREATED)
async def submit_report_review(
    run_id: uuid.UUID,
    body: ReportReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    dispatcher: RunDispatcher = Depends(get_run_dispatcher),
):
    """A decision about a revision. On APPROVED, the artifact is frozen in the same
    transaction — so an approval that cannot produce a verifiable artifact is not recorded
    as an approval at all."""
    run = await _run_or_404(db, run_id, current_user.id)
    query = select(Revision).where(Revision.run_id == run.id)
    if body.revision_version is not None:
        query = query.where(Revision.version == body.revision_version)
    revision = (await db.execute(query.order_by(Revision.version.desc()))).scalars().first()
    if revision is None:
        raise Conflict("This run has no report to review.")

    try:
        review = await run_lifecycle.record_report_review(
            db,
            run,
            revision,
            reviewer_id=current_user.id,
            decision=body.decision,
            feedback=body.feedback,
        )
        artifact_id = None
        if body.decision == "APPROVED":
            run.status = "COMPLETED"
            # Measured before the artifact is frozen, and in the same transaction as the
            # approval: it is a statement about the exact bytes this reviewer approved.
            await run_lifecycle.measure_citation_resolution(db, run, revision)
            artifact = await run_lifecycle.create_artifact(db, run)
            artifact_id = str(artifact.id)
        elif body.decision == "REWORK_REQUESTED":
            run.status = "RUNNING"
        await db.commit()
        if body.decision == "REWORK_REQUESTED" and body.dispatch:
            # `route_after_gate` sends a rejected draft back to the SYNTHESIZER, not the
            # executor — the same evidence, resynthesized — so the next revision costs one
            # synthesis rather than a whole run.
            await dispatcher.rework(str(run.id), str(current_user.id), body.feedback)
    except run_lifecycle.LifecycleError as exc:
        await db.rollback()
        raise Conflict(str(exc)) from exc

    # Read off the ORM rows *before* the ingest attempts. Either may fail and roll back,
    # and a rollback expires every object in the identity map — so a response assembled
    # afterwards would lazily reload `review` outside the greenlet and turn a best-effort
    # indexing failure into a 500 on an approval that has already been committed.
    response = {
        "review_id": str(review.id),
        "gate": "REPORT",
        "decision": review.decision,
        "artifact_id": artifact_id,
    }

    if body.decision == "APPROVED":
        # Both stores, after the commit and never inside the approval transaction:
        # embedding cost and provider availability must not be able to fail an approval
        # that has already been recorded. Neither call raises.
        await _ingest_report_into_corpus(db, run, revision.report_markdown)
        await _ingest_report_into_memory(db, run, revision.report_markdown)

    return response


async def _ingest_report_into_corpus(db: AsyncSession, run, report_markdown: str) -> None:
    """Auto-save an approved report into its project's corpus. Best-effort; never
    raises — see report_corpus.ingest_report's own docstring for why."""
    try:
        from app import adapters
        from app.run_execution import provider_keys_for
        from app.services.report_corpus import ingest_report

        store = await adapters.ServerCorpusLocator().ensure(
            run.project_id, keys=await provider_keys_for(db, run.owner_id)
        )
        await ingest_report(store, session_id=str(run.id), report_markdown=report_markdown)
    except Exception as e:  # noqa: BLE001 — see report_corpus.ingest_report's own docstring
        logger.warning("report_corpus_ingest_setup_failed", run_id=str(run.id), error=str(e))


async def _ingest_report_into_memory(db: AsyncSession, run, report_markdown: str) -> None:
    """Add an approved report to its project's memory — the store project chat reads.

    Approval is the quality filter that makes retrieval trustworthy, so this sits on the
    approval transition and nowhere else. Best-effort by the same rule as the corpus write:
    the run has already succeeded and committed, and failing it retroactively because an
    embedding provider was down would destroy work in order to report a gap. The gap is
    reported instead, by `memory/status`, which counts approved reports against indexed
    ones and self-heals on the next re-index.
    """
    from app.services import memory

    if not memory.is_available(db):
        # Absent on the desktop host by design, which the parity tables and the UI both
        # already state. Skipping quietly is correct there; warning on every approval
        # would report a decision as a gap.
        return
    try:
        from app import adapters
        from app.run_execution import provider_keys_for

        embedder = await adapters.embeddings_for(await provider_keys_for(db, run.owner_id))
        result = await memory.ingest_run(db, run, report_markdown, embedder)
        if result.skipped:
            logger.info("memory_ingest_skipped", run_id=str(run.id), reason=result.reason)
    except Exception as e:  # noqa: BLE001 — see docstring: never fail a committed run
        await db.rollback()
        logger.warning("memory_ingest_failed", run_id=str(run.id), error=str(e))


@router.get("/{run_id}/bundle.json")
async def get_bundle(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The verifiable bundle. Served from the frozen artifact once one exists.

    Before approval it is assembled live, which is the honest answer to "what would be
    frozen if I approved this?". After approval the artifact's `payload` is authoritative:
    re-assembling would silently pick up anything that changed since.
    """
    run = await _run_or_404(db, run_id, current_user.id)
    artifact = (
        await db.execute(select(ResearchArtifact).where(ResearchArtifact.run_id == run.id))
    ).scalar_one_or_none()
    if artifact is not None:
        payload = artifact.payload
    else:
        manifest, reason = await run_bundle.assemble_with_reason(db, run.id)
        if manifest is None:
            raise Conflict(f"No bundle can be assembled for this run ({reason}).")
        payload = manifest.model_dump()

    filename = f"research-{str(run.id)[:8]}.bundle.json"
    return Response(
        content=json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{run_id}/verification")
async def get_verification(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Run the **shipped standalone verifier** over this run's bundle and report every check.

    Not a summary boolean: a reader who is told "verified" learns less than one who is told
    which of the six checks passed. `assembled=false` means the verifier was not run, which
    is not the same as a failure.
    """
    run = await _run_or_404(db, run_id, current_user.id)
    artifact = (
        await db.execute(select(ResearchArtifact).where(ResearchArtifact.run_id == run.id))
    ).scalar_one_or_none()
    if artifact is not None:
        from research_engine.bundle import BundleManifest

        manifest, reason = BundleManifest.model_validate(artifact.payload), None
    else:
        manifest, reason = await run_bundle.assemble_with_reason(db, run.id)
    if manifest is None:
        return {"assembled": False, "reason": reason, "passed": None, "checks": []}

    result = run_bundle.verify(manifest)
    return {
        "assembled": True,
        "reason": None,
        "passed": result.passed,
        "bundle_hash": manifest.bundle_hash,
        "frozen": artifact is not None,
        "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in result.checks],
    }


# ── SSE ───────────────────────────────────────────────────────────────────────────


@router.get("/{run_id}/stream")
async def stream_run(
    run_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    redis=Depends(get_redis),
):
    """Live run events. **The same bus, the same channel shape, the same replay rule.**

    Not a second event architecture: `agent_logs` rows are the durable backlog and the
    Redis channel is the live tail, exactly as the session stream works — the worker writes
    through `adapters.agent_log_sink`, which is why `agent_logs.session_id` had to become
    polymorphic. `Last-Event-ID` therefore replays a run from a durable id the same way.

    The stop-list is the session stream's plus nothing: a stream held open on a suspended graph waits
    on no one, so it closes at `PLAN_READY` and `HITL_READY` as well as the two terminals.
    """
    run = await _run_or_404(db, run_id, current_user.id)
    last_event_id = request.headers.get("last-event-id")
    after_id = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0

    async def gen() -> AsyncGenerator[str, None]:
        # Deferred, like the two other uses of `adapters` in this module: it reaches
        # `app.config` and `app.db.redis`, and the desktop imports this file at request
        # time. Module scope here would put the server's data plane in the desktop's
        # import tree for a route that host does not even mount.
        from app import adapters

        channel = f"session:{run_id}:events"
        pubsub = redis.pubsub()
        # Subscribe BEFORE snapshotting the backlog, so an event published in the gap is
        # queued rather than lost from both — the trap the session stream already documents.
        await pubsub.subscribe(channel)
        try:
            async with AsyncSessionLocal() as sdb:
                backlog = (
                    (
                        await sdb.execute(
                            select(AgentLog)
                            .where(AgentLog.session_id == run_id, AgentLog.id > after_id)
                            .order_by(AgentLog.id.asc())
                        )
                    )
                    .scalars()
                    .all()
                )

            # The loop itself is `app/services/event_stream.py`, shared with the session
            # stream and both desktop streams. What stays here is the half that genuinely
            # differs: where the backlog is read and what the live feed is.
            async for frame in sse_frames(
                connected={"type": "connected", "run_id": str(run_id)},
                backlog=[(row.id, row.payload) for row in backlog],
                live=adapters.redis_event_stream(pubsub),
                replay_stop=_REPLAY_STOP_EVENTS,
                terminal_stop=_TERMINAL_EVENTS,
                already_done=run.status in _SUSPENDED_STATUSES,
                seen_from=after_id,
            ):
                yield frame
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)


# ── Exports ───────────────────────────────────────────────────────────────────────


async def _latest_revision(db: AsyncSession, run: ResearchRun, version: int | None):
    query = select(Revision).where(Revision.run_id == run.id)
    if version is not None:
        query = query.where(Revision.version == version)
    revision = (await db.execute(query.order_by(Revision.version.desc()))).scalars().first()
    if revision is None:
        raise NotFound("This run has no report yet.")
    return revision


async def _source_dicts(db: AsyncSession, run_id) -> list[dict]:
    """The numbered source list an export renders. Uncited sources are excluded — they
    have no `[n]` to render against, and inventing one is the thing this product exists to refuse."""
    rows = (
        (
            await db.execute(
                select(Source)
                .where(Source.run_id == run_id, Source.citation_index.isnot(None))
                .order_by(Source.citation_index)
            )
        )
        .scalars()
        .all()
    )
    return [{"index": s.citation_index, "url": s.url, "title": s.title or ""} for s in rows]


@router.get("/{run_id}/export.md")
async def export_markdown(
    run_id: uuid.UUID,
    revision_version: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The approved bytes, plus the model-attribution footer both hosts already share."""
    run = await _run_or_404(db, run_id, current_user.id)
    revision = await _latest_revision(db, run, revision_version)
    body = _demo_stamped(run, revision.report_markdown) + render_model_attribution_md(
        run.model_routing
    )
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="research-{str(run.id)[:8]}.md"'},
    )


@router.get("/{run_id}/export.pdf")
async def export_pdf(
    run_id: uuid.UUID,
    revision_version: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reuses `app.services.export.render_pdf` — one PDF pipeline, not two."""
    run = await _run_or_404(db, run_id, current_user.id)
    revision = await _latest_revision(db, run, revision_version)
    from app.services import export

    pdf = export.render_pdf(
        _demo_stamped(run, revision.report_markdown),
        await _source_dicts(db, run.id),
        title=run.question[:120],
        model_routing=run.model_routing,
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="research-{str(run.id)[:8]}.pdf"'},
    )


def _demo_stamped(run: ResearchRun, report: str) -> str:
    """Prose exports of a demo run say so; the bundle does not.

    Same split the session exports make: `report_hash` is checked against the hash a human
    approved, so injecting a banner into the bundle's report body would break verification
    for a reason that has nothing to do with the artifact's integrity. The bundle carries
    `demo` as a hash-covered field instead.
    """
    # Straight to the engine's own stamper, which is where this rule lives for both hosts
    # (`tests/test_demo_stamp_parity.py`). This used to reach it through
    # `app.api.v1.research._DEMO_STAMP`, a one-line alias of the same constant — and
    # deferring that import to call time did not make it safe, it only moved the cost to
    # the first export: `app/api/v1/research.py` imports `app.workers.tasks` at module
    # scope, so on the packaged desktop app this raised
    # `ModuleNotFoundError: No module named 'celery'` and every Markdown export answered
    # 500. It was unreachable until the desktop could complete a run, which is the kind of
    # latent break that ships. `research_engine` imports no host packages at all, so there
    # is nothing to defer.
    return stamp_demo_md(report, demo=bool(run.demo))


# ── Cancel ────────────────────────────────────────────────────────────────────────


@router.post("/{run_id}/cancel")
async def cancel_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Record that cancellation was requested. **Advisory, and the response says so.**

    The engine does not check this between nodes, so an in-flight run continues to its next
    stop. What this does guarantee is durable: the run is marked CANCELLED with a timestamp
    and an actor, and the UI must not claim the work stopped immediately. Strengthening the
    engine's cancellation is a separate change and is not made here.
    """
    run = await _run_or_404(db, run_id, current_user.id)
    if run.status in ("COMPLETED", "FAILED", "CANCELLED"):
        raise Conflict(f"This run is already {run.status}.")
    await run_lifecycle.request_cancel(db, run, by=current_user.id)
    await db.commit()
    return {
        "status": run.status,
        "cancelled_at": run.cancelled_at.isoformat(),
        # Stated in the payload so a client cannot accidentally promise more than is true.
        "advisory": True,
        "detail": (
            "Cancellation recorded. Work already in flight runs to its next checkpoint; "
            "no new research will be started for this run."
        ),
    }


# ── Archive, Restore & Delete ─────────────────────────────────────────────────────


@router.post("/{run_id}/archive")
async def archive_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark a run as archived. Idempotent."""
    run = await _run_or_404(db, run_id, current_user.id)
    await run_lifecycle.archive_run(db, run)
    await db.commit()
    return {
        "status": "ok",
        "archived": True,
        "archived_at": run.archived_at.isoformat() if run.archived_at else None,
    }


@router.post("/{run_id}/unarchive")
async def unarchive_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Restore an archived run to active history. Idempotent."""
    run = await _run_or_404(db, run_id, current_user.id)
    await run_lifecycle.unarchive_run(db, run)
    await db.commit()
    return {
        "status": "ok",
        "archived": False,
        "archived_at": None,
    }


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Permanently delete a run and all associated records.

    Refuses non-terminal runs (409 Conflict). Deletes polymorphic AgentLogs, ResearchArtifact,
    Review rows, and the ResearchRun row (cascading all dependent tables). Cleans up LangGraph
    checkpoints via checkpoints.delete_thread.
    """
    run = await _run_or_404(db, run_id, current_user.id)
    try:
        await run_lifecycle.delete_run(db, run)
    except run_lifecycle.LifecycleError as exc:
        raise Conflict(str(exc)) from exc
    await db.commit()

    from app.services import checkpoints

    try:
        await checkpoints.delete_thread(str(run_id))
    except Exception as e:  # noqa: BLE001 — user rows are gone; log and move on
        logger.warning("checkpoint_cleanup_failed", run_id=str(run_id), error=str(e))

    logger.info("run_deleted", run_id=str(run_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
