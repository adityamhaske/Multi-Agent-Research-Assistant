"""
Migration driver: transactions, ledger, resume, idempotency (M2E §3–§5).

One transaction per run — read V1, derive V2, insert V2, write the ledger, commit. Any
failure rolls the whole run back, so a partially migrated run can never appear successful
and can never leave V2 rows behind without a ledger row to explain them.

Sequential and single-connection by measurement, not by default: M2C.5 found concurrency
flat on throughput and 14× worse at p99, because the checkpoint saver serialises anyway.
Peak heap was 3.5 MB for 2,000 runs, so there is no memory pressure to batch away either.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session
from migration.engine import Unmigratable, migrate_session
from migration.ledger import TERMINAL, MigrationLedger, MigrationStatus


@dataclass
class MigrationReport:
    considered: int = 0
    by_status: dict[str, int] = field(default_factory=dict)
    rows_by_table: dict[str, int] = field(default_factory=dict)
    durations_ms: list[int] = field(default_factory=list)
    wall_seconds: float = 0.0

    def record(self, status: str, counts: dict[str, int], ms: int) -> None:
        self.considered += 1
        self.by_status[status] = self.by_status.get(status, 0) + 1
        for table, n in counts.items():
            self.rows_by_table[table] = self.rows_by_table.get(table, 0) + n
        self.durations_ms.append(ms)

    @property
    def accounted(self) -> int:
        """Every considered session must land in exactly one terminal bucket (M2E §N)."""
        return sum(self.by_status.values())


async def _ledger_for(db: AsyncSession, session_id) -> MigrationLedger | None:
    return (
        await db.execute(select(MigrationLedger).where(MigrationLedger.session_id == session_id))
    ).scalar_one_or_none()


async def migrate_all(
    db: AsyncSession,
    saver,
    *,
    limit: int | None = None,
    retry_failed: bool = False,
    dry_run: bool = False,
) -> MigrationReport:
    """Migrate every V1 session without a terminal ledger row.

    Resume is the default and needs no flag: a session already carrying a terminal status
    is skipped, so re-running continues rather than repeating. `retry_failed` additionally
    re-attempts rows in `FAILED` — the one retryable terminal state.
    """
    report = MigrationReport()
    t0 = time.perf_counter()

    # Ids first, rows one at a time — NOT a list of ORM objects.
    #
    # Loading every `Session` up front looks cheaper and is wrong: the first run that
    # rolls back expires **every** object in the identity map, including the ones not
    # processed yet. The next iteration then touches an expired attribute outside the
    # greenlet context and dies with `MissingGreenlet` — so one refused run would abort
    # the whole migration. Found by the M2E-2 dry run, whose corpus has a refusal in the
    # middle rather than at the end (the M2E-1 test happened to put it last).
    #
    # `(created_at, id)` rather than `created_at` alone: `--limit` and resume must cut the
    # corpus at the same place every time, and timestamps tie.
    session_ids = (
        (await db.execute(select(Session.id).order_by(Session.created_at.asc(), Session.id.asc())))
        .scalars()
        .all()
    )

    processed = 0
    for session_id in session_ids:
        if limit is not None and processed >= limit:
            break
        existing = await _ledger_for(db, session_id)
        if existing is not None and existing.status in TERMINAL:
            if not (retry_failed and existing.status == MigrationStatus.FAILED):
                continue
        processed += 1

        run_t0 = time.perf_counter()
        attempt = (existing.attempt + 1) if existing else 1
        try:
            # Re-read inside the attempt: a previous rollback may have expired this row.
            session = (
                await db.execute(select(Session).where(Session.id == session_id))
            ).scalar_one()
            result = await migrate_session(db, saver, session)
            status, category, detail = result.status, None, None
            ev, rev, art = result.evidence_outcome, result.revision_outcome, result.artifact_outcome
            counts, rows, ms = result.counts, result.rows_written, result.duration_ms
            # A checkpoint the migration could not read is not a migrated run.
            #
            # `status` is one slot and a run can carry two findings at once (no evidence
            # AND no report). The precedence is deliberate and fixed: **checkpoint outcome
            # outranks revision outcome**, because an unread checkpoint says the migration
            # could not see the run, while a missing report is something the migration
            # could see. Neither fact is lost — `evidence_outcome` and `revision_outcome`
            # are separate columns and both are always written.
            if ev == "CHECKPOINT_MISSING":
                status = MigrationStatus.CHECKPOINT_MISSING
            elif ev == "CHECKPOINT_UNREADABLE":
                status = MigrationStatus.READ_FAILURE
            elif ev == "NONE_PRESENT":
                status = MigrationStatus.EMPTY
            elif rev == "NO_REPORT":
                status = MigrationStatus.NO_REPORT
        except Unmigratable as exc:
            await db.rollback()
            status, category, detail = MigrationStatus.INCONSISTENT_V1, exc.category, exc.detail
            ev = rev = art = None
            counts, rows, ms = {}, 0, int((time.perf_counter() - run_t0) * 1000)
        except Exception as exc:  # noqa: BLE001 — retryable
            await db.rollback()
            status = MigrationStatus.FAILED
            category, detail = type(exc).__name__, str(exc)[:400]
            ev = rev = art = None
            counts, rows, ms = {}, 0, int((time.perf_counter() - run_t0) * 1000)

        await db.execute(delete(MigrationLedger).where(MigrationLedger.session_id == session_id))
        await db.execute(
            MigrationLedger.__table__.insert().values(
                session_id=session_id,
                status=str(status),
                attempt=attempt,
                v2_run_id=session_id if rows else None,
                failure_category=category,
                detail=detail,
                evidence_outcome=ev,
                revision_outcome=rev,
                artifact_outcome=art,
                rows_written=rows,
                duration_ms=ms,
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
            )
        )
        if dry_run:
            await db.rollback()
        else:
            await db.commit()
        report.record(str(status), counts, ms)

    report.wall_seconds = time.perf_counter() - t0
    return report
