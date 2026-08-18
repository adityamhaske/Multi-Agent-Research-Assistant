"""
V1 → V2 migration (M2E), against a disposable SQLite database.

Never touches production: every fixture builds its own file-backed SQLite schema from
`Base.metadata` and throws it away. No test in this module reads `DATABASE_URL`.

The load-bearing assertions are the ones about *refusal*: that a missing checkpoint is not
reported as empty, that an unreadable one is not reported as empty, that V1 evidence never
becomes ATTESTED, and that a state V2 cannot represent is classified rather than invented.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, func, insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import POSTGRES_ONLY_TABLES, Base
from app.models.audit_log import AuditLog
from app.models.project import Project
from app.models.research import Evidence, ResearchRun, Source
from app.models.review import Review
from app.models.revision import Claim, Revision
from app.models.session import Session, SessionStatus
from app.models.user import User
from migration.checkpoint import CheckpointOutcome, read_checkpoint
from migration.ledger import MigrationLedger, MigrationStatus
from migration.runner import migrate_all

REPORT = (
    "# Findings\n\nRecall improved by twelve points on the benchmark [1]. "
    "A second sentence that also carries a marker [2].\n\n## Sources\n\n1. https://e.org/a\n"
)
SOURCES = [
    {"index": 1, "url": "https://e.org/a", "title": "A", "snippet": "s", "snippets": ["s"]},
    {"index": 2, "url": "https://e.org/b", "title": "B", "snippet": "t", "snippets": ["t"]},
]
EVIDENCE = [
    {
        "task_id": 1,
        "source_url": "https://e.org/a",
        "source_title": "A",
        "snippet": "Recall improved by twelve points.",
        "key_fact": "recall up",
    },
    {
        "task_id": 2,
        "source_url": "https://e.org/b",
        "source_title": "B",
        "snippet": "",
        "key_fact": "blanked by V1 verification",
    },
]


class FakeSaver:
    """A checkpoint saver whose three outcomes are explicit.

    `None` → the thread has no snapshot. `BOOM` → decoding raises. Anything else is a
    decodable snapshot, whose evidence may still be empty.
    """

    BOOM = object()

    def __init__(self, threads: dict[str, object]) -> None:
        self._threads = threads

    async def aget_tuple(self, config):
        tid = config["configurable"]["thread_id"]
        if tid not in self._threads:
            return None
        payload = self._threads[tid]
        if payload is self.BOOM:
            raise RuntimeError("checkpoint blob is corrupt")

        class _T:
            checkpoint = {"channel_values": payload}

        return _T()


@pytest.fixture
async def db(tmp_path):
    """A disposable SQLite database. Explicitly not the production DSN."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'm2e.sqlite'}")

    @event.listens_for(engine.sync_engine, "connect")
    def _fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    tables = [t for t in Base.metadata.sorted_tables if t.name not in POSTGRES_ONLY_TABLES]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def seed(
    db,
    *,
    status=SessionStatus.COMPLETED,
    report=REPORT,
    sources=SOURCES,
    rework=0,
    audits=(),
    error=None,
):
    now = datetime.now(UTC)
    uid, pid, sid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await db.execute(
        insert(User).values(
            id=uid, email=f"{uid}@x.invalid", hashed_pw="x", is_active=True, created_at=now
        )
    )
    await db.execute(
        insert(Project).values(id=pid, user_id=uid, name="P", created_at=now, updated_at=now)
    )
    await db.execute(
        insert(Session).values(
            id=sid,
            user_id=uid,
            project_id=pid,
            prompt="q",
            status=status,
            research_depth="fast",
            draft_report=report,
            final_report=report if report else None,
            sources=sources,
            rework_count=rework,
            total_cost_usd=1,
            total_tokens_input=10,
            total_tokens_output=5,
            corpus_mode=False,
            demo=False,
            skip_plan_gate=False,
            error_message=error,
            created_at=now,
            updated_at=now,
        )
    )
    for action, h in audits:
        await db.execute(
            insert(AuditLog).values(
                session_id=sid,
                user_id=uid,
                action=action,
                feedback=None,
                draft_hash=h,
                created_at=now,
            )
        )
    await db.commit()
    return sid


async def _count(db, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


# ── A / B / C: the tri-state, which is the whole point ───────────────────────────


async def test_empty_checkpoint_is_EMPTY_not_missing(db):
    sid = await seed(db)
    saver = FakeSaver({str(sid): {"evidence": [], "contradictions": []}})
    await migrate_all(db, saver)
    led = (await db.execute(select(MigrationLedger))).scalar_one()
    assert led.status == MigrationStatus.EMPTY
    assert led.evidence_outcome == "NONE_PRESENT"


async def test_missing_checkpoint_is_CHECKPOINT_MISSING_not_empty(db):
    await seed(db)
    await migrate_all(db, FakeSaver({}))  # no thread at all
    led = (await db.execute(select(MigrationLedger))).scalar_one()
    assert led.status == MigrationStatus.CHECKPOINT_MISSING
    assert led.evidence_outcome == "CHECKPOINT_MISSING"
    assert led.status != MigrationStatus.EMPTY


async def test_unreadable_checkpoint_is_READ_FAILURE_not_empty(db):
    sid = await seed(db)
    await migrate_all(db, FakeSaver({str(sid): FakeSaver.BOOM}))
    led = (await db.execute(select(MigrationLedger))).scalar_one()
    assert led.status == MigrationStatus.READ_FAILURE
    assert led.evidence_outcome == "CHECKPOINT_UNREADABLE"
    assert led.status != MigrationStatus.EMPTY


async def test_the_three_outcomes_are_distinct_at_the_reader(db):
    saver = FakeSaver({"read": {"evidence": []}, "boom": FakeSaver.BOOM})
    assert (await read_checkpoint(saver, "read")).outcome is CheckpointOutcome.READ
    assert (await read_checkpoint(saver, "gone")).outcome is CheckpointOutcome.MISSING
    assert (await read_checkpoint(saver, "boom")).outcome is CheckpointOutcome.UNREADABLE


# ── D: idempotency ───────────────────────────────────────────────────────────────


async def test_running_twice_duplicates_nothing(db):
    sid = await seed(db)
    saver = FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": []}})
    await migrate_all(db, saver)
    first = {
        m.__name__: await _count(db, m) for m in (ResearchRun, Source, Evidence, Revision, Claim)
    }
    await migrate_all(db, saver)
    second = {
        m.__name__: await _count(db, m) for m in (ResearchRun, Source, Evidence, Revision, Claim)
    }
    assert first == second, f"second pass duplicated rows: {first} → {second}"
    assert (await db.execute(select(func.count()).select_from(MigrationLedger))).scalar_one() == 1


async def test_v2_ids_are_deterministic_not_random(db):
    """Idempotency must not depend on the ledger being correct."""
    sid = await seed(db)
    saver = FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": []}})
    await migrate_all(db, saver)
    before = sorted(str(r) for r in (await db.execute(select(Evidence.id))).scalars())
    await db.execute(MigrationLedger.__table__.delete())  # forget we ever ran
    await db.commit()
    await migrate_all(db, saver)  # collides, does not duplicate
    after = sorted(str(r) for r in (await db.execute(select(Evidence.id))).scalars())
    assert before == after


# ── G: provenance ────────────────────────────────────────────────────────────────


async def test_no_v1_evidence_becomes_attested(db):
    sid = await seed(db)
    saver = FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": []}})
    await migrate_all(db, saver)
    rows = (await db.execute(select(Evidence))).scalars().all()
    assert rows, "nothing migrated — the assertion below would be vacuous"
    for e in rows:
        assert e.provenance_state == "UNCHECKED"
        assert e.attested_against is None and e.attestation_run_at is None


async def test_a_blanked_snippet_is_preserved_not_invented(db):
    sid = await seed(db)
    saver = FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": []}})
    await migrate_all(db, saver)
    empties = [e for e in (await db.execute(select(Evidence))).scalars() if e.snippet == ""]
    assert len(empties) == 1, "V1's blanked snippet must survive as an empty string"


# ── H / I / J: the three refusals ────────────────────────────────────────────────


async def test_a_cancelled_run_stays_FAILED(db):
    sid = await seed(db, status=SessionStatus.FAILED, error="Research stopped by user.")
    await migrate_all(db, FakeSaver({str(sid): {"evidence": [], "contradictions": []}}))
    run = (await db.execute(select(ResearchRun))).scalar_one()
    assert run.status == "FAILED"
    assert run.cancelled_at is None


async def test_rework_count_does_not_manufacture_revisions(db):
    sid = await seed(db, rework=3)  # V1 claims 3 reworks; 1 report survives
    await migrate_all(db, FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": []}}))
    assert await _count(db, Revision) == 1


async def test_claim_lineage_is_never_inferred(db):
    sid = await seed(db)
    await migrate_all(db, FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": []}}))
    rows = (await db.execute(select(Claim))).scalars().all()
    assert rows
    assert all(c.lineage_id is None for c in rows)
    assert all(c.extraction_method == "DERIVED_FROM_REPORT" for c in rows)
    assert all(c.verification_state == "UNCHECKED" for c in rows)


# ── K / L: the two open mapping problems, resolved conservatively ────────────────


async def test_a_review_without_a_report_is_classified_not_dropped(db):
    """`submit_plan` runs at AWAITING_PLAN, before any draft exists (verified in code).

    `reviews.revision_id` is NOT NULL, so V2 cannot hold it. Refuse the run rather than
    fabricate a revision or discard the approval.
    """
    sid = await seed(
        db, status=SessionStatus.FAILED, report=None, audits=[("plan_approved", "a" * 64)]
    )
    await migrate_all(db, FakeSaver({str(sid): {"evidence": [], "contradictions": []}}))
    led = (await db.execute(select(MigrationLedger))).scalar_one()
    assert led.status == MigrationStatus.INCONSISTENT_V1
    assert led.failure_category == "REVIEW_WITHOUT_REVISION"
    assert await _count(db, Revision) == 0, "no revision may be fabricated to hold a review"
    assert await _count(db, ResearchRun) == 0, "the run must not be half-migrated"
    # The V1 review is untouched and still there.
    assert (await db.execute(select(func.count()).select_from(AuditLog))).scalar_one() == 1


async def test_evidence_with_no_resolvable_source_is_classified_not_invented(db):
    """Sources are derived by the synthesizer; a run that failed earlier has none."""
    sid = await seed(db, sources=None)
    await migrate_all(db, FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": []}}))
    led = (await db.execute(select(MigrationLedger))).scalar_one()
    assert led.status == MigrationStatus.INCONSISTENT_V1
    assert led.failure_category == "EVIDENCE_SOURCE_UNRESOLVED"
    assert await _count(db, Source) == 0, "no synthetic source may be invented"
    assert await _count(db, Evidence) == 0


# ── F: transaction boundary ──────────────────────────────────────────────────────


async def test_a_refused_run_leaves_no_partial_v2_rows(db):
    """The run inserts research_runs/sources first, then hits the refusal — all must roll back."""
    sid = await seed(db, sources=None)
    await migrate_all(db, FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": []}}))
    for model in (ResearchRun, Source, Evidence, Revision, Claim, Review):
        assert await _count(db, model) == 0, f"{model.__name__} survived a rolled-back run"
    assert await _count(db, MigrationLedger) == 1, "the ledger must still explain the run"


# ── N: coverage accounting ───────────────────────────────────────────────────────


async def test_every_considered_session_lands_in_exactly_one_terminal_bucket(db):
    good = await seed(db)
    empty = await seed(db)
    missing = await seed(db)
    bad = await seed(db, sources=None)
    saver = FakeSaver(
        {
            str(good): {"evidence": EVIDENCE, "contradictions": []},
            str(empty): {"evidence": [], "contradictions": []},
            str(bad): {"evidence": EVIDENCE, "contradictions": []},
        }
    )
    report = await migrate_all(db, saver)
    assert report.considered == 4
    assert report.accounted == report.considered, "unexplained remainder"
    assert await _count(db, MigrationLedger) == 4
    statuses = {
        r.session_id: r.status for r in (await db.execute(select(MigrationLedger))).scalars()
    }
    assert statuses[good] == MigrationStatus.MIGRATED
    assert statuses[empty] == MigrationStatus.EMPTY
    assert statuses[missing] == MigrationStatus.CHECKPOINT_MISSING
    assert statuses[bad] == MigrationStatus.INCONSISTENT_V1


async def test_absence_from_the_ledger_means_not_processed(db):
    await seed(db)
    await seed(db)
    saver = FakeSaver({})
    await migrate_all(db, saver, limit=1)
    assert await _count(db, MigrationLedger) == 1, "the unprocessed session must have NO row"
