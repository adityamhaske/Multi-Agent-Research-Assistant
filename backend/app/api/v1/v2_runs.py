"""
The V2 read and review surface (V2-native runtime milestone).

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
through `app.v2_runtime`, which goes through `app.authorization` — so the rule that only an
approved report review authorizes an artifact is not restated here.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import v2_bundle, v2_runtime
from app.db.base import get_db
from app.dependencies import get_current_user
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

router = APIRouter(prefix="/v2/runs", tags=["v2"])


class CreateRunRequest(BaseModel):
    """The domain entry point for a V2-native run."""

    project_id: uuid.UUID
    question: str = Field(min_length=1, max_length=2000)
    depth: str = Field("balanced", description="fast | balanced | comprehensive")
    corpus_mode: bool = False
    skip_plan_gate: bool = True
    topic_seeds: list | None = None
    outline_template: str | None = None
    #: Dispatch the run to the worker. False creates the domain row only — used by tests
    #: that drive the engine in-process, and by any caller that wants to stage a run.
    dispatch: bool = True


class PlanReviewRequest(BaseModel):
    decision: str = Field("APPROVED", description="APPROVED | REWORK_REQUESTED | REJECTED")
    feedback: str | None = None
    dispatch: bool = True


class ReportReviewRequest(BaseModel):
    """A decision about a revision. `dispatch` drives the rework resume."""

    revision_version: int | None = Field(
        None, description="Which revision was reviewed. Defaults to the latest."
    )
    decision: str = Field(..., description="APPROVED | REWORK_REQUESTED | REJECTED")
    feedback: str | None = None
    dispatch: bool = True


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
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Run not found.")
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
):
    """Open a V2-native run.

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
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Project not found.")
    if body.depth not in RESEARCH_DEPTHS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown depth.")

    run = await v2_runtime.create_run(
        db,
        owner_id=current_user.id,
        project_id=project.id,
        question=body.question,
        depth=body.depth,
        corpus_mode=body.corpus_mode,
        skip_plan_gate=body.skip_plan_gate,
        topic_seeds=body.topic_seeds,
        outline_template=body.outline_template,
    )
    # Committed BEFORE dispatch: a worker that picks the message up first and cannot find
    # the row would fail a run that was about to exist.
    await db.commit()

    if body.dispatch:
        from app.workers.tasks import run_v2_pipeline

        run_v2_pipeline.delay(str(run.id), str(current_user.id))
    return {"run_id": str(run.id), "status": run.status, "dispatched": body.dispatch}


@router.get("")
async def list_runs(
    project_id: uuid.UUID | None = None,
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
        raise HTTPException(status.HTTP_409_CONFLICT, detail="This run has no plan to review.")
    review = await v2_runtime.record_plan_review(
        db, run, plan, reviewer_id=current_user.id, decision=body.decision, feedback=body.feedback
    )
    await db.commit()

    # An approved plan resumes the suspended graph from the design gate — the same
    # `runner.resume(plan=…)` the V1 path uses, so research the user already paid for is
    # not re-run.
    if body.decision == "APPROVED" and body.dispatch:
        from app.workers.tasks import resume_v2_plan_gate

        resume_v2_plan_gate.delay(
            str(run.id),
            str(current_user.id),
            {"tasks": plan.tasks, "sections": plan.outline_sections},
        )
    return {"review_id": str(review.id), "gate": "PLAN", "decision": review.decision}


@router.post("/{run_id}/report-review", status_code=status.HTTP_201_CREATED)
async def submit_report_review(
    run_id: uuid.UUID,
    body: ReportReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
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
        raise HTTPException(status.HTTP_409_CONFLICT, detail="This run has no report to review.")

    try:
        review = await v2_runtime.record_report_review(
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
            artifact = await v2_runtime.create_artifact(db, run)
            artifact_id = str(artifact.id)
        elif body.decision == "REWORK_REQUESTED":
            run.status = "RUNNING"
        await db.commit()
        if body.decision == "REWORK_REQUESTED" and body.dispatch:
            from app.workers.tasks import resume_v2_pipeline

            # `route_after_gate` sends a rejected draft back to the SYNTHESIZER, not the
            # executor — the same evidence, resynthesized — so the next revision costs one
            # synthesis rather than a whole run.
            resume_v2_pipeline.delay(str(run.id), str(current_user.id), False, body.feedback)
    except v2_runtime.LifecycleError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return {
        "review_id": str(review.id),
        "gate": "REPORT",
        "decision": review.decision,
        "artifact_id": artifact_id,
    }


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
        manifest, reason = await v2_bundle.assemble_with_reason(db, run.id)
        if manifest is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"No bundle can be assembled for this run ({reason}).",
            )
        payload = manifest.model_dump()

    import json

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
        manifest, reason = await v2_bundle.assemble_with_reason(db, run.id)
    if manifest is None:
        return {"assembled": False, "reason": reason, "passed": None, "checks": []}

    result = v2_bundle.verify(manifest)
    return {
        "assembled": True,
        "reason": None,
        "passed": result.passed,
        "bundle_hash": manifest.bundle_hash,
        "frozen": artifact is not None,
        "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in result.checks],
    }
