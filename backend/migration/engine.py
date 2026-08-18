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
    # (source_id, quoted text) → every evidence row carrying it. A list, not a single id:
    # the refinement is only allowed when the match is UNIQUE, and that cannot be known
    # until every row is in (M2F Amendment §7.4).
    by_quote: dict[tuple[uuid.UUID, str], list[uuid.UUID]] = {}
    max_seq = 0
    if read.outcome is CheckpointOutcome.READ:
        for i, item in enumerate(read.evidence, start=1):
            if not isinstance(item, dict):
                continue
            raw_url = item.get("source_url") or ""
            norm = _norm_url(raw_url)
            src_id = by_url.get(norm)
            if src_id is None:
                if not raw_url:
                    # No identity exists anywhere in V1: `_number_sources` skips it,
                    # `group_snippets_by_source` skips it, and `agent_logs` carries counts
                    # rather than evidence. A `Source` here would be an invention, so the
                    # run is refused (M2F Amendment §6.3).
                    raise Unmigratable(
                        "EVIDENCE_SOURCE_UNRESOLVED",
                        f"evidence[{i}] has an empty source_url; no V1 location records "
                        "an identity for it",
                    )
                # Recovery, not synthesis. `EvidenceChunk.source_url` is a REQUIRED field
                # written by the executor — a V1 fact in a different table from the one the
                # synthesizer writes. `citation_index` stays NULL because the number is
                # assigned by the synthesizer, which never ran for this run: recording that
                # the source was retrieved but never cited is truthful, generating an index
                # would not be (M2F Amendment §6.2).
                #
                # Keyed identically to a snapshot source, so a URL present in both collapses
                # to one row by construction rather than duplicating.
                src_id = _det("source", sid, norm)
                by_url[norm] = src_id
                await db.execute(
                    insert(Source).values(
                        id=src_id,
                        run_id=sid,
                        url=raw_url,
                        normalized_url=norm,
                        title=item.get("source_title") or None,
                        kind="CORPUS" if raw_url.startswith("corpus://") else "WEB",
                        retrieval_status="UNKNOWN",
                        citation_index=None,
                        corpus_document_id=(
                            raw_url[len("corpus://") :] if raw_url.startswith("corpus://") else None
                        ),
                        retrieved_at=session.created_at,
                    )
                )
                bump("sources")
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
            # The detector saw `snippet.strip()[:MAX_SNIPPET_CHARS]`; matching on the same
            # form is replaying V1's own derivation, not normalising the data.
            by_quote.setdefault((src_id, snippet.strip()[:500]), []).append(eid)
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
            # A conflict between two ATTRIBUTED QUOTATIONS. The source anchors are what V1
            # guarantees — `validate_pairs` drops any pair whose URL was not in the
            # detector's input — and the evidence anchors are a refinement that may not
            # resolve (M2F Amendment §7).
            src_a = by_url.get(_norm_url(pair.get("source_a") or ""))
            src_b = by_url.get(_norm_url(pair.get("source_b") or ""))
            quote_a = pair.get("snippet_a") or None
            quote_b = pair.get("snippet_b") or None

            def _refine(source_id, quote):
                """The evidence row carrying this quotation — only if there is exactly one.

                No fallback to "the first evidence row from that source": V1 recorded a
                quotation, not a reference, and picking a row would assert a link the
                detector never made.
                """
                if source_id is None or not quote:
                    return None
                hits = by_quote.get((source_id, quote.strip()[:500]), [])
                return hits[0] if len(hits) == 1 else None

            ev_a = _refine(src_a, quote_a)
            ev_b = _refine(src_b, quote_b)
            # ck_contra_refine: half a resolved pair is not a pair.
            if ev_a is None or ev_b is None:
                ev_a = ev_b = None
            # A pair naming the same source twice is dropped by `validate_pairs`, so this
            # only fires on data that bypassed it.
            detected = src_a is not None and src_b is not None and src_a != src_b

            await db.execute(
                insert(Contradiction).values(
                    id=_det("contradiction", sid, j),
                    run_id=sid,
                    source_a_id=src_a if detected else None,
                    source_b_id=src_b if detected else None,
                    evidence_a_id=ev_a if detected else None,
                    evidence_b_id=ev_b if detected else None,
                    quote_a=quote_a,
                    quote_b=quote_b,
                    summary_a=(pair.get("claim_a") or pair.get("a") or None),
                    summary_b=(pair.get("claim_b") or pair.get("b") or None),
                    nature=pair.get("nature") or None,
                    dimension="UNCLASSIFIED",
                    # DETECTED at the granularity V1 worked in. Until M2F this had to be
                    # NOT_RUN — a lie about a detector that had run — because the CHECK
                    # demanded evidence references V1 never recorded.
                    detection_state="DETECTED" if detected else "NOT_RUN",
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
    # `audit_log.id` is BIGSERIAL and monotonic, and the rows above are ordered by it, so
    # the enumeration IS V1's decision order — a transformation of a V1 fact, not a
    # generated ordering. It is also the only place that order still exists (M2F
    # Amendment §8.3).
    for position, row in enumerate(rows, start=1):
        mapped = AUDIT_MAP.get(row.action)
        if mapped is None:
            raise Unmigratable("UNKNOWN_AUDIT_ACTION", f"audit_log.action={row.action!r}")
        gate, decision, event_action = mapped

        if gate == "PLAN":
            # A plan review targets the PLAN version, and no revision. `submit_plan` runs
            # at AWAITING_PLAN, before any draft exists, so this is normal V1 behaviour and
            # is now representable — but only against a plan that actually exists.
            if plan_id is None:
                raise Unmigratable(
                    "PLAN_REVIEW_WITHOUT_PLAN",
                    f"audit_log {row.id} approves a plan, but the run has neither "
                    "plan_json nor outline_json to point plan_version_id at",
                )
        elif rev_id is None:
            # A REPORT review with no report is not merely unrepresentable, it is
            # incoherent: the V1 gate that writes these rows requires a draft to exist.
            # Relaxing a constraint would not make it truthful.
            raise Unmigratable(
                "REVIEW_WITHOUT_REVISION",
                f"audit_log {row.id} ({row.action}) is a report decision, but the run has "
                "no report",
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
                run_id=sid,
                sequence=position,
                revision_id=rev_id if gate == "REPORT" else None,
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
        # The migration does not create artifacts — nothing in the approved model asks it
        # to, and an artifact is a frozen snapshot rather than a migrated fact. What it
        # records is whether one *could* be authorized, using the single accessor that
        # encodes the rule (`authorization.approving_report_review`).
        artifact_outcome="AUTHORIZED" if seen_report_approval else "NOT_APPROVED",
        rows_written=sum(counts.values()),
        duration_ms=int((time.perf_counter() - t0) * 1000),
        counts=counts,
    )
