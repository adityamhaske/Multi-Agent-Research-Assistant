"""
Assembling the verifiable artifact from the research domain tables.

One home: `app.run_lifecycle.create_artifact` freezes this into a `ResearchArtifact`.
`research_engine.bundle` is the schema and `research_engine.verify_bundle` is the checker,
both untouched — so an artifact this produces verifies with the same standalone script a
reader can run without the product.

Two refusals are load-bearing:

* **A run whose evidence was never read produces no bundle.** `research_runs.evidence_outcome`
  says whether the graph's evidence was actually recovered from its checkpoint. `READ` means
  the `evidence` rows *are* the record, so zero of them is a measured zero. Either failure
  state means the count is unknown, and a bundle asserting zero evidence there would number
  every `[n]` against nothing and claim a quality nobody observed.
* **A plan approval never serializes as `"approved"`.** `verify_bundle` treats that string
  as report authorization and no database constraint reaches a JSON file, so the guard has
  to be here.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authorization import approval_chain
from app.models.agent_log import AgentLog
from app.models.research import Contradiction, Evidence, ResearchRun, Source
from app.models.revision import Revision
from research_engine import bundle as bundle_mod
from research_engine import verify_bundle

#: The vocabulary a bundle uses for a review decision, and the only place it is written.
#: Injective, so a decision and its serialised action determine each other.
REVIEW_TO_BUNDLE_ACTION = {
    ("REPORT", "APPROVED"): "approved",
    ("REPORT", "REWORK_REQUESTED"): "rework_requested",
    # The session exports had no `rejected` action, so this pair has no counterpart there —
    # but it must still be DISTINCT, or the map stops being injective and the approval chain stops
    # being comparable. `verify_bundle` counts only `approved`, so an action it does not
    # know authorizes nothing, which is the correct outcome for a rejection.
    ("REPORT", "REJECTED"): "rejected",
    ("PLAN", "APPROVED"): "plan_approved",
    ("PLAN", "REWORK_REQUESTED"): "plan_rework_requested",
    ("PLAN", "REJECTED"): "plan_rejected",
}


async def _trace(db: AsyncSession, run_id) -> list[dict]:
    """`agent_logs` is keyed by the run id on both hosts — one query, either kind of run."""
    rows = (
        (
            await db.execute(
                select(AgentLog).where(AgentLog.session_id == run_id).order_by(AgentLog.id.asc())
            )
        )
        .scalars()
        .all()
    )
    return [row.payload for row in rows]


async def assemble_with_reason(
    db: AsyncSession, run_id
) -> tuple[bundle_mod.BundleManifest | None, str | None]:
    """Assemble the bundle from the research domain tables, or say why it cannot be."""
    run = (
        await db.execute(select(ResearchRun).where(ResearchRun.id == run_id))
    ).scalar_one_or_none()
    if run is None:
        return None, "RUN_ABSENT"

    # A bundle presents an evidence list, so it must not present one for a run whose
    # evidence was never recovered: `evidence` would be empty, every `[n]` would resolve to
    # nothing, and the bundle would assert a measured zero it never measured.
    #
    # Found by measurement, not review: an unreadable checkpoint used to emit a bundle that
    # failed its own `claim_evidence_linkage` check.
    if run.evidence_outcome in {"CHECKPOINT_MISSING", "CHECKPOINT_UNREADABLE"}:
        return None, "EVIDENCE_UNAVAILABLE"

    revision = (
        (
            await db.execute(
                select(Revision).where(Revision.run_id == run_id).order_by(Revision.version.desc())
            )
        )
        .scalars()
        .first()
    )
    if revision is None:
        return None, "NO_REVISION"

    sources = (
        (
            await db.execute(
                select(Source).where(Source.run_id == run_id).order_by(Source.citation_index)
            )
        )
        .scalars()
        .all()
    )
    evidence = (
        (
            await db.execute(
                select(Evidence)
                .where(Evidence.run_id == run_id)
                .order_by(Evidence.sequence.asc(), Evidence.id.asc())
            )
        )
        .scalars()
        .all()
    )
    by_source = {src.id: src for src in sources}

    evidence_dicts = [
        {
            "source_url": by_source[e.source_id].url if e.source_id in by_source else "",
            "source_title": (by_source[e.source_id].title or "")
            if e.source_id in by_source
            else "",
            "snippet": e.snippet,
            "key_fact": e.key_fact or "",
        }
        for e in evidence
    ]

    # The bundle's `sources` shape is what `graph._number_sources` derives from the evidence
    # list, and the `sources` table does not carry the snippet columns — so it is rebuilt
    # here by replaying that same derivation over the stored evidence. Reconstruction of a
    # documented derivation, not a normalisation: if the stored evidence disagrees with what
    # the run recorded, the rebuilt list differs and the bundle's own checks say so.
    source_dicts = []
    for src in sources:
        snippets: list[str] = []
        for e in evidence:
            if e.source_id != src.id:
                continue
            text = (e.snippet or "").strip()
            if text and text not in snippets:
                snippets.append(text)
        source_dicts.append(
            {
                "index": src.citation_index,
                "url": src.url,
                "title": src.title or "",
                "snippet": snippets[0] if snippets else "",
                "snippets": snippets,
            }
        )

    contradictions = (
        (
            await db.execute(
                select(Contradiction)
                .where(Contradiction.run_id == run_id)
                .order_by(Contradiction.id.asc())
            )
        )
        .scalars()
        .all()
    )
    # All seven fields of the exported shape. The pair is
    # `(claim_a, snippet_a, source_a, claim_b, snippet_b, source_b, nature)` and the domain now
    # holds every one of them, at the source granularity the detector actually worked in.
    contradiction_dicts = [
        {
            "claim_a": c.summary_a,
            "snippet_a": c.quote_a or "",
            "source_a": by_source[c.source_a_id].url if c.source_a_id in by_source else "",
            "claim_b": c.summary_b,
            "snippet_b": c.quote_b or "",
            "source_b": by_source[c.source_b_id].url if c.source_b_id in by_source else "",
            "nature": c.nature or "",
        }
        for c in contradictions
    ]

    # Run-scoped and ordered by `sequence`, not by revision: a PLAN review has no
    # `revision_id` at all, so the old single-parent read would silently omit every plan
    # approval from the chain.
    reviews = await approval_chain(db, run_id)
    approval_chain_dicts = []
    for r in reviews:
        action = REVIEW_TO_BUNDLE_ACTION.get((r.gate, r.decision))
        if action is None:  # pragma: no cover — AUDIT_MAP invertibility is pinned by a test
            raise ValueError(f"review {r.id} has no serialised action for {r.gate}/{r.decision}")
        # The serialization layer of the artifact-authorization rule.
        # `verify_bundle` treats `action == "approved"` as report authorization; emitting
        # that string for a plan approval would satisfy the verifier's load-bearing check
        # in a file no database constraint reaches.
        if r.gate == "PLAN" and action == verify_bundle.REPORT_APPROVAL_ACTION:
            raise ValueError(
                f"review {r.id} is a PLAN approval and would serialize as a report approval"
            )
        approval_chain_dicts.append(
            {
                "action": action,
                "feedback": r.feedback,
                "draft_hash": r.reviewed_hash,
                "timestamp": r.created_at.isoformat(),
            }
        )

    return (
        bundle_mod.assemble(
            session_id=str(run.id),
            query=run.question,
            report=revision.report_markdown,
            evidence=evidence_dicts,
            sources=source_dicts,
            contradictions=contradiction_dicts,
            models=run.model_routing or {},
            cost_usd=float(run.cost_usd),
            tokens_input=run.tokens_input,
            tokens_output=run.tokens_output,
            elapsed_seconds=float(run.elapsed_seconds) if run.elapsed_seconds else None,
            research_depth=run.depth,
            approval_chain=approval_chain_dicts,
            trace=await _trace(db, run.id),
            trace_available=True,
            demo=run.demo,
        ),
        None,
    )


async def assemble(db: AsyncSession, run_id) -> bundle_mod.BundleManifest | None:
    """The manifest, or None when the run has nothing assemblable. Never a half bundle."""
    manifest, _ = await assemble_with_reason(db, run_id)
    return manifest


def verify(manifest: bundle_mod.BundleManifest):
    """The shipped standalone verifier, imported rather than reimplemented.

    A private copy of the checks would verify a bundle against this module's own idea of validity,
    which is the one thing this must not do.
    """
    return verify_bundle.verify(manifest)
