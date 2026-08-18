"""
Bundle equivalence: does the V2 representation say the same thing V1 said? (M2E §"Bundle
equivalence").

The V1 bundle is assembled from `sessions` + `audit_log` + the LangGraph checkpoint, exactly
as `app/api/v1/research.py::export_bundle_json` does. The V2 bundle is assembled from the
migrated domain tables. Both go through the same `research_engine.bundle.assemble`, so any
difference is a difference in the *data*, not in the format.

**What a match does and does not mean.** `BUNDLE_EQUIVALENT` means one thing only:

    the V1 representation and the V2 representation are the same

It does **not** mean the historical V1 evidence was truthful, that its citations resolved,
that its claims were correct, or that any attestation was valid. Those are properties of the
run; this is a property of the migration. Conflating them is precisely the "false
measurement" failure this repository treats as P0 (AGENTS.md), so the vocabulary is kept
apart: `BUNDLE_EQUIVALENT` is about *representation fidelity*.

**Only two fields are normalised, and both are properties of the act of assembling rather
than of the run:**

* `created_at` — the wall-clock at which `assemble()` was called. Different by construction.
* `bundle_hash` — a digest over every other field including `created_at`, so it cannot
  agree while `created_at` disagrees. Recomputed over the normalised dict on both sides, so
  it still detects any difference in the fields that *are* compared.

Nothing else is normalised. A mismatch anywhere else is reported as a mismatch, named field
by field, and never smoothed away.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_log import AgentLog
from app.models.audit_log import AuditLog
from app.models.research import Contradiction, Evidence, ResearchRun, Source
from app.models.review import Review
from app.models.revision import Revision
from app.models.session import Session, SessionStatus
from migration.checkpoint import CheckpointOutcome, read_checkpoint
from research_engine import bundle as bundle_mod

#: The only fields normalised before comparison. See the module docstring.
NORMALISED_FIELDS = ("created_at", "bundle_hash")

#: Reverse of `engine.AUDIT_MAP`. V1's `action` is recoverable from V2's (gate, decision)
#: because the forward map is injective — verified by `test_audit_map_is_invertible`.
REVIEW_TO_V1_ACTION = {
    ("REPORT", "APPROVED"): "approved",
    ("REPORT", "REWORK_REQUESTED"): "rework_requested",
    ("PLAN", "APPROVED"): "plan_approved",
}


#: Field sets that differ for a **known, named** reason — a V2 column that does not exist,
#: not a migration defect. Keyed by the differing fields with `bundle_hash` removed, since
#: the digest moves with any field and never identifies one.
#:
#: A mismatch whose field set is not in here is `UNCLASSIFIED`, and the dry run fails on it.
#: That is the point: "never silently ignore mismatches" means an unrecognised difference
#: must be louder than a recognised one, not quieter.
KNOWN_LOSSY: dict[frozenset[str], str] = {
    # V1 keys a contradiction by source URL; V2 keys it by evidence id and the migration
    # leaves both NULL, because V1 never recorded which evidence row a side came from.
    frozenset({"contradictions"}): "CONTRADICTION_PAIR_NOT_STORED",
    # V2's `sources` has no snippet columns. The V1 shape is rebuilt by replaying
    # `_number_sources` over the migrated evidence, so a run whose evidence no longer
    # matches the source snapshot V1 recorded cannot round-trip.
    frozenset({"sources"}): "SOURCE_SNIPPETS_NOT_STORED",
    frozenset({"sources", "contradictions"}): "SOURCE_SNIPPETS_AND_CONTRADICTION_PAIR",
}


class BundleVerdict(enum.StrEnum):
    BUNDLE_EQUIVALENT = "BUNDLE_EQUIVALENT"
    BUNDLE_MISMATCH = "BUNDLE_MISMATCH"
    #: One side could not be assembled at all — no report, no migrated run, or a checkpoint
    #: that could not be read. Never silently folded into either of the other two.
    NOT_COMPARABLE = "NOT_COMPARABLE"


@dataclass
class BundleComparison:
    session_id: str
    verdict: BundleVerdict
    reason: str | None = None
    #: Field names that differ, in bundle-manifest order. Empty iff EQUIVALENT.
    differing_fields: list[str] = field(default_factory=list)
    #: `field -> (v1, v2)`, truncated. Diagnosis, never a place to stash a whole report.
    detail: dict[str, tuple[str, str]] = field(default_factory=dict)
    #: For a mismatch: the named V2 limitation that explains it, or `UNCLASSIFIED`.
    limitation: str | None = None


def _clip(value: Any, n: int = 240) -> str:
    text = repr(value)
    return text if len(text) <= n else text[:n] + f"…(+{len(text) - n})"


def _normalise(manifest: bundle_mod.BundleManifest) -> dict:
    """Blank the two assembly-time fields, then recompute the hash over what is left."""
    d = manifest.model_dump()
    d["created_at"] = ""
    d["bundle_hash"] = ""
    d["bundle_hash"] = bundle_mod.compute_bundle_hash(bundle_mod.BundleManifest.model_validate(d))
    return d


# ── V1 side ───────────────────────────────────────────────────────────────────────


async def assemble_v1(
    db: AsyncSession, saver, session: Session
) -> tuple[bundle_mod.BundleManifest | None, str | None]:
    """Rebuild the bundle the V1 server would have exported for this session.

    Mirrors `export_bundle_json` field for field, with one deliberate difference: the
    checkpoint is read through the tri-state reader, so a missing or unreadable snapshot
    yields NOT_COMPARABLE rather than an empty evidence list (M2E §0.1).
    """
    report = session.final_report or session.draft_report
    if not report:
        return None, "V1_NO_REPORT"

    read = await read_checkpoint(saver, str(session.id))
    if read.outcome is CheckpointOutcome.MISSING:
        return None, "V1_CHECKPOINT_MISSING"
    if read.outcome is CheckpointOutcome.UNREADABLE:
        return None, "V1_CHECKPOINT_UNREADABLE"

    audit_logs = (
        (
            await db.execute(
                select(AuditLog)
                .where(AuditLog.session_id == session.id)
                .order_by(AuditLog.id.asc())
            )
        )
        .scalars()
        .all()
    )
    approval_chain = [
        {
            "action": row.action,
            "feedback": row.feedback,
            "draft_hash": row.draft_hash,
            "timestamp": row.created_at.isoformat(),
        }
        for row in audit_logs
    ]

    return (
        bundle_mod.assemble(
            session_id=str(session.id),
            query=session.prompt,
            report=report,
            evidence=read.evidence,
            sources=session.sources or [],
            contradictions=read.contradictions,
            models=session.model_routing or {},
            cost_usd=float(session.total_cost_usd),
            tokens_input=session.total_tokens_input,
            tokens_output=session.total_tokens_output,
            elapsed_seconds=float(session.elapsed_seconds) if session.elapsed_seconds else None,
            research_depth=session.research_depth,
            approval_chain=approval_chain,
            trace=await _trace(db, session.id),
            trace_available=True,
            demo=session.demo,
        ),
        None,
    )


async def _trace(db: AsyncSession, run_id) -> list[dict]:
    """`agent_logs` is not migrated — it is the same table for both sides (M2E §1)."""
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


# ── V2 side ───────────────────────────────────────────────────────────────────────


async def assemble_v2(
    db: AsyncSession, run_id
) -> tuple[bundle_mod.BundleManifest | None, str | None]:
    """Rebuild the same bundle from the migrated V2 domain tables."""
    run = (
        await db.execute(select(ResearchRun).where(ResearchRun.id == run_id))
    ).scalar_one_or_none()
    if run is None:
        return None, "V2_RUN_ABSENT"

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
        return None, "V2_NO_REVISION"

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

    # V1's `sessions.sources` is derived by `graph._number_sources` from the evidence list,
    # and V2's `sources` table does not carry the snippet columns — so the V1 shape is
    # rebuilt here by replaying that same derivation over the migrated evidence. This is
    # reconstruction of a documented derivation, not a normalisation: if the migrated
    # evidence disagrees with what V1 recorded, the rebuilt list differs and the comparison
    # says so.
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
    # V1's pair is keyed by source URL; V2 keys it by evidence id, and the migration leaves
    # both NULL because V1 never recorded which evidence row a side came from. So the URLs
    # are genuinely absent from V2 and are emitted as such — a run with contradictions will
    # report BUNDLE_MISMATCH on this field, which is the truthful outcome and is recorded as
    # a V2 mapping limitation rather than hidden by a normalisation.
    contradiction_dicts = [
        {
            "source_a": None,
            "source_b": None,
            "claim_a": c.summary_a,
            "claim_b": c.summary_b,
        }
        for c in contradictions
    ]

    reviews = (
        (
            await db.execute(
                select(Review)
                .where(Review.revision_id == revision.id)
                .order_by(Review.created_at.asc(), Review.id.asc())
            )
        )
        .scalars()
        .all()
    )
    approval_chain = [
        {
            "action": REVIEW_TO_V1_ACTION.get((r.gate, r.decision), ""),
            "feedback": r.feedback,
            "draft_hash": r.reviewed_hash,
            "timestamp": r.created_at.isoformat(),
        }
        for r in reviews
    ]

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
            approval_chain=approval_chain,
            trace=await _trace(db, run.id),
            trace_available=True,
            demo=run.demo,
        ),
        None,
    )


# ── Comparison ────────────────────────────────────────────────────────────────────


async def compare_run(db: AsyncSession, saver, session: Session) -> BundleComparison:
    """Assemble both sides and compare. Never returns a verdict it did not measure."""
    sid = str(session.id)

    # The V1 route refuses to export a bundle for anything but a COMPLETED session, so a
    # non-COMPLETED run has no V1 bundle to be equivalent to.
    if session.status != SessionStatus.COMPLETED:
        return BundleComparison(sid, BundleVerdict.NOT_COMPARABLE, f"V1_STATUS_{session.status}")

    v1, why = await assemble_v1(db, saver, session)
    if v1 is None:
        return BundleComparison(sid, BundleVerdict.NOT_COMPARABLE, why)

    v2, why = await assemble_v2(db, session.id)
    if v2 is None:
        return BundleComparison(sid, BundleVerdict.NOT_COMPARABLE, why)

    left, right = _normalise(v1), _normalise(v2)
    differing = [k for k in left if left[k] != right[k]]
    if not differing:
        return BundleComparison(sid, BundleVerdict.BUNDLE_EQUIVALENT)

    substantive = frozenset(differing) - {"bundle_hash"}
    return BundleComparison(
        sid,
        BundleVerdict.BUNDLE_MISMATCH,
        reason="FIELDS_DIFFER",
        differing_fields=differing,
        detail={k: (_clip(left[k]), _clip(right[k])) for k in differing if k != "bundle_hash"},
        limitation=KNOWN_LOSSY.get(substantive, "UNCLASSIFIED"),
    )
