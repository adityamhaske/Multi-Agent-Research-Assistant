"""
The research lifecycle — the persistence side of a run, host-free.

The research *engine* is unchanged: `research_engine.graph` plans, executes, criticises and
synthesizes exactly as it does today, and `RunOutcome` is still the plain-data handoff. What
changes is where a host writes that outcome. This module is the destination:

    question → ResearchRun → ResearchPlan → Sources + Evidence → Revision
             → Claims → ClaimEvidenceLinks → Contradictions → Review → Artifact → Bundle

**Host-agnostic on purpose.** No FastAPI, no auth, no Redis, no crypto. The server router and
the desktop sidecar both call these functions, so the lifecycle has one home rather than the
two that this repository keeps rediscovering (AGENTS.md, "two hosts, one contract").

Four rules, and this module is where each becomes behaviour rather than documentation:

* **Retrieved is not cited.** A `Source` gets a `citation_index` only if the synthesizer
  numbered it. Never generated (I6).
* **An item is attested only to what the graph actually verified.** The snippet check in
  `research_engine.graph.verify_evidence_snippets` runs per item and records its verdict on
  the chunk (`attestation_grade`, `snippet_unverified`); `record_evidence` below reads that
  verdict rather than asserting one. An item the check never reached — fake-mode runs, or a
  chunk with no snippet to check — lands `UNCHECKED`, honestly (I…§14).
* **A contradiction is a conflict between two attributed quotations.** `DETECTED` needs both
  source anchors; an evidence anchor is set only on an exact, unique quotation match (I7, I8).
* **Only an APPROVED REPORT review authorizes an artifact**, and the check goes through
  `app.authorization` rather than being re-derived here (I3).

Rework appends. `record_revision` allocates the next `version`, so revision 1 is never
overwritten and `Review.sequence` keeps the decision order that produced it.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import authorization
from app.models.agent_log import AgentLog
from app.models.memory_chunk import MemoryChunk
from app.models.research import Contradiction, Evidence, ResearchPlan, ResearchRun, Source
from app.models.review import AuditEvent, ResearchArtifact, Review
from app.models.revision import Claim, ClaimEvidenceLink, Revision
from app.services import memory
from research_engine import citation_rate
from research_engine import claims as claim_rules
from research_engine.graph import _norm_url

#: Engine `RunOutcome.status` strings → `research_runs.status`.
#: `awaiting_approval` becomes `AWAITING_REVIEW`; nothing else moves, and `CANCELLED` is
#: reachable only through `request_cancel`, never inferred from a message.
OUTCOME_STATUS = {
    "awaiting_plan": "AWAITING_PLAN",
    "awaiting_approval": "AWAITING_REVIEW",
    "completed": "COMPLETED",
    "failed": "FAILED",
}


class LifecycleError(Exception):
    """A transition the domain does not allow. Raised before anything is written."""


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


# ── 1. The run ────────────────────────────────────────────────────────────────────


async def create_run(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID,
    project_id: uuid.UUID,
    question: str,
    depth: str = "balanced",
    corpus_mode: bool = False,
    demo: bool = False,
    skip_plan_gate: bool = True,
    topic_seeds: list | None = None,
    outline_template: str | None = None,
    model_routing: dict | None = None,
) -> ResearchRun:
    """Open a new run. `owner_id` is denormalised so every authorization is single-table."""
    run = ResearchRun(
        id=uuid.uuid4(),
        project_id=project_id,
        owner_id=owner_id,
        question=question,
        status="PENDING",
        depth=depth,
        corpus_mode=corpus_mode,
        demo=demo,
        skip_plan_gate=skip_plan_gate,
        topic_seeds=topic_seeds,
        outline_template=outline_template,
        model_routing=model_routing,
        cost_usd=0,
        tokens_input=0,
        tokens_output=0,
    )
    db.add(run)
    await db.flush()
    return run


async def set_status(db: AsyncSession, run: ResearchRun, status: str) -> None:
    """Move the run's status, refusing the one transition the schema cannot express.

    `ck_run_cancelled` ties `CANCELLED` to `cancelled_at`, so cancellation has its own entry
    point (`request_cancel`) and cannot be reached by a bare status write.

    It also cannot be *left* by one. A cancelled run is terminal by the user's decision, and
    the constraint enforces that from below: any status write on a row with `cancelled_at`
    set raises `IntegrityError` from whichever background task attempted it. Refusing here
    turns that into a named error at the call site instead of a constraint violation three
    layers down — the failure this replaces was a resume dispatched after a cancel writing
    RUNNING and killing its Celery task (issue #54).
    """
    if status == "CANCELLED":
        raise LifecycleError("use request_cancel(); CANCELLED must carry cancelled_at")
    if run.status == "CANCELLED":
        raise LifecycleError(f"run {run.id} was cancelled; it cannot move to {status}")
    run.status = status
    await db.flush()


async def request_cancel(db: AsyncSession, run: ResearchRun, *, by: uuid.UUID) -> None:
    """Durable cancellation — a row, not a TTL'd cache key."""
    run.status = "CANCELLED"
    run.cancelled_at = datetime.now(UTC)
    run.cancel_requested_by = by
    await db.flush()


async def record_failure(db: AsyncSession, run: ResearchRun, error: str | None) -> None:
    """Record that the run failed — unless the user had already stopped it (issue #54).

    A cancelled run keeps its status. `ck_run_cancelled` ties CANCELLED to `cancelled_at`,
    so writing FAILED over it does not merely mis-record: it violates the constraint and
    raises `IntegrityError` from whatever background task was unlucky enough to be holding
    the run. Observed live — cancel a run mid-flight, let its worker hit any error, and the
    error handler died on the constraint instead of recording the failure.

    The guard lives here rather than at the call sites because this is the only function
    that writes FAILED, and the call sites are three and growing (`persist_outcome` twice,
    the corpus-mode guard in `execute_run`, and `tasks._mark_run_failed`). The message is
    still kept: what went wrong is worth knowing even when the run's fate was already
    decided by the user.
    """
    if run.status == "CANCELLED":
        run.error_message = error
        await db.flush()
        return
    run.status = "FAILED"
    run.error_message = error
    await db.flush()


async def record_metrics(
    db: AsyncSession,
    run: ResearchRun,
    *,
    cost_usd: float,
    tokens_input: int,
    tokens_output: int,
    elapsed_seconds: float | None = None,
    citation_resolution_rate: float | None = None,
) -> None:
    """Spend and timings. `citation_resolution_rate` stays NULL when unmeasured — never 0."""
    run.cost_usd = cost_usd
    run.tokens_input = tokens_input
    run.tokens_output = tokens_output
    if elapsed_seconds is not None:
        run.elapsed_seconds = elapsed_seconds
    if citation_resolution_rate is not None:
        run.citation_resolution_rate = citation_resolution_rate
    await db.flush()


# ── 2. The plan ───────────────────────────────────────────────────────────────────


async def record_plan(
    db: AsyncSession,
    run: ResearchRun,
    *,
    tasks: list[dict],
    outline_sections: list,
    origin: str = "MODEL_PROPOSED",
) -> ResearchPlan:
    """Append a plan version. The session pipeline overwrote `plan_json`; this inserts and never updates.

    `origin` is a real value here — a run knows whether the model proposed the
    plan or a human edited it. `UNKNOWN` exists only for rows written before origin was
    recorded, and nothing may write it now — a run that cannot say has not been asked.
    """
    if origin == "UNKNOWN":
        raise LifecycleError("UNKNOWN is for imported plans only; a native run knows")
    version = (
        await db.execute(
            select(func.coalesce(func.max(ResearchPlan.version), 0)).where(
                ResearchPlan.run_id == run.id
            )
        )
    ).scalar_one() + 1
    plan = ResearchPlan(
        id=uuid.uuid4(),
        run_id=run.id,
        version=version,
        tasks=tasks,
        outline_sections=outline_sections,
        origin=origin,
    )
    db.add(plan)
    await db.flush()
    return plan


async def approve_plan(db: AsyncSession, plan: ResearchPlan) -> None:
    """Stamp the plan approved. `uq_plan_approved` allows one per run."""
    plan.approved_at = datetime.now(UTC)
    await db.flush()


# ── 3. Sources and evidence ───────────────────────────────────────────────────────


@dataclass
class EvidenceWrite:
    """What was persisted, and enough of the index to link claims and contradictions."""

    sources_by_url: dict[str, uuid.UUID]
    #: citation_index → the first evidence row from that source. `[n]` resolves through this.
    evidence_by_index: dict[int, uuid.UUID]
    #: (source_id, quoted text) → every evidence row carrying it. A list, because a
    #: contradiction may only refine to a UNIQUE match.
    evidence_by_quote: dict[tuple[uuid.UUID, str], list[uuid.UUID]]
    watermark: int
    source_count: int
    evidence_count: int


async def record_evidence(
    db: AsyncSession,
    run: ResearchRun,
    *,
    evidence: list[dict],
    numbered_sources: list[dict] | None = None,
) -> EvidenceWrite:
    """Persist the executor's evidence and the sources it names.

    `numbered_sources` is the synthesizer's `_number_sources` output when synthesis has
    run. A source present in evidence but absent from that list is **retrieved but not
    cited**, and gets `citation_index = NULL` — the distinction S3 exists to hold. Evidence
    with an empty `source_url` has no identity and is refused rather than given one.
    """
    index_by_url: dict[str, int] = {}
    title_by_url: dict[str, str] = {}
    for entry in numbered_sources or []:
        if not isinstance(entry, dict) or not entry.get("url"):
            continue
        norm = _norm_url(entry["url"])
        if isinstance(entry.get("index"), int):
            index_by_url[norm] = entry["index"]
        if entry.get("title"):
            title_by_url[norm] = entry["title"]

    sources_by_url: dict[str, uuid.UUID] = {}
    evidence_by_index: dict[int, uuid.UUID] = {}
    evidence_by_quote: dict[tuple[uuid.UUID, str], list[uuid.UUID]] = {}
    watermark = 0

    base = (
        await db.execute(
            select(func.coalesce(func.max(Evidence.sequence), 0)).where(Evidence.run_id == run.id)
        )
    ).scalar_one()

    for offset, item in enumerate(evidence, start=1):
        if not isinstance(item, dict):
            continue
        url = (item.get("source_url") or "").strip()
        if not url:
            raise LifecycleError(
                f"evidence[{offset}] has no source_url; a Source cannot be invented for it"
            )
        norm = _norm_url(url)
        source_id = sources_by_url.get(norm)
        if source_id is None:
            source_id = (
                await db.execute(
                    select(Source.id).where(Source.run_id == run.id, Source.normalized_url == norm)
                )
            ).scalar_one_or_none()
        if source_id is None:
            source_id = uuid.uuid4()
            db.add(
                Source(
                    id=source_id,
                    run_id=run.id,
                    url=url,
                    normalized_url=norm,
                    title=title_by_url.get(norm) or item.get("source_title") or None,
                    kind="CORPUS" if url.startswith("corpus://") else "WEB",
                    # The executor records whether it fetched a body or quoted a
                    # search result, so this is observed rather than assumed.
                    retrieval_status=(
                        "CORPUS_DOCUMENT"
                        if url.startswith("corpus://")
                        else item.get("retrieval_status") or "FETCHED"
                    ),
                    citation_index=index_by_url.get(norm),
                    corpus_document_id=(
                        url[len("corpus://") :] if url.startswith("corpus://") else None
                    ),
                    retrieved_at=datetime.now(UTC),
                )
            )
            await db.flush()
        sources_by_url[norm] = source_id

        snippet = item.get("snippet") or ""
        sequence = base + offset

        # The graph's per-item verdict, read rather than re-derived — see
        # `verify_evidence_snippets` for what sets each of these on the chunk dict.
        # `snippet_unverified` means the check ran and blanked a fabricated quotation;
        # `attestation_grade` means it ran and the snippet matched what a tool actually
        # returned (as `FETCHED_BODY` or `SEARCH_SNIPPET` — `read_webpage` handles a
        # `corpus://` URL the same as any other fetch). Neither present means the check
        # never reached this item (fake mode, or nothing to check), which is exactly what
        # UNCHECKED is for — a corpus item is not exempt from that absence.
        grade = item.get("attestation_grade")
        if url.startswith("corpus://") and grade:
            grade = "CORPUS_DOCUMENT"

        if item.get("snippet_unverified"):
            provenance_state, attested_against, attestation_run_at = (
                "UNATTESTED",
                None,
                datetime.now(UTC),
            )
        elif grade:
            provenance_state, attested_against, attestation_run_at = (
                "ATTESTED",
                grade,
                datetime.now(UTC),
            )
        else:
            provenance_state, attested_against, attestation_run_at = "UNCHECKED", None, None

        eid = uuid.uuid4()
        db.add(
            Evidence(
                id=eid,
                run_id=run.id,
                source_id=source_id,
                sequence=sequence,
                task_id=str(item["task_id"]) if item.get("task_id") is not None else None,
                snippet=snippet,
                content_hash=content_hash(snippet),
                key_fact=item.get("key_fact") or None,
                provenance_state=provenance_state,
                attested_against=attested_against,
                attestation_run_at=attestation_run_at,
            )
        )
        watermark = sequence
        idx = index_by_url.get(norm)
        if idx is not None and idx not in evidence_by_index:
            evidence_by_index[idx] = eid
        evidence_by_quote.setdefault((source_id, snippet.strip()[:500]), []).append(eid)

    await db.flush()
    return EvidenceWrite(
        sources_by_url=sources_by_url,
        evidence_by_index=evidence_by_index,
        evidence_by_quote=evidence_by_quote,
        watermark=watermark,
        source_count=len(sources_by_url),
        evidence_count=len([e for e in evidence if isinstance(e, dict)]),
    )


# ── 4–6. Revision, claims, links ──────────────────────────────────────────────────


@dataclass
class RevisionWrite:
    revision: Revision
    claim_count: int
    link_count: int


async def record_revision(
    db: AsyncSession,
    run: ResearchRun,
    *,
    report_markdown: str,
    evidence_index: EvidenceWrite | None = None,
) -> RevisionWrite:
    """Append the next immutable revision, with its claims and their evidence links.

    Rework calls this again: `version` is allocated from what already exists, so revision 1
    survives untouched. `evidence_watermark` records the last evidence sequence visible at
    synthesis — a threshold, not a count, so gaps do not affect it.
    """
    if not report_markdown:
        raise LifecycleError("a revision must carry the report it is a version of")

    version = (
        await db.execute(
            select(func.coalesce(func.max(Revision.version), 0)).where(Revision.run_id == run.id)
        )
    ).scalar_one() + 1
    watermark = (
        evidence_index.watermark
        if evidence_index is not None
        else (
            await db.execute(
                select(func.coalesce(func.max(Evidence.sequence), 0)).where(
                    Evidence.run_id == run.id
                )
            )
        ).scalar_one()
    )
    revision = Revision(
        id=uuid.uuid4(),
        run_id=run.id,
        version=version,
        report_markdown=report_markdown,
        report_hash=content_hash(report_markdown),
        evidence_watermark=watermark,
    )
    db.add(revision)
    await db.flush()

    by_index = evidence_index.evidence_by_index if evidence_index else {}
    if not by_index:
        by_index = await _evidence_by_citation_index(db, run.id)

    claim_count = link_count = 0
    for position, text in enumerate(claim_rules.claim_lines(report_markdown)):
        claim = Claim(
            id=uuid.uuid4(),
            revision_id=revision.id,
            run_id=run.id,
            position=position,
            text=text,
            # The synthesizer emits prose, not structured claims, so this is what the
            # extraction honestly is. MODEL_STRUCTURED arrives with a structured emitter.
            extraction_method="DERIVED_FROM_REPORT",
            verification_state="UNCHECKED",
            verification_method="NOT_RUN",
            # Never inferred. Nothing observed that a sentence in this revision IS the
            # assertion from the last one, and matching by text would manufacture it.
            lineage_id=None,
        )
        db.add(claim)
        claim_count += 1
        for marker in dict.fromkeys(claim_rules.extract_citations(text)):
            target = by_index.get(marker)
            if target is None:
                continue  # a marker resolving to nothing links to nothing
            db.add(
                ClaimEvidenceLink(
                    id=uuid.uuid4(),
                    run_id=run.id,
                    claim_id=claim.id,
                    evidence_id=target,
                    stance="SUPPORTS",
                    origin="CITATION_MARKER",
                )
            )
            link_count += 1
    await db.flush()
    return RevisionWrite(revision=revision, claim_count=claim_count, link_count=link_count)


async def _evidence_by_citation_index(db: AsyncSession, run_id) -> dict[int, uuid.UUID]:
    """citation_index → first evidence row, rebuilt from the database.

    Used when a revision is written in a later transaction than its evidence (rework), so
    the in-memory index from `record_evidence` is gone. Uncited sources are excluded by the
    `IS NOT NULL` filter, which is the whole point of the nullable index.
    """
    rows = (
        await db.execute(
            select(Source.citation_index, Evidence.id)
            .join(Evidence, Evidence.source_id == Source.id)
            .where(Source.run_id == run_id, Source.citation_index.isnot(None))
            .order_by(Evidence.sequence.asc(), Evidence.id.asc())
        )
    ).all()
    out: dict[int, uuid.UUID] = {}
    for index, evidence_id in rows:
        out.setdefault(index, evidence_id)
    return out


# ── 7. Contradictions ─────────────────────────────────────────────────────────────


async def record_contradictions(
    db: AsyncSession,
    run: ResearchRun,
    *,
    pairs: list[dict],
    evidence_index: EvidenceWrite | None = None,
    detector_ran: bool = True,
) -> int:
    """Persist the detector's pairs as conflicts between attributed quotations.

    `detector_ran=False` records that fact instead of silently writing nothing: a detector
    that was unavailable and a run with no conflicts are different findings, and
    `detection_state` is where that difference lives.
    """
    if not detector_ran:
        db.add(
            Contradiction(
                id=uuid.uuid4(),
                run_id=run.id,
                detection_state="DETECTOR_UNAVAILABLE",
                review_state="UNREVIEWED",
            )
        )
        await db.flush()
        return 1

    by_url = dict(evidence_index.sources_by_url) if evidence_index else {}
    by_quote = dict(evidence_index.evidence_by_quote) if evidence_index else {}
    if not by_url:
        by_url = {
            row.normalized_url: row.id
            for row in (await db.execute(select(Source).where(Source.run_id == run.id))).scalars()
        }

    written = 0
    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        src_a = by_url.get(_norm_url(pair.get("source_a") or ""))
        src_b = by_url.get(_norm_url(pair.get("source_b") or ""))
        quote_a = pair.get("snippet_a") or None
        quote_b = pair.get("snippet_b") or None

        def refine(source_id, quote):
            """The evidence row carrying this quotation — only if there is exactly one."""
            if source_id is None or not quote:
                return None
            hits = by_quote.get((source_id, quote.strip()[:500]), [])
            return hits[0] if len(hits) == 1 else None

        ev_a, ev_b = refine(src_a, quote_a), refine(src_b, quote_b)
        if ev_a is None or ev_b is None:
            ev_a = ev_b = None  # ck_contra_refine: half a resolved pair is not a pair
        detected = src_a is not None and src_b is not None and src_a != src_b

        db.add(
            Contradiction(
                id=uuid.uuid4(),
                run_id=run.id,
                source_a_id=src_a if detected else None,
                source_b_id=src_b if detected else None,
                evidence_a_id=ev_a if detected else None,
                evidence_b_id=ev_b if detected else None,
                quote_a=quote_a,
                quote_b=quote_b,
                summary_a=pair.get("claim_a") or None,
                summary_b=pair.get("claim_b") or None,
                nature=pair.get("nature") or None,
                # The detector assigns no dimension, and neither does a run yet.
                dimension="UNCLASSIFIED",
                detection_state="DETECTED" if detected else "NOT_RUN",
                review_state="UNREVIEWED",
            )
        )
        written += 1
    await db.flush()
    return written


# ── 8. Reviews ────────────────────────────────────────────────────────────────────


async def _next_sequence(db: AsyncSession, run_id) -> int:
    return (
        await db.execute(
            select(func.coalesce(func.max(Review.sequence), 0)).where(Review.run_id == run_id)
        )
    ).scalar_one() + 1


async def record_plan_review(
    db: AsyncSession,
    run: ResearchRun,
    plan: ResearchPlan,
    *,
    reviewer_id: uuid.UUID,
    decision: str = "APPROVED",
    feedback: str | None = None,
) -> Review:
    """A decision about a plan version. `revision_id` is NULL, and it authorizes nothing."""
    review = Review(
        id=uuid.uuid4(),
        run_id=run.id,
        sequence=await _next_sequence(db, run.id),
        revision_id=None,
        plan_version_id=plan.id,
        reviewer_id=reviewer_id,
        gate="PLAN",
        decision=decision,
        feedback=feedback,
        # The plan's canonical serialisation. Opaque on the session path, computed here — but still not
        # checked by the bundle verifier, which only binds report approvals.
        reviewed_hash=content_hash(f"{plan.version}|{plan.tasks}|{plan.outline_sections}"),
    )
    db.add(review)
    await db.flush()
    if decision == "APPROVED":
        await approve_plan(db, plan)
    await _audit(
        db, run, reviewer_id, "plan.approved" if decision == "APPROVED" else "plan.rejected"
    )
    return review


async def record_report_review(
    db: AsyncSession,
    run: ResearchRun,
    revision: Revision,
    *,
    reviewer_id: uuid.UUID,
    decision: str,
    feedback: str | None = None,
) -> Review:
    """A decision about a revision. The hash binds to the exact bytes reviewed."""
    if decision not in ("APPROVED", "REWORK_REQUESTED", "REJECTED"):
        raise LifecycleError(f"unknown report decision {decision!r}")
    review = Review(
        id=uuid.uuid4(),
        run_id=run.id,
        sequence=await _next_sequence(db, run.id),
        revision_id=revision.id,
        plan_version_id=None,
        reviewer_id=reviewer_id,
        gate="REPORT",
        decision=decision,
        feedback=feedback,
        # `revisions.report_markdown` is immutable, which is what makes this a permanent
        # property rather than one that survives until the next rework.
        reviewed_hash=revision.report_hash,
    )
    db.add(review)
    await db.flush()
    await _audit(
        db,
        run,
        reviewer_id,
        "review.approved" if decision == "APPROVED" else "review.rework_requested",
    )
    return review


async def _audit(db: AsyncSession, run: ResearchRun, actor_id, action: str) -> None:
    await db.execute(
        insert(AuditEvent).values(
            actor_id=actor_id,
            action=action,
            subject_type="research_run",
            subject_id=run.id,
            metadata_json={"native": True},
        )
    )


async def measure_citation_resolution(
    db: AsyncSession, run: ResearchRun, revision: Revision
) -> float | None:
    """How much of the approved report's citation apparatus resolves. NULL when unmeasured.

    Measured here because *here* is when the report becomes final. The engine measures it
    on its own `completed` outcome, and a run never reaches one: approving at the report
    gate finalizes the run in the domain rather than resuming the graph, so nothing was
    ever computing this — `citation_resolution_rate` was NULL on every run the product
    produced, while History offered a filter on it and the run card displayed it.

    The rule itself is not restated: `research_engine.citation_rate` is the one definition
    the benchmark, the eval judge and this all read, so the number a user sees and the
    number a published measurement quotes cannot drift.

    NULL survives as NULL. A report that cites nothing has nothing to resolve, which is a
    different finding from a report whose every marker is broken — the distinction this
    product exists to keep.
    """
    numbered = (
        (
            await db.execute(
                select(Source).where(Source.run_id == run.id, Source.citation_index.is_not(None))
            )
        )
        .scalars()
        .all()
    )
    rate = citation_rate.resolution_rate(
        revision.report_markdown, [{"index": s.citation_index} for s in numbered]
    )
    if rate is not None:
        run.citation_resolution_rate = rate
        await db.flush()
    return rate


# ── 9. Artifact ───────────────────────────────────────────────────────────────────


async def create_artifact(db: AsyncSession, run: ResearchRun) -> ResearchArtifact:
    """Freeze the approved record. Only an APPROVED REPORT review gets here.

    The authorization decision is `app.authorization`'s, not this module's: one accessor,
    so a second copy cannot drift. The payload is a frozen bundle rather than a set of
    joins, so reading it never touches live tables.
    """
    review = await authorization.approving_report_review(db, run.id)
    if review is None:
        raise LifecycleError(
            "no APPROVED REPORT review for this run — a plan approval or a rework request "
            "does not authorize an artifact"
        )
    values = authorization.artifact_authorization_values(review)

    from app import run_bundle

    manifest = await run_bundle.assemble(db, run.id)
    if manifest is None:
        raise LifecycleError("the run has no assemblable bundle; refusing to freeze nothing")
    if manifest.report_hash != review.reviewed_hash:
        # The artifact must bind to the bytes the human approved. A mismatch means the
        # bundle was assembled from a different revision than the one reviewed.
        raise LifecycleError(
            f"report_hash {manifest.report_hash[:12]}… does not match the approved "
            f"{review.reviewed_hash[:12]}…"
        )

    artifact = ResearchArtifact(
        id=uuid.uuid4(),
        owner_id=run.owner_id,
        run_id=run.id,
        project_id=run.project_id,
        revision_id=review.revision_id,
        format_version=manifest.bundle_version,
        payload=manifest.model_dump(),
        artifact_hash=manifest.bundle_hash,
        demo=run.demo,
        **values,
    )
    db.add(artifact)
    await db.flush()
    await _audit(db, run, review.reviewer_id, "artifact.created")
    return artifact


# ── 10. Archive, Restore & Delete ──────────────────────────────────────────────────


async def archive_run(db: AsyncSession, run: ResearchRun) -> ResearchRun:
    """Mark a run archived. Idempotent."""
    if run.archived_at is None:
        run.archived_at = datetime.now(UTC)
        await db.flush()
    return run


async def unarchive_run(db: AsyncSession, run: ResearchRun) -> ResearchRun:
    """Restore an archived run to active history. Idempotent."""
    if run.archived_at is not None:
        run.archived_at = None
        await db.flush()
    return run


async def delete_run(db: AsyncSession, run: ResearchRun) -> None:
    """Permanently delete a run and all associated relational records.

    Refuses active / non-terminal runs (PENDING, RUNNING, AWAITING_PLAN, AWAITING_REVIEW)
    with LifecycleError. Reviews and artifacts are deleted in the same transaction; the two
    polymorphic tables — agent logs and project-memory chunks — carry no foreign key and so
    are deleted explicitly; and the run itself is deleted, cascading its plans, sources,
    evidence, revisions, claims, annotations, links, and contradictions.
    """
    if run.status in ("PENDING", "RUNNING", "AWAITING_PLAN", "AWAITING_REVIEW"):
        raise LifecycleError(
            f"This run is still active ({run.status}). Cancel it or wait for it to finish before deleting."
        )

    # 1. Delete polymorphic AgentLogs
    await db.execute(delete(AgentLog).where(AgentLog.session_id == run.id))

    # 1b. And its project-memory chunks, which are polymorphic for the same reason and so
    # carry no cascade either. A deleted run whose text stays retrievable would let project
    # chat quote a report that no longer exists. Guarded because this function runs on both
    # hosts and the desktop one has no memory table to delete from.
    if memory.is_available(db):
        await db.execute(delete(MemoryChunk).where(MemoryChunk.source_report_id == run.id))

    # 2. Delete ResearchArtifact for this run
    await db.execute(delete(ResearchArtifact).where(ResearchArtifact.run_id == run.id))

    # 3. Delete Review rows for this run (RESTRICT foreign key)
    await db.execute(delete(Review).where(Review.run_id == run.id))

    # 4. Delete the run (cascades plans, sources, evidence, revisions, claims, annotations, links, contradictions)
    await db.delete(run)
    await db.flush()
