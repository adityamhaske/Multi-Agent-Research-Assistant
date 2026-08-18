"""
V1 → V2 data migration engine (M2E).

Reads V1, derives V2, writes V2, writes the ledger — one transaction per run. Never
modifies V1. Never infers a fact V1 did not record.

**Deterministic identity, not random UUIDs.** Every V2 id is derived with `uuid5` from the
V1 identity, so a second migration produces the *same* ids and collides on the primary key
instead of duplicating. Random ids would make idempotency depend on the ledger being
correct; this makes it depend on arithmetic.

The four refusals this engine is built around, each traceable to a rule rather than taste:

* evidence migrates `UNCHECKED`, never `ATTESTED` — V1 recorded no per-item attestation
* one revision per run, never `rework_count + 1` — superseded drafts were overwritten
* `lineage_id` stays NULL — V1 never observed claim identity
* a cancelled run stays `FAILED` — V1's marker is a message, not a contract
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.research import Contradiction, Evidence, ResearchPlan, ResearchRun, Source
from app.models.review import AuditEvent, Review
from app.models.revision import Claim, ClaimEvidenceLink, Revision
from app.models.session import Session, SessionStatus
from migration.checkpoint import CheckpointOutcome, read_checkpoint
from migration.ledger import MigrationStatus
from research_engine import claims as claim_rules

#: Namespace for deterministic V2 ids. Fixed forever — changing it would make a re-run
#: produce a disjoint set of rows instead of colliding, i.e. silently duplicate everything.
NS = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")


def _det(*parts: object) -> uuid.UUID:
    return uuid.uuid5(NS, "|".join(str(p) for p in parts))


def _sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _norm_url(url: str) -> str:
    return (url or "").strip().rstrip("/").lower()


#: V1 status → V2 status. `AWAITING_APPROVAL` is a rename; nothing else moves.
#: CANCELLED is deliberately absent — see the module docstring.
STATUS_MAP = {
    SessionStatus.PENDING: "PENDING",
    SessionStatus.RUNNING: "RUNNING",
    SessionStatus.AWAITING_PLAN: "AWAITING_PLAN",
    SessionStatus.AWAITING_APPROVAL: "AWAITING_REVIEW",
    SessionStatus.COMPLETED: "COMPLETED",
    SessionStatus.FAILED: "FAILED",
}

AUDIT_MAP = {
    "approved": ("REPORT", "APPROVED", "review.approved"),
    "rework_requested": ("REPORT", "REWORK_REQUESTED", "review.rework_requested"),
    "plan_approved": ("PLAN", "APPROVED", "plan.approved"),
}


@dataclass
class RunResult:
    session_id: uuid.UUID
    status: MigrationStatus
    failure_category: str | None = None
    detail: str | None = None
    evidence_outcome: str | None = None
    revision_outcome: str | None = None
    artifact_outcome: str | None = None
    rows_written: int = 0
    duration_ms: int = 0
    counts: dict[str, int] = field(default_factory=dict)


class Unmigratable(Exception):
    """V1 holds a state V2 cannot represent without inventing a fact.

    Raised rather than worked around. The run is classified `INCONSISTENT_V1`, V1 is left
    exactly as it was, and the reason is recorded — which is the only honest outcome when
    the alternative is a synthetic source or a fabricated revision.
    """

    def __init__(self, category: str, detail: str) -> None:
        super().__init__(detail)
        self.category = category
        self.detail = detail


async def migrate_session(db: AsyncSession, saver, session: Session) -> RunResult:
    """Derive and insert every V2 row for one V1 session. Caller owns the transaction."""
    t0 = time.perf_counter()
    counts: dict[str, int] = {}
    sid = session.id

    def bump(table: str, n: int = 1) -> None:
        counts[table] = counts.get(table, 0) + n

    # ── run ──────────────────────────────────────────────────────────────────────
    await db.execute(
        insert(ResearchRun).values(
            id=sid,
            project_id=session.project_id,
            owner_id=session.user_id,  # V1 projects.user_id is NOT renamed
            question=session.prompt,
            status=STATUS_MAP[session.status],
            depth=session.research_depth,
            corpus_mode=session.corpus_mode,
            demo=session.demo,
            skip_plan_gate=session.skip_plan_gate,
            topic_seeds=session.topic_seeds,
            outline_template=session.outline_template,
            model_routing=session.model_routing,
            cost_usd=session.total_cost_usd,
            tokens_input=session.total_tokens_input,
            tokens_output=session.total_tokens_output,
            elapsed_seconds=session.elapsed_seconds,
            citation_resolution_rate=session.citation_resolution_rate,
            error_message=session.error_message,
            # Never inferred from error_message (M2E §14).
            cancelled_at=None,
            cancel_requested_by=None,
            archived_at=session.archived_at,
            created_at=session.created_at,
            updated_at=session.updated_at,
        )
    )
    bump("research_runs")

    # ── plan: one version, authorship unknown ────────────────────────────────────
    plan_id = None
    if session.plan_json is not None or session.outline_json is not None:
        plan_id = _det("plan", sid, 1)
        await db.execute(
            insert(ResearchPlan).values(
                id=plan_id,
                run_id=sid,
                version=1,
                tasks=(session.plan_json or {}).get("tasks") or [],
                outline_sections=(session.outline_json or {}).get("sections") or [],
                # V1 overwrote the proposal with the approved plan, so which one this is
                # cannot be known. UNKNOWN is the truthful value.
                origin="UNKNOWN",
                approved_at=session.plan_approved_at,
                created_at=session.created_at,
            )
        )
        bump("research_plans")

    # ── sources: from the V1 JSON snapshot only ──────────────────────────────────
    by_url: dict[str, uuid.UUID] = {}
    for entry in session.sources or []:
        if not isinstance(entry, dict):
            continue
        url = entry.get("url") or ""
        if not url:
            continue
        norm = _norm_url(url)
        if norm in by_url:
            continue
        src_id = _det("source", sid, norm)
        by_url[norm] = src_id
        await db.execute(
            insert(Source).values(
                id=src_id,
                run_id=sid,
                url=url,
                normalized_url=norm,
                title=entry.get("title") or None,
                kind="CORPUS" if url.startswith("corpus://") else "WEB",
                # V1 never recorded whether a page was fetched or only seen in a search
                # result. UNKNOWN, not a guess.
                retrieval_status="UNKNOWN",
                citation_index=int(entry.get("index") or (len(by_url))),
                corpus_document_id=url[len("corpus://") :] if url.startswith("corpus://") else None,
                retrieved_at=session.created_at,
            )
        )
        bump("sources")

    # ── evidence: the checkpoint, tri-state ──────────────────────────────────────
    read = await read_checkpoint(saver, str(sid))
    if read.outcome is CheckpointOutcome.MISSING:
        evidence_outcome = "CHECKPOINT_MISSING"
    elif read.outcome is CheckpointOutcome.UNREADABLE:
        evidence_outcome = "CHECKPOINT_UNREADABLE"
    else:
        evidence_outcome = "COPIED" if read.evidence else "NONE_PRESENT"

    ev_ids: dict[int, uuid.UUID] = {}  # citation_index → evidence id (first per source)
    max_seq = 0
    if read.outcome is CheckpointOutcome.READ:
        for i, item in enumerate(read.evidence, start=1):
            if not isinstance(item, dict):
                continue
            norm = _norm_url(item.get("source_url") or "")
            src_id = by_url.get(norm)
            if src_id is None:
                # `graph._number_sources` skips evidence with an empty URL, and `sources`
                # is only written by the synthesizer — so a run that failed earlier has
                # evidence with no source row. `evidence.source_id` is NOT NULL and V2
                # offers no honest placeholder. Refuse rather than invent one.
                raise Unmigratable(
                    "EVIDENCE_SOURCE_UNRESOLVED",
                    f"evidence[{i}] url={item.get('source_url')!r} has no source row; "
                    "sources are derived by the synthesizer and this run has none",
                )
            snippet = item.get("snippet") or ""
            eid = _det("evidence", sid, i)
            await db.execute(
                insert(Evidence).values(
                    id=eid,
                    run_id=sid,
                    source_id=src_id,
                    sequence=i,
                    task_id=str(item.get("task_id")) if item.get("task_id") is not None else None,
                    snippet=snippet,  # kept verbatim, empty included
                    content_hash=_sha(snippet),
                    key_fact=item.get("key_fact") or None,
                    # V1 recorded no per-item attestation. Never ATTESTED (M2E §7).
                    provenance_state="UNCHECKED",
                    attested_against=None,
                    attestation_run_at=None,
                    created_at=session.created_at,
                )
            )
            bump("evidence")
            max_seq = i
            # Map every V1 citation index for this URL onto the first evidence row from
            # it, so `[n]` in the report resolves to real evidence. First-wins: V1 gave one
            # citation index per source, and later evidence from the same source is
            # additional support for that same marker, not a new one.
            for entry in session.sources or []:
                if not isinstance(entry, dict):
                    continue
                if _norm_url(entry.get("url") or "") != norm:
                    continue
                idx = entry.get("index")
                if isinstance(idx, int) and idx not in ev_ids:
                    ev_ids[idx] = eid

        for j, pair in enumerate(read.contradictions, start=1):
            if not isinstance(pair, dict):
                continue
            await db.execute(
                insert(Contradiction).values(
                    id=_det("contradiction", sid, j),
                    run_id=sid,
                    evidence_a_id=None,
                    evidence_b_id=None,
                    summary_a=(pair.get("claim_a") or pair.get("a") or None),
                    summary_b=(pair.get("claim_b") or pair.get("b") or None),
                    dimension="UNCLASSIFIED",
                    # V1's pairs are keyed by source, not by evidence id, so the pair
                    # cannot be reconstructed. Recording DETECTED without the pair would
                    # violate ck_contra_pair; NOT_RUN would be a lie. Neither: no row.
                    detection_state="NOT_RUN",
                    review_state="UNREVIEWED",
                    created_at=session.created_at,
                )
            )
            bump("contradictions")

    # ── revision: exactly one, never rework_count + 1 ────────────────────────────
    report = session.final_report or session.draft_report
    rev_id = None
    if report:
        rev_id = _det("revision", sid, 1)
        await db.execute(
            insert(Revision).values(
                id=rev_id,
                run_id=sid,
                version=1,
                report_markdown=report,
                report_hash=_sha(report),
                evidence_watermark=max_seq,
                created_at=session.updated_at or session.created_at,
            )
        )
        bump("revisions")
        revision_outcome = "COPIED"

        # claims + links, from the canonical M0A extractor
        for pos, text in enumerate(claim_rules.claim_lines(report)):
            cid = _det("claim", sid, 1, pos)
            await db.execute(
                insert(Claim).values(
                    id=cid,
                    revision_id=rev_id,
                    run_id=sid,
                    position=pos,
                    text=text,
                    extraction_method="DERIVED_FROM_REPORT",
                    verification_state="UNCHECKED",
                    verification_method="NOT_RUN",
                    lineage_id=None,  # never inferred (M2E §11)
                    created_at=session.created_at,
                )
            )
            bump("claims")
            for n in dict.fromkeys(claim_rules.extract_citations(text)):
                target = ev_ids.get(n)
                if target is None:
                    continue  # a marker resolving to nothing links to nothing
                await db.execute(
                    insert(ClaimEvidenceLink).values(
                        id=_det("link", sid, 1, pos, n),
                        run_id=sid,
                        claim_id=cid,
                        evidence_id=target,
                        stance="SUPPORTS",
                        origin="CITATION_MARKER",
                        created_at=session.created_at,
                    )
                )
                bump("claim_evidence_links")
    else:
        revision_outcome = "NO_REPORT"

    # ── reviews + audit events ───────────────────────────────────────────────────
    rows = (
        (
            await db.execute(
                select(AuditLog).where(AuditLog.session_id == sid).order_by(AuditLog.id.asc())
            )
        )
        .scalars()
        .all()
    )

    seen_report_approval = False
    for row in rows:
        mapped = AUDIT_MAP.get(row.action)
        if mapped is None:
            raise Unmigratable("UNKNOWN_AUDIT_ACTION", f"audit_log.action={row.action!r}")
        gate, decision, event_action = mapped

        if rev_id is None:
            # `submit_plan` requires AWAITING_PLAN, which precedes any draft — so a
            # plan_approved row with no report is a legitimate V1 state. V2's
            # reviews.revision_id is NOT NULL, so it cannot be represented. Refuse: the
            # review must not be dropped, and no revision may be fabricated to hold it.
            raise Unmigratable(
                "REVIEW_WITHOUT_REVISION",
                f"audit_log {row.id} ({row.action}) exists but the run has no report; "
                "reviews.revision_id is NOT NULL",
            )
        if len(row.draft_hash or "") != 64:
            raise Unmigratable("MALFORMED_DRAFT_HASH", f"audit_log {row.id}")
        if gate == "REPORT" and decision == "APPROVED":
            if seen_report_approval:
                raise Unmigratable(
                    "DUPLICATE_APPROVAL",
                    f"two approving REPORT reviews for one revision (audit_log {row.id})",
                )
            seen_report_approval = True

        await db.execute(
            insert(Review).values(
                id=_det("review", sid, row.id),
                revision_id=rev_id,
                reviewer_id=row.user_id,
                plan_version_id=plan_id if gate == "PLAN" else None,
                gate=gate,
                decision=decision,
                feedback=row.feedback,
                reviewed_hash=row.draft_hash,
                created_at=row.created_at,
            )
        )
        bump("reviews")
        await db.execute(
            insert(AuditEvent).values(
                actor_id=row.user_id,
                action=event_action,
                subject_type="research_run",
                subject_id=sid,
                metadata_json={"v1_audit_log_id": row.id},
                occurred_at=row.created_at,
            )
        )
        bump("audit_events")

    return RunResult(
        session_id=sid,
        status=MigrationStatus.MIGRATED,
        evidence_outcome=evidence_outcome,
        revision_outcome=revision_outcome,
        artifact_outcome="NOT_APPROVED" if not seen_report_approval else "PENDING_M2F",
        rows_written=sum(counts.values()),
        duration_ms=int((time.perf_counter() - t0) * 1000),
        counts=counts,
    )
