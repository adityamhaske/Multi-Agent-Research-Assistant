"""
The M2E-2 disposable dry run: seed a representative V1 corpus, migrate it, measure the V2
write path, and check every invariant the migration claims.

**It cannot run against production, and the guard is not a flag.** The dry run *seeds* its
own V1 corpus, so it refuses any target whose `sessions` table is not empty. Production has
rows; a mistyped DSN therefore fails closed rather than writing into live data. On top of
that the target is explicit (`--database-url`, never `DATABASE_URL`) and must be confirmed
by name.

**What it measures.** M2C.5 measured the checkpoint *read* path and found concurrency flat
on throughput and 14× worse at p99. It did not measure V2 *writes*, which is what this adds:
rows inserted per table, wall-clock, per-run p50/p95/p99, rows/sec, peak heap, and the
per-run transaction duration — against the real M2D schema on whichever dialect the DSN
names.

The checkpoint saver is a **real LangGraph `AsyncSqliteSaver`**, not a stub. A dry run whose
checkpoint reads were faked would measure the migration against a replacement for the thing
being migrated, which is the "test that stubs the mechanism under test" failure AGENTS.md
warns about; here it would also silently remove the read cost from the timings.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import sys
import tempfile
import time
import tracemalloc
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, insert, inspect, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.agent_log import AgentLog
from app.models.audit_log import AuditLog
from app.models.project import Project
from app.models.research import Contradiction, Evidence, ResearchPlan, ResearchRun, Source
from app.models.review import AuditEvent, ResearchArtifact, Review
from app.models.revision import Claim, ClaimEvidenceLink, Revision
from app.models.session import Session, SessionStatus
from app.models.user import User
from migration import provenance
from migration.bundle_equivalence import BundleVerdict, validate_run
from migration.checkpoint import read_checkpoint
from migration.cli import Refused, check_target, database_name, describe
from migration.ledger import TERMINAL, MigrationLedger
from migration.runner import migrate_all
from research_engine.graph import _number_sources

COUNTED_TABLES = {
    "research_runs": ResearchRun,
    "research_plans": ResearchPlan,
    "sources": Source,
    "evidence": Evidence,
    "contradictions": Contradiction,
    "revisions": Revision,
    "claims": Claim,
    "claim_evidence_links": ClaimEvidenceLink,
    "reviews": Review,
    "audit_events": AuditEvent,
}


def _hash(text: str) -> str:
    """The same digest `bundle.report_hash` uses, so an approval can match a report."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── The corpus ────────────────────────────────────────────────────────────────────
#
# Shapes, not random noise. Each entry is a V1 state that the audit found actually occurs,
# and the mix is weighted so the common case dominates the timings the way it would in
# production. `SHAPES` is the list M2E-3 reports coverage against.


@dataclass
class Shape:
    name: str
    weight: int
    #: What the migration is expected to conclude. Asserted, not assumed.
    expect: str


SHAPES = [
    Shape("complete", 40, "MIGRATED"),
    Shape("complete_large", 8, "MIGRATED"),
    Shape("reworked", 10, "MIGRATED"),
    Shape("demo", 4, "MIGRATED"),
    Shape("with_contradictions", 6, "MIGRATED"),
    Shape("empty_checkpoint", 8, "EMPTY"),
    Shape("missing_checkpoint", 6, "CHECKPOINT_MISSING"),
    Shape("unreadable_checkpoint", 2, "READ_FAILURE"),
    Shape("no_report", 6, "NO_REPORT"),
    Shape("cancelled_as_failed", 4, "MIGRATED"),
    # The synthesizer never ran, so `sessions.sources` is empty — but the executor still
    # recorded where each snippet came from, so the sources are RECOVERABLE (M2F/F3).
    Shape("source_recovered_from_evidence", 4, "NO_REPORT"),
    # No URL anywhere in V1: the one source case that stays non-migratable.
    Shape("evidence_without_url", 2, "INCONSISTENT_V1"),
    # A plan approval before any draft — normal V1, and representable since M2F/F2.
    Shape("plan_approved_no_report", 2, "NO_REPORT"),
    # ...but only against a plan that exists.
    Shape("plan_approved_no_plan", 2, "INCONSISTENT_V1"),
]


def _report(n_markers: int) -> str:
    body = " ".join(
        f"Finding number {i} is supported by the retrieved material [{i}]."
        for i in range(1, n_markers + 1)
    )
    return f"# Findings\n\n{body}\n\n## Sources\n\n" + "\n".join(
        f"{i}. https://example.invalid/doc-{i}" for i in range(1, n_markers + 1)
    )


def _evidence(n: int, *, blank_one: bool = True) -> list[dict]:
    out = []
    for i in range(1, n + 1):
        snippet = "" if (blank_one and i == 2) else f"Verbatim passage number {i} from the source."
        out.append(
            {
                "task_id": i,
                "source_url": f"https://example.invalid/doc-{i}",
                "source_title": f"Document {i}",
                "snippet": snippet,
                "key_fact": f"fact {i}",
            }
        )
    return out


def build_shape(shape: str, index: int) -> dict:
    """One V1 session's worth of data, as plain dicts. No database, no ORM."""
    n = 12 if shape == "complete_large" else 3
    evidence = _evidence(n)
    sources, _ = _number_sources(evidence)
    report = _report(n)
    base = {
        "status": SessionStatus.COMPLETED,
        "report": report,
        "sources": sources,
        "evidence": evidence,
        "contradictions": [],
        "checkpoint": "present",
        # Real digests, not placeholders. M2E-2 used `"a"*64` and every bundle in the
        # corpus therefore failed `verify_bundle`'s approval_chain check — equivalence was
        # measured on bundles that could never have verified, which is exactly the
        # collapse the three gates exist to separate (M2F Amendment §9.4).
        "audits": [
            ("plan_approved", _hash(f"plan for run {index}")),
            ("approved", _hash(report or "")),
        ],
        "rework": 0,
        "demo": False,
        "error": None,
        "plan": [{"id": i, "query": f"q{i}", "rationale": "r"} for i in range(1, 4)],
    }

    if shape == "reworked":
        # The rework was requested against an earlier draft, so its hash must NOT be the
        # report's — only the approval binds to the report that shipped.
        base["audits"] = [
            ("rework_requested", _hash(f"superseded draft for run {index}")),
            ("approved", _hash(report)),
        ]
        base["rework"] = 2
    elif shape == "demo":
        base["demo"] = True
    elif shape == "with_contradictions":
        # All seven fields `validate_pairs` emits. The quotations are the exact evidence
        # snippets, so the evidence refinement resolves uniquely (M2F Amendment §7.4).
        base["contradictions"] = [
            {
                "claim_a": "the metric rose",
                "snippet_a": evidence[0]["snippet"],
                "source_a": "https://example.invalid/doc-1",
                "claim_b": "the metric fell",
                "snippet_b": evidence[2]["snippet"],
                "source_b": "https://example.invalid/doc-3",
                "nature": "the two figures cannot both describe the same benchmark",
            }
        ]
    elif shape == "empty_checkpoint":
        base["evidence"] = []
    elif shape == "missing_checkpoint":
        base["checkpoint"] = "absent"
    elif shape == "unreadable_checkpoint":
        base["checkpoint"] = "corrupt"
    elif shape == "no_report":
        base.update(status=SessionStatus.FAILED, report=None, audits=[])
    elif shape == "cancelled_as_failed":
        # V1 records a user cancellation as FAILED with a message. Never inferred (M2E §0.2).
        base.update(status=SessionStatus.FAILED, error="Research stopped by user.")
    elif shape == "source_recovered_from_evidence":
        base.update(status=SessionStatus.FAILED, sources=[], report=None, audits=[])
    elif shape == "evidence_without_url":
        base.update(
            status=SessionStatus.FAILED,
            sources=[],
            report=None,
            audits=[],
            evidence=[
                {
                    "task_id": 1,
                    "source_url": "",
                    "source_title": "",
                    "snippet": "a snippet the executor could not attribute",
                    "key_fact": "unattributed",
                }
            ],
        )
    elif shape == "plan_approved_no_report":
        base.update(
            status=SessionStatus.AWAITING_PLAN,
            report=None,
            audits=[("plan_approved", _hash(f"plan for run {index}"))],
        )
    elif shape == "plan_approved_no_plan":
        base.update(
            status=SessionStatus.AWAITING_PLAN,
            report=None,
            plan=None,
            audits=[("plan_approved", _hash(f"plan for run {index}"))],
        )
    base["shape"] = shape
    base["index"] = index
    return base


def plan_corpus(total: int) -> list[dict]:
    """Deterministic: the same `--runs` always produces the same corpus, in the same order."""
    weights = [s.weight for s in SHAPES]
    pool = sum(weights)
    counts = [max(1, round(total * w / pool)) for w in weights]
    # Trim or pad the commonest shape so the total is exact.
    while sum(counts) > total:
        counts[0] -= 1
    while sum(counts) < total:
        counts[0] += 1
    out = []
    for shape, count in zip(SHAPES, counts, strict=True):
        for _ in range(count):
            out.append(build_shape(shape.name, len(out)))
    return out


async def seed_corpus(db, saver, corpus: list[dict]) -> dict[str, uuid.UUID]:
    """Insert the V1 rows and write the real checkpoints. Returns session id → shape."""
    now = datetime(2026, 1, 1, tzinfo=UTC)
    uid, pid = uuid.uuid4(), uuid.uuid4()
    await db.execute(
        insert(User).values(
            id=uid, email=f"{uid}@dryrun.invalid", hashed_pw="x", is_active=True, created_at=now
        )
    )
    await db.execute(
        insert(Project).values(id=pid, user_id=uid, name="dry run", created_at=now, updated_at=now)
    )

    shapes: dict[str, uuid.UUID] = {}
    for spec in corpus:
        sid = uuid.uuid4()
        created = now + timedelta(seconds=spec["index"])
        await db.execute(
            insert(Session).values(
                id=sid,
                user_id=uid,
                project_id=pid,
                prompt=f"question {spec['index']}",
                status=spec["status"],
                research_depth="balanced",
                draft_report=spec["report"],
                final_report=spec["report"],
                sources=spec["sources"],
                rework_count=spec["rework"],
                total_cost_usd="0.012345",
                total_tokens_input=4321,
                total_tokens_output=1234,
                elapsed_seconds="12.50",
                corpus_mode=False,
                demo=spec["demo"],
                skip_plan_gate=False,
                error_message=spec["error"],
                model_routing={"planner": "google:gemini-2.5-flash"},
                plan_json=({"tasks": spec["plan"]} if spec["plan"] else None),
                outline_json=({"sections": ["Findings", "Limitations"]} if spec["plan"] else None),
                created_at=created,
                updated_at=created,
            )
        )
        for i, (action, digest) in enumerate(spec["audits"]):
            await db.execute(
                insert(AuditLog).values(
                    session_id=sid,
                    user_id=uid,
                    action=action,
                    feedback=None,
                    draft_hash=digest,
                    created_at=created + timedelta(seconds=i),
                )
            )
        await db.execute(
            insert(AgentLog).values(
                session_id=sid,
                event_type="node_finished",
                agent_name="planner",
                payload={"event": "node_finished", "agent": "planner"},
                created_at=created,
            )
        )
        if spec["checkpoint"] != "absent":
            await put_checkpoint(
                saver,
                str(sid),
                {"evidence": spec["evidence"], "contradictions": spec["contradictions"]},
                corrupt=spec["checkpoint"] == "corrupt",
            )
        shapes[str(sid)] = spec["shape"]
    await db.commit()
    return shapes


async def put_checkpoint(saver, thread_id: str, values: dict, *, corrupt: bool = False) -> None:
    """Write one real LangGraph checkpoint.

    `channel_versions` must name every channel: the saver stores channel values in a blob
    table keyed by (channel, version), and a value with no version is dropped on read —
    which would silently turn a populated checkpoint into an empty one.
    """
    from langgraph.checkpoint.base import empty_checkpoint

    checkpoint = empty_checkpoint()
    checkpoint["channel_values"] = dict(values)
    versions = {k: "1" for k in values}
    checkpoint["channel_versions"] = versions
    await saver.aput(
        {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
        checkpoint,
        {"source": "loop", "step": 1},
        versions,
    )
    if corrupt:
        # Not a mock: the real saver's own stored blob, made undecodable, so the real
        # `aget_tuple` raises the way it would over a truncated or wrong-codec row. This is
        # what produces a genuine UNREADABLE rather than a simulated one.
        await saver.conn.execute(
            "UPDATE checkpoints SET checkpoint = ? WHERE thread_id = ?",
            (b"\x00 not a valid serialised checkpoint", thread_id),
        )
        await saver.conn.commit()


# ── Measurement ───────────────────────────────────────────────────────────────────


@dataclass
class DryRunResult:
    target: str
    dialect: str
    runs_seeded: int
    considered: int
    accounted: int
    by_status: dict[str, int] = field(default_factory=dict)
    by_shape: dict[str, dict[str, int]] = field(default_factory=dict)
    rows_by_table: dict[str, int] = field(default_factory=dict)
    rows_by_table_in_db: dict[str, int] = field(default_factory=dict)
    total_rows: int = 0
    wall_seconds: float = 0.0
    rows_per_second: float = 0.0
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    max_ms: float = 0.0
    mean_ms: float = 0.0
    peak_heap_mb: float = 0.0
    failures: int = 0
    retries: int = 0
    # ── Gate A: representational fidelity ──
    fidelity: dict[str, int] = field(default_factory=dict)
    fidelity_not_comparable: dict[str, int] = field(default_factory=dict)
    fidelity_mismatch_fields: dict[str, int] = field(default_factory=dict)
    fidelity_limitations: dict[str, int] = field(default_factory=dict)
    # ── Gate B: internal bundle validity, both sides, never collapsed into Gate A ──
    validity: dict[str, int] = field(default_factory=dict)
    validity_failed_checks_v1: dict[str, int] = field(default_factory=dict)
    validity_failed_checks_v2: dict[str, int] = field(default_factory=dict)
    # ── Gate C: historical non-fabrication ──
    #: V1 could not assemble a bundle and V2 could, for a reason that is acceptable: V1's
    #: export route refuses a non-COMPLETED run that V2 nonetheless migrated in full.
    asymmetric_but_justified: int = 0
    grounding: dict[str, list[str]] = field(default_factory=dict)
    checks: dict[str, str] = field(default_factory=dict)
    resume: dict[str, int] = field(default_factory=dict)
    unmigratable: dict[str, int] = field(default_factory=dict)


def _pct(values: list[int], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return float(ordered[k])


async def _count(db, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def measure(
    db, saver, shapes: dict[str, str], *, interrupt_after: int | None = None
) -> DryRunResult:
    """Run the migration against the seeded corpus and grade it against every invariant.

    Three independent gates, each recorded as its own field rather than folded into one
    pass/fail — a bundle can land in any combination of them, and collapsing the gates
    would hide which kind of defect a failure actually is (M2F Amendment §10):

    * **Gate A — representational fidelity.** Does the V2 bundle say the same thing V1's
      did, field for field, for the sessions where a comparison is even possible?
    * **Gate B — internal bundle validity**, checked on both sides independently. A V1
      bundle and its V2 migration are graded separately so "the migration preserved an
      already-broken bundle" and "the migration broke a valid one" are distinguishable.
    * **Gate C — historical non-fabrication.** Every migrated column is grounded in a
      declared V1 source (`migration.provenance`), and the declared constants
      (UNCHECKED evidence, NULL claim lineage, …) actually hold in what got written —
      the map could claim UNCHECKED while the engine wrote ATTESTED, and only checking
      the data catches that.

    `interrupt_after` re-runs `migrate_all` a second time to prove resume is idempotent:
    the first pass commits and stops, the second must process only the remainder and
    must not re-insert what the first pass already wrote (`resume_duplicated_nothing`).

    Every named invariant in `checks` is a `_verdict(...)` computed from the actual rows
    in `db`, not asserted — this function is the harness the invariants are measured
    against, not a report of what they are supposed to be.
    """
    dialect = db.bind.dialect.name if db.bind is not None else "unknown"
    result = DryRunResult(
        target="", dialect=dialect, runs_seeded=len(shapes), considered=0, accounted=0
    )

    first_rows = 0
    if interrupt_after:
        # A clean stop after N runs, then a restart. The second pass below must process
        # only the remainder and must not touch what the first pass already committed —
        # which is what "resume is the default" has to mean in practice.
        first = await migrate_all(db, saver, limit=interrupt_after)
        first_rows = sum(first.rows_by_table.values())
        result.resume = {
            "first_pass_considered": first.considered,
            "first_pass_rows": first_rows,
            "ledger_rows_after_first_pass": await _count(db, MigrationLedger),
        }

    tracemalloc.start()
    t0 = time.perf_counter()
    report = await migrate_all(db, saver)
    wall = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    result.considered = report.considered
    result.accounted = report.accounted
    result.by_status = dict(sorted(report.by_status.items()))
    result.rows_by_table = dict(sorted(report.rows_by_table.items()))
    result.total_rows = sum(report.rows_by_table.values())
    result.wall_seconds = round(wall, 4)
    result.rows_per_second = round(result.total_rows / wall, 1) if wall else 0.0
    durations = report.durations_ms
    result.p50_ms = _pct(durations, 0.50)
    result.p95_ms = _pct(durations, 0.95)
    result.p99_ms = _pct(durations, 0.99)
    result.max_ms = float(max(durations)) if durations else 0.0
    result.mean_ms = round(statistics.fmean(durations), 2) if durations else 0.0
    result.peak_heap_mb = round(peak / (1024 * 1024), 3)

    result.rows_by_table_in_db = {
        name: await _count(db, model) for name, model in COUNTED_TABLES.items()
    }

    ledger = {str(r.session_id): r for r in (await db.execute(select(MigrationLedger))).scalars()}
    result.failures = sum(1 for r in ledger.values() if r.status == "FAILED")
    result.retries = sum(r.attempt - 1 for r in ledger.values())
    result.unmigratable = {}
    for row in ledger.values():
        if row.failure_category:
            key = row.failure_category
            result.unmigratable[key] = result.unmigratable.get(key, 0) + 1

    by_shape: dict[str, dict[str, int]] = {}
    for sid, shape in shapes.items():
        status = ledger[sid].status if sid in ledger else "NOT_PROCESSED"
        by_shape.setdefault(shape, {})
        by_shape[shape][status] = by_shape[shape].get(status, 0) + 1
    result.by_shape = {k: dict(sorted(v.items())) for k, v in sorted(by_shape.items())}

    # ── Ledger accounting: stated as checks, each with a pass/fail verdict ──
    sessions = (await db.execute(select(Session.id))).scalars().all()
    runs = {str(r) for r in (await db.execute(select(ResearchRun.id))).scalars()}
    ledgered_runs = {str(r.v2_run_id) for r in ledger.values() if r.v2_run_id}
    equivalent_but_invalid: list[str] = []
    unassembled_v1_but_v2: list[str] = []
    justified_asymmetry: list[str] = []
    checks = {
        "one_ledger_row_per_considered_session": _verdict(len(ledger) == len(sessions)),
        "no_unexplained_remainder": _verdict(report.accounted == report.considered),
        "every_outcome_is_terminal": _verdict(all(r.status in TERMINAL for r in ledger.values())),
        "every_v2_run_has_a_ledger_record": _verdict(runs == ledgered_runs),
        "rows_written_matches_the_database": _verdict(
            all(
                result.rows_by_table.get(name, 0) == result.rows_by_table_in_db.get(name, 0)
                for name in result.rows_by_table
            )
        ),
        "no_partial_rows_for_a_refused_run": _verdict(
            all(r.rows_written == 0 for r in ledger.values() if r.failure_category)
        ),
    }

    # ── The four refusals, checked at corpus scale rather than one fixture at a time ──
    runs_rows = (await db.execute(select(ResearchRun))).scalars().all()
    v1_failed = {
        str(r)
        for r in (
            await db.execute(select(Session.id).where(Session.status == SessionStatus.FAILED))
        ).scalars()
    }
    evidence_rows = (await db.execute(select(Evidence))).scalars().all()
    # V1 records `rework_count`, and it must never become a revision count: superseded
    # drafts were overwritten in place and are gone (M2E §3).
    max_revisions = (
        await db.execute(
            select(func.count())
            .select_from(Revision)
            .group_by(Revision.run_id)
            .limit(1)
            .order_by(func.count().desc())
        )
    ).scalar_one_or_none() or 0
    claim_rows = (await db.execute(select(Claim))).scalars().all()

    # Every source row must be traceable to an entry V1 actually recorded — no synthetic
    # source was invented to satisfy `evidence.source_id`.
    v1_source_urls: set[tuple[str, str]] = set()
    for sid, payload in (await db.execute(select(Session.id, Session.sources))).all():
        for entry in payload or []:
            if isinstance(entry, dict) and entry.get("url"):
                v1_source_urls.add((str(sid), entry["url"]))
    migrated_sources = {
        (str(row.run_id), row.url) for row in (await db.execute(select(Source))).scalars()
    }

    # ── F5's dangerous cases, each a named FAIL rather than a footnote ──
    contradiction_rows = (await db.execute(select(Contradiction))).scalars().all()
    review_rows = (await db.execute(select(Review))).scalars().all()
    artifact_rows = (await db.execute(select(ResearchArtifact))).scalars().all()

    # A source is grounded if its URL appears in the V1 snapshot OR on a V1 evidence chunk.
    # Recovery from the executor's own record is legitimate — `EvidenceChunk.source_url` is
    # a required V1 field — and anything else is invention. This replaces the older
    # snapshot-only check, which called a legitimate recovery a synthesis.
    v1_urls: set[tuple[str, str]] = set(v1_source_urls)
    for sid_ in (await db.execute(select(Session.id))).scalars().all():
        read = await read_checkpoint(saver, str(sid_))
        for item in read.evidence:
            if isinstance(item, dict) and item.get("source_url"):
                v1_urls.add((str(sid_), item["source_url"]))

    per_run_sequences: dict[str, list[int]] = {}
    for review in review_rows:
        per_run_sequences.setdefault(str(review.run_id), []).append(review.sequence)

    checks.update(
        {
            # PLAN approval → Artifact = FAIL
            "no_plan_review_can_authorize_an_artifact": _verdict(
                all(a.review_gate == "REPORT" for a in artifact_rows)
                and all(r.revision_id is None for r in review_rows if r.gate == "PLAN")
            ),
            "every_report_review_targets_a_revision": _verdict(
                all(r.revision_id is not None for r in review_rows if r.gate == "REPORT")
            ),
            # empty source_url → fabricated Source = FAIL
            "every_source_url_came_from_v1": _verdict(migrated_sources <= v1_urls),
            "no_source_carries_an_invented_citation_index": _verdict(
                all(
                    row.citation_index is None or row.citation_index >= 1
                    for row in (await db.execute(select(Source))).scalars()
                )
            ),
            # ambiguous evidence match → DETECTED contradiction = FAIL
            "detected_contradictions_have_both_source_anchors": _verdict(
                all(
                    (c.source_a_id is not None and c.source_b_id is not None)
                    for c in contradiction_rows
                    if c.detection_state == "DETECTED"
                )
            ),
            "evidence_refinement_is_all_or_nothing": _verdict(
                all(
                    (c.evidence_a_id is None) == (c.evidence_b_id is None)
                    for c in contradiction_rows
                )
            ),
            "no_contradiction_claims_evidence_without_a_source": _verdict(
                all(
                    c.source_a_id is not None
                    for c in contradiction_rows
                    if c.evidence_a_id is not None
                )
            ),
            # review ordering
            "review_order_is_total_within_each_run": _verdict(
                all(
                    sorted(seqs) == list(range(1, len(seqs) + 1))
                    for seqs in per_run_sequences.values()
                )
            ),
            "cancellation_never_becomes_CANCELLED": _verdict(
                all(r.status != "CANCELLED" and r.cancelled_at is None for r in runs_rows)
            ),
            "a_v1_FAILED_run_stays_FAILED": _verdict(
                all(r.status == "FAILED" for r in runs_rows if str(r.id) in v1_failed)
            ),
            "rework_count_never_manufactures_revisions": _verdict(max_revisions <= 1),
            "evidence_is_never_ATTESTED": _verdict(
                all(
                    e.provenance_state == "UNCHECKED"
                    and e.attested_against is None
                    and e.attestation_run_at is None
                    for e in evidence_rows
                )
            ),
            "claim_lineage_is_always_NULL": _verdict(all(c.lineage_id is None for c in claim_rows)),
            "every_shape_lands_where_expected": _verdict(
                all(
                    set(result.by_shape.get(shape.name, {})) in ({shape.expect}, set())
                    for shape in SHAPES
                )
            ),
        }
    )
    if interrupt_after:
        result.resume["second_pass_considered"] = report.considered
        result.resume["second_pass_rows"] = result.total_rows
        checks["resume_processed_only_the_remainder"] = _verdict(
            result.resume["first_pass_considered"] + report.considered == len(shapes)
        )
        checks["resume_duplicated_nothing"] = _verdict(
            first_rows + result.total_rows
            == sum(result.rows_by_table_in_db[n] for n in result.rows_by_table_in_db)
        )
        # `rows_written` is per-pass, so the whole-database comparison above replaces the
        # single-pass check rather than sitting beside it.
        checks.pop("rows_written_matches_the_database", None)

    # ── Gates A, B and C over every session, migrated or not ──
    #
    # Three fields, never one verdict. A bundle can be equivalent and invalid (the whole of
    # the M2E-2 corpus was), valid and intentionally lossy, or not comparable and still
    # required to be grounded (M2F Amendment §10).
    fidelity: dict[str, int] = {}
    not_comparable: dict[str, int] = {}
    fields: dict[str, int] = {}
    limitations: dict[str, int] = {}
    validity: dict[str, int] = {}
    failed_v1: dict[str, int] = {}
    failed_v2: dict[str, int] = {}

    def _bump(bucket: dict, key: str) -> None:
        bucket[key] = bucket.get(key, 0) + 1

    for sid in sessions:
        session = (await db.execute(select(Session).where(Session.id == sid))).scalar_one()
        run = await validate_run(db, saver, session)

        _bump(fidelity, str(run.fidelity.verdict))
        if run.fidelity.verdict is BundleVerdict.NOT_COMPARABLE:
            _bump(
                not_comparable,
                f"v1={'+'.join(run.fidelity.v1_reasons)} | v2={'+'.join(run.fidelity.v2_reasons)}",
            )
        for name in run.fidelity.differing_fields:
            _bump(fields, name)
        if run.fidelity.limitation:
            _bump(limitations, run.fidelity.limitation)

        # `passed is None` means not measured. Rendered as "unassembled", never as a
        # failure — a bundle that could not be built has not failed verification.
        def _side(v):
            return "unassembled" if v.passed is None else ("valid" if v.passed else "invalid")

        _bump(validity, f"v1={_side(run.validity_v1)},v2={_side(run.validity_v2)}")
        for name in run.validity_v1.failed_checks:
            _bump(failed_v1, name)
        for name in run.validity_v2.failed_checks:
            _bump(failed_v2, name)

        if run.fidelity.verdict is BundleVerdict.BUNDLE_EQUIVALENT and not (
            run.validity_v1.passed and run.validity_v2.passed
        ):
            equivalent_but_invalid.append(str(sid))
        # V1 could not produce a bundle at all but V2 did: either V2 is asserting evidence
        # V1 never had, or the run legitimately migrated a report V1's export route refused
        # (non-COMPLETED status). Only the second is acceptable, so it is checked, not
        # assumed.
        if not run.validity_v1.assembled and run.validity_v2.assembled:
            justified = "V1_STATUS_NOT_COMPLETED" in run.fidelity.v1_reasons and (
                "V1_CHECKPOINT_MISSING" not in run.fidelity.v1_reasons
                and "V1_CHECKPOINT_UNREADABLE" not in run.fidelity.v1_reasons
            )
            (unassembled_v1_but_v2 if not justified else justified_asymmetry).append(str(sid))

    result.fidelity = dict(sorted(fidelity.items()))
    result.fidelity_not_comparable = dict(sorted(not_comparable.items()))
    result.fidelity_mismatch_fields = dict(sorted(fields.items()))
    result.fidelity_limitations = dict(sorted(limitations.items()))
    result.validity = dict(sorted(validity.items()))
    result.validity_failed_checks_v1 = dict(sorted(failed_v1.items()))
    result.validity_failed_checks_v2 = dict(sorted(failed_v2.items()))

    # Gate C is corpus-wide by construction: a declaration about the engine's source plus a
    # check of every declared constant against every migrated row. Both halves are needed —
    # the map could say UNCHECKED while the engine writes ATTESTED, and only the second
    # would notice.
    result.asymmetric_but_justified = len(justified_asymmetry)
    result.grounding = {
        "undeclared_columns": provenance.undeclared_columns(),
        "stale_declarations": provenance.stale_declarations(),
        "constant_violations": await provenance.constant_violations(db),
    }

    checks.update(
        {
            # Gate A
            "every_bundle_mismatch_is_a_named_limitation": _verdict(
                "UNCLASSIFIED" not in limitations
            ),
            "no_generic_not_comparable_bucket": _verdict(
                all(" | v2=" in key and not key.endswith("v2=") for key in not_comparable)
            ),
            # Gate B — the pairing is what carries meaning, not either side alone.
            "no_migration_broke_a_valid_bundle": _verdict(
                not any(k.startswith("v1=valid,v2=invalid") for k in validity)
            ),
            "no_v2_bundle_repairs_an_invalid_v1": _verdict(
                not any(k.startswith("v1=invalid,v2=valid") for k in validity)
            ),
            "equivalent_bundles_are_valid_on_both_sides": _verdict(not equivalent_but_invalid),
            "no_unjustified_v2_bundle_where_v1_had_none": _verdict(not unassembled_v1_but_v2),
            # Gate C
            "every_migrated_column_is_grounded": _verdict(
                not result.grounding["undeclared_columns"]
                and not result.grounding["stale_declarations"]
            ),
            "declared_constants_hold_in_the_data": _verdict(
                not result.grounding["constant_violations"]
            ),
        }
    )
    result.checks = dict(sorted(checks.items()))
    return result


def _verdict(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


# ── Entry point ───────────────────────────────────────────────────────────────────


async def _main(args: argparse.Namespace) -> int:
    try:
        check_target(args.database_url, apply=True, confirm=args.confirm_database)
    except Refused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    print(describe(args.database_url, apply=True), file=sys.stderr)
    engine = create_async_engine(args.database_url)
    tmpdir = tempfile.mkdtemp(prefix="m2e-dryrun-")
    try:
        async with engine.connect() as conn:
            if conn.dialect.name == "postgresql":
                actual = (await conn.execute(text("SELECT current_database()"))).scalar_one()
                print(f"  connected : {actual}\n", file=sys.stderr)
                if actual != args.confirm_database:
                    print(f"refused: server reports {actual!r}", file=sys.stderr)
                    return 2
            tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))

        if args.create_schema:
            # The desktop host's path (`create_all`), offered because SQLite has no Alembic
            # story in this repository. Creates missing tables only; it never drops or
            # alters, so it cannot damage a database that already has a schema.
            from app.models import POSTGRES_ONLY_TABLES, Base

            wanted = [
                t
                for t in Base.metadata.sorted_tables
                if not (conn.dialect.name == "sqlite" and t.name in POSTGRES_ONLY_TABLES)
            ]
            async with engine.begin() as conn2:
                await conn2.run_sync(lambda c: Base.metadata.create_all(c, tables=wanted))
            async with engine.connect() as conn3:
                tables = await conn3.run_sync(lambda c: set(inspect(c).get_table_names()))

        missing = {"sessions", "research_runs", "migration_ledger"} - tables
        if missing:
            print(f"refused: missing {sorted(missing)} — run alembic upgrade head", file=sys.stderr)
            return 2
        async with engine.connect() as conn:
            existing = (await conn.execute(text("SELECT count(*) FROM sessions"))).scalar_one()

        # The load-bearing guard: this tool SEEDS a corpus, so a non-empty target is not a
        # disposable database. Production has sessions, so a mistyped DSN stops here.
        if existing:
            print(
                f"refused: {database_name(args.database_url)} already holds {existing} sessions; "
                "the dry run only writes to an empty, disposable database",
                file=sys.stderr,
            )
            return 2

        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        maker = async_sessionmaker(engine, expire_on_commit=False)
        checkpoint_path = str(Path(tmpdir) / "checkpoints.sqlite")
        async with AsyncSqliteSaver.from_conn_string(checkpoint_path) as saver, maker() as db:
            corpus = plan_corpus(args.runs)
            shapes = await seed_corpus(db, saver, corpus)
            print(
                f"  seeded    : {len(shapes)} V1 sessions across {len(SHAPES)} shapes\n",
                file=sys.stderr,
            )
            result = await measure(db, saver, shapes, interrupt_after=args.interrupt_after)

        result.target = f"{database_name(args.database_url)} ({result.dialect})"
        payload = asdict(result)
        text_out = json.dumps(payload, indent=2, sort_keys=True)
        print(text_out)
        if args.out:
            Path(args.out).write_text(text_out + "\n", encoding="utf-8")
        failed = [k for k, v in result.checks.items() if v != "PASS"]
        return 1 if failed else 0
    finally:
        await engine.dispose()


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m migration.dryrun",
        description="Seed a representative V1 corpus into a DISPOSABLE database and migrate it.",
    )
    p.add_argument(
        "--database-url", required=True, help="Disposable target. DATABASE_URL is never read."
    )
    p.add_argument(
        "--confirm-database", required=True, help="Must match the database the DSN names."
    )
    p.add_argument("--runs", type=int, default=100, help="How many V1 sessions to seed.")
    p.add_argument("--out", default=None, help="Write the JSON result here.")
    p.add_argument(
        "--interrupt-after",
        type=int,
        default=None,
        help="Stop cleanly after N runs, then restart — proves resume. Timings then cover "
        "the second pass only, so measure performance in a run without this flag.",
    )
    p.add_argument(
        "--create-schema",
        action="store_true",
        help="Build missing tables with create_all (the desktop host's path). Never drops.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_main(parser().parse_args(argv)))


if __name__ == "__main__":  # pragma: no cover — exercised through main()
    raise SystemExit(main())
