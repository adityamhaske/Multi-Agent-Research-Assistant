"""
M2E-2 dry-run scenarios: resume, partial failure, retry, ledger accounting, and bundle
equivalence — all against disposable SQLite databases.

Companion to `test_migration_engine.py`, which owns the tri-state and the four refusals.
This module owns the properties that only appear once the migration is *driven*: what
survives an interruption, what a failed run leaves behind, and whether the V2 representation
says the same thing V1 said.

Nothing here reads `DATABASE_URL`. The Postgres half of the dry run lives in
`migration/dryrun.py`, which refuses to run against anything it was not explicitly pointed at.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select, update

from app.models.research import Evidence, ResearchRun, Source
from app.models.review import Review
from app.models.revision import Claim, ClaimEvidenceLink, Revision
from app.models.session import Session, SessionStatus
from migration import engine as engine_mod
from migration.bundle_equivalence import (
    KNOWN_LOSSY,
    REVIEW_TO_V1_ACTION,
    BundleVerdict,
    compare_run,
)
from migration.checkpoint import CheckpointOutcome, read_checkpoint
from migration.dryrun import put_checkpoint
from migration.ledger import TERMINAL, MigrationLedger, MigrationStatus
from migration.runner import migrate_all
from tests.migration_support import (
    CONTRADICTIONS,
    EVIDENCE,
    PLAN,
    FakeSaver,
    open_db,
    seed,
)

ROUTING = {"planner": "google:gemini-2.5-flash", "synthesizer": "google:gemini-2.5-flash"}
TRACE = [{"event": "node_finished", "agent": "planner", "detail": "3 tasks"}]


@pytest.fixture
async def maker(tmp_path):
    """A disposable SQLite database, handed out as a session *factory*.

    A factory rather than a session because the resume tests need to drop a connection
    mid-migration and open a fresh one, which is what a restarted process does.
    """
    async with open_db(tmp_path / "dryrun.sqlite") as factory:
        yield factory


@pytest.fixture
async def db(maker):
    async with maker() as session:
        yield session


async def _count(db, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def _seed_complete(db, **kw):
    """One fully-populated COMPLETED session: plan, sources, evidence, report, approval."""
    kw.setdefault("audits", [("plan_approved", "a" * 64), ("approved", "b" * 64)])
    return await seed(db, plan=PLAN, trace=TRACE, routing=ROUTING, **kw)


# ── E: bundle equivalence ─────────────────────────────────────────────────────────


async def test_a_fully_migrated_run_is_bundle_equivalent(db):
    sid = await _seed_complete(db)
    saver = FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": []}})
    await migrate_all(db, saver)

    session = (await db.execute(select(Session).where(Session.id == sid))).scalar_one()
    result = await compare_run(db, saver, session)
    assert result.verdict is BundleVerdict.BUNDLE_EQUIVALENT, (
        result.differing_fields,
        result.detail,
    )


async def test_bundle_equivalence_is_not_a_claim_about_truthfulness(db):
    """The verdict is about representation, and the fixture proves the distinction.

    This run's evidence contains a snippet V1 *blanked* because it failed verification, and
    a citation the report carries. The bundles agree — and the V2 evidence is still
    UNCHECKED, still carries an empty snippet, and still proves nothing about the research.
    """
    sid = await _seed_complete(db)
    saver = FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": []}})
    await migrate_all(db, saver)
    session = (await db.execute(select(Session).where(Session.id == sid))).scalar_one()
    assert (await compare_run(db, saver, session)).verdict is BundleVerdict.BUNDLE_EQUIVALENT

    rows = (await db.execute(select(Evidence))).scalars().all()
    assert any(e.snippet == "" for e in rows), "the blanked snippet is still blank"
    assert all(e.provenance_state == "UNCHECKED" for e in rows)


async def test_a_v2_difference_is_reported_not_ignored(db):
    """Change one V2 field after migration; the comparison must name it."""
    sid = await _seed_complete(db)
    saver = FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": []}})
    await migrate_all(db, saver)

    await db.execute(
        update(ResearchRun).where(ResearchRun.id == sid).values(question="a different question")
    )
    await db.commit()

    session = (await db.execute(select(Session).where(Session.id == sid))).scalar_one()
    result = await compare_run(db, saver, session)
    assert result.verdict is BundleVerdict.BUNDLE_MISMATCH
    assert "query" in result.differing_fields
    assert "bundle_hash" in result.differing_fields, "the digest must move with the field"
    # A difference nobody has named is louder than one that has been: the dry run fails
    # the whole run on UNCLASSIFIED, so a new V2 gap cannot be absorbed as "expected".
    assert result.limitation == "UNCLASSIFIED"


async def test_contradictions_do_not_round_trip_and_say_so(db):
    """A documented V2 mapping limitation, surfaced rather than normalised away.

    V1 keys a contradiction by source URL. V2 keys it by evidence id, and the migration
    leaves both NULL because V1 never recorded which evidence row a side came from. The
    bundle therefore cannot be rebuilt, and the comparison reports exactly that field.
    """
    sid = await _seed_complete(db)
    saver = FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": CONTRADICTIONS}})
    await migrate_all(db, saver)

    session = (await db.execute(select(Session).where(Session.id == sid))).scalar_one()
    result = await compare_run(db, saver, session)
    assert result.verdict is BundleVerdict.BUNDLE_MISMATCH
    assert result.differing_fields == ["contradictions", "bundle_hash"]
    assert result.limitation == "CONTRADICTION_PAIR_NOT_STORED"


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"status": SessionStatus.FAILED}, "V1_STATUS_"),
        ({"report": None}, "V1_NO_REPORT"),
    ],
)
async def test_uncomparable_runs_are_labelled_not_scored(db, kwargs, reason):
    sid = await seed(db, **kwargs)
    saver = FakeSaver({str(sid): {"evidence": [], "contradictions": []}})
    session = (await db.execute(select(Session).where(Session.id == sid))).scalar_one()
    result = await compare_run(db, saver, session)
    assert result.verdict is BundleVerdict.NOT_COMPARABLE
    assert result.reason.startswith(reason)


async def test_a_missing_checkpoint_is_not_comparable_rather_than_empty(db):
    """The tri-state again, one level up: no snapshot ≠ a bundle with no evidence."""
    sid = await _seed_complete(db)
    session = (await db.execute(select(Session).where(Session.id == sid))).scalar_one()
    result = await compare_run(db, FakeSaver({}), session)
    assert result.verdict is BundleVerdict.NOT_COMPARABLE
    assert result.reason == "V1_CHECKPOINT_MISSING"


async def test_the_audit_action_map_is_invertible(db):
    """The V2 approval chain is rebuilt by inverting `engine.AUDIT_MAP`.

    If a fourth action is ever added on one side only, this fails rather than silently
    emitting an empty `action` into a bundle that then verifies against nothing.
    """
    forward = {(gate, dec): action for action, (gate, dec, _) in engine_mod.AUDIT_MAP.items()}
    assert forward == REVIEW_TO_V1_ACTION
    assert len(forward) == len(engine_mod.AUDIT_MAP), "AUDIT_MAP is not injective"


# ── B: resume after interruption ──────────────────────────────────────────────────


async def test_resume_after_a_clean_stop_processes_only_the_remainder(maker):
    async with maker() as db:
        ids = [await _seed_complete(db) for _ in range(4)]
        saver = FakeSaver({str(s): {"evidence": EVIDENCE, "contradictions": []} for s in ids})

        first = await migrate_all(db, saver, limit=2)
        assert first.considered == 2
        assert await _count(db, MigrationLedger) == 2
        assert await _count(db, ResearchRun) == 2

    # A restarted process: new session, same database.
    async with maker() as db:
        second = await migrate_all(db, saver)
        assert second.considered == 2, "already-terminal runs must not be reprocessed"
        assert await _count(db, MigrationLedger) == 4
        assert await _count(db, ResearchRun) == 4
        assert await _count(db, Revision) == 4
        assert await _count(db, Evidence) == 8


async def test_resume_after_a_hard_interruption_loses_nothing_and_duplicates_nothing(maker):
    """Kill the migration mid-run; the interrupted run must be NOT_PROCESSED, not half-done.

    `KeyboardInterrupt` is deliberate: it is a `BaseException`, so the runner's
    `except Exception` does not catch it and the process really does die with an open
    transaction — which is what an operator pressing Ctrl-C produces.
    """
    async with maker() as db:
        ids = [await _seed_complete(db) for _ in range(4)]
    saver = FakeSaver({str(s): {"evidence": EVIDENCE, "contradictions": []} for s in ids})

    calls = {"n": 0}
    real = engine_mod.migrate_session

    async def interrupt_on_third(db, saver, session):
        calls["n"] += 1
        if calls["n"] == 3:
            raise KeyboardInterrupt("operator stopped the migration")
        return await real(db, saver, session)

    async with maker() as db:
        engine_mod_migrate = engine_mod.migrate_session
        try:
            import migration.runner as runner_mod

            runner_mod.migrate_session = interrupt_on_third
            with pytest.raises(KeyboardInterrupt):
                await migrate_all(db, saver)
        finally:
            runner_mod.migrate_session = engine_mod_migrate
        await db.rollback()

    async with maker() as db:
        # Two runs committed; the third died with its transaction open and therefore has no
        # ledger row at all — which is what NOT_PROCESSED means (M2E §8).
        assert await _count(db, MigrationLedger) == 2
        assert await _count(db, ResearchRun) == 2

        report = await migrate_all(db, saver)
        assert report.considered == 2, "the interrupted run and the untouched one"
        assert await _count(db, MigrationLedger) == 4
        assert await _count(db, ResearchRun) == 4
        assert await _count(db, Evidence) == 8, "no run was migrated twice"


# ── D: partial transaction failure, and retrying it ───────────────────────────────


async def _fail_after_evidence(monkeypatch):
    """Fault injection *after* the run, sources and evidence rows are inserted.

    Chosen because it is the shape that matters: a failure early enough to be trivially
    safe proves nothing. `claim_lines` runs once the revision is already in the transaction.
    """

    def boom(_report):
        raise RuntimeError("injected fault: claim extraction failed")

    monkeypatch.setattr(engine_mod.claim_rules, "claim_lines", boom)


async def test_a_failure_mid_transaction_leaves_no_v2_rows(db, monkeypatch):
    sid = await _seed_complete(db)
    saver = FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": []}})
    await _fail_after_evidence(monkeypatch)

    await migrate_all(db, saver)

    for model in (ResearchRun, Source, Evidence, Revision, Claim, ClaimEvidenceLink, Review):
        assert await _count(db, model) == 0, f"{model.__name__} survived a failed run"
    led = (await db.execute(select(MigrationLedger))).scalar_one()
    assert led.status == MigrationStatus.FAILED
    assert led.failure_category == "RuntimeError"
    assert "injected fault" in led.detail
    assert led.rows_written == 0
    assert led.v2_run_id is None, "nothing was written, so nothing may be pointed at"


async def test_retrying_a_failed_run_does_not_duplicate_child_rows(db, monkeypatch):
    sid = await _seed_complete(db)
    saver = FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": []}})

    await _fail_after_evidence(monkeypatch)
    await migrate_all(db, saver)
    assert (await db.execute(select(MigrationLedger))).scalar_one().status == MigrationStatus.FAILED

    monkeypatch.undo()
    await migrate_all(db, saver, retry_failed=True)

    led = (await db.execute(select(MigrationLedger))).scalar_one()
    assert led.status == MigrationStatus.MIGRATED
    assert led.attempt == 2, "the retry must be counted, not hidden"
    assert await _count(db, ResearchRun) == 1
    assert await _count(db, Evidence) == 2
    assert await _count(db, Claim) == 2
    assert await _count(db, Review) == 2

    # And a third pass changes nothing.
    await migrate_all(db, saver, retry_failed=True)
    assert await _count(db, Evidence) == 2
    assert await _count(db, MigrationLedger) == 1


async def test_a_failed_run_is_not_retried_without_being_asked(db, monkeypatch):
    sid = await _seed_complete(db)
    saver = FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": []}})
    await _fail_after_evidence(monkeypatch)
    await migrate_all(db, saver)
    monkeypatch.undo()

    report = await migrate_all(db, saver)  # no retry_failed
    assert report.considered == 0
    assert await _count(db, ResearchRun) == 0


# ── N: ledger completeness ────────────────────────────────────────────────────────


async def test_every_considered_session_has_exactly_one_terminal_outcome(db, monkeypatch):
    good = await _seed_complete(db)
    empty = await _seed_complete(db)
    missing = await _seed_complete(db)
    unreadable = await _seed_complete(db)
    orphan = await seed(db, sources=[])
    no_report = await seed(db, report=None)
    nothing_at_all = await seed(db, report=None)

    saver = FakeSaver(
        {
            str(good): {"evidence": EVIDENCE, "contradictions": []},
            str(empty): {"evidence": [], "contradictions": []},
            str(unreadable): FakeSaver.BOOM,
            str(orphan): {"evidence": EVIDENCE, "contradictions": []},
            str(no_report): {"evidence": EVIDENCE, "contradictions": []},
            str(nothing_at_all): {"evidence": [], "contradictions": []},
        }
    )
    report = await migrate_all(db, saver)

    sessions = (await db.execute(select(func.count()).select_from(Session))).scalar_one()
    assert report.considered == sessions == 7
    assert report.accounted == report.considered, "unexplained remainder"

    rows = {r.session_id: r for r in (await db.execute(select(MigrationLedger))).scalars()}
    assert len(rows) == 7, "one ledger row per considered session, no more and no less"
    assert all(r.status in TERMINAL for r in rows.values()), "a run left IN_PROGRESS"
    assert rows[good].status == MigrationStatus.MIGRATED
    assert rows[empty].status == MigrationStatus.EMPTY
    assert rows[missing].status == MigrationStatus.CHECKPOINT_MISSING
    assert rows[unreadable].status == MigrationStatus.READ_FAILURE
    assert rows[orphan].status == MigrationStatus.INCONSISTENT_V1
    assert rows[no_report].status == MigrationStatus.NO_REPORT

    # `status` is a single slot and this run has two findings at once: no checkpoint
    # evidence AND no report. The runner's documented precedence puts the checkpoint
    # outcome first, and neither fact is lost — both live in their own column.
    assert rows[nothing_at_all].status == MigrationStatus.EMPTY
    assert rows[nothing_at_all].evidence_outcome == "NONE_PRESENT"
    assert rows[nothing_at_all].revision_outcome == "NO_REPORT"


async def test_every_v2_run_has_a_ledger_record_and_the_reverse(db):
    for _ in range(3):
        await _seed_complete(db)
    sessions = (await db.execute(select(Session.id))).scalars().all()
    saver = FakeSaver({str(s): {"evidence": EVIDENCE, "contradictions": []} for s in sessions})
    await migrate_all(db, saver)

    runs = {str(r) for r in (await db.execute(select(ResearchRun.id))).scalars()}
    ledgered = {
        str(r.v2_run_id)
        for r in (await db.execute(select(MigrationLedger))).scalars()
        if r.v2_run_id is not None
    }
    assert runs, "vacuous otherwise"
    assert runs == ledgered, "a V2 run with no migration record, or the reverse"


async def test_a_v2_run_never_appears_without_rows_written(db, monkeypatch):
    """`v2_run_id` is set only when the transaction actually wrote something."""
    await _seed_complete(db)
    sid = (await db.execute(select(Session.id))).scalars().one()
    await _fail_after_evidence(monkeypatch)
    await migrate_all(db, FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": []}}))

    led = (await db.execute(select(MigrationLedger))).scalar_one()
    assert (led.v2_run_id is not None) == (led.rows_written > 0)
    assert await _count(db, ResearchRun) == 0


# ── M: coverage accounting across a mixed corpus ──────────────────────────────────


async def test_report_totals_reconcile_with_the_database(db):
    for _ in range(3):
        await _seed_complete(db)
    await seed(db, sources=[])  # one refusal
    sessions = (await db.execute(select(Session.id))).scalars().all()
    saver = FakeSaver({str(s): {"evidence": EVIDENCE, "contradictions": []} for s in sessions})

    report = await migrate_all(db, saver)

    assert report.rows_by_table["research_runs"] == await _count(db, ResearchRun)
    assert report.rows_by_table["evidence"] == await _count(db, Evidence)
    assert report.rows_by_table["revisions"] == await _count(db, Revision)
    assert report.rows_by_table["claims"] == await _count(db, Claim)
    assert report.rows_by_table["reviews"] == await _count(db, Review)
    assert len(report.durations_ms) == report.considered


# ── C (again): the tri-state against a REAL LangGraph saver ───────────────────────
#
# `test_migration_engine.py` proves the tri-state against `FakeSaver`, which is fine for
# the classification logic and useless for the question "does a real checkpointer behave
# the way the fake does?". It does not, and the difference matters: corrupting a real
# saver's stored blob produces a value that *deserialises* — to the integer 0 — rather
# than raising. The reader treated that as an empty checkpoint until the M2E-2 dry run
# ran it against the real thing.


@pytest.fixture
async def real_saver(tmp_path):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        yield saver


async def test_the_tri_state_holds_against_a_real_langgraph_saver(real_saver):
    await put_checkpoint(real_saver, "full", {"evidence": EVIDENCE, "contradictions": []})
    await put_checkpoint(real_saver, "empty", {"evidence": [], "contradictions": []})
    await put_checkpoint(
        real_saver, "broken", {"evidence": EVIDENCE, "contradictions": []}, corrupt=True
    )

    full = await read_checkpoint(real_saver, "full")
    assert full.outcome is CheckpointOutcome.READ and len(full.evidence) == 2

    empty = await read_checkpoint(real_saver, "empty")
    assert empty.outcome is CheckpointOutcome.READ and empty.evidence == []

    assert (await read_checkpoint(real_saver, "absent")).outcome is CheckpointOutcome.MISSING

    broken = await read_checkpoint(real_saver, "broken")
    assert broken.outcome is CheckpointOutcome.UNREADABLE, (
        "a corrupt blob that happens to deserialise must not read as empty"
    )
    assert broken.error and "not a mapping" in broken.error


async def test_a_corrupt_checkpoint_reaches_the_ledger_as_READ_FAILURE(db, real_saver):
    """End to end: corruption must not be recorded as a run that gathered nothing."""
    sid = await _seed_complete(db)
    await put_checkpoint(
        real_saver, str(sid), {"evidence": EVIDENCE, "contradictions": []}, corrupt=True
    )

    await migrate_all(db, real_saver)

    led = (await db.execute(select(MigrationLedger))).scalar_one()
    assert led.status == MigrationStatus.READ_FAILURE
    assert led.evidence_outcome == "CHECKPOINT_UNREADABLE"
    assert led.status != MigrationStatus.EMPTY


async def test_a_checkpoint_with_no_channel_values_is_unreadable_not_empty(real_saver):
    """A format this code does not understand is not a run with no evidence."""
    await put_checkpoint(real_saver, "odd", {"evidence": [], "contradictions": []})
    await real_saver.conn.execute(
        "UPDATE checkpoints SET checkpoint = ? WHERE thread_id = 'odd'",
        (real_saver.serde.dumps_typed({"v": 1, "id": "x"})[1],),
    )
    await real_saver.conn.commit()
    read = await read_checkpoint(real_saver, "odd")
    assert read.outcome is CheckpointOutcome.UNREADABLE
    assert "channel_values" in (read.error or "")


async def test_no_known_limitation_silently_covers_an_unrelated_field():
    """`KNOWN_LOSSY` must name only fields V2 genuinely cannot store.

    A broad entry — say `{"report"}` — would turn a real migration defect into an expected
    limitation. Pinning the vocabulary means widening it is a deliberate, reviewable act.
    """
    allowed = {"contradictions", "sources"}
    for fields in KNOWN_LOSSY:
        assert set(fields) <= allowed, f"{sorted(fields)} is not a known V2 storage gap"
