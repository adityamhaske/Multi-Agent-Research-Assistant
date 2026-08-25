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

import pathlib

import pytest
from sqlalchemy import func, select, update

from app.models.research import Contradiction, Evidence, ResearchRun, Source
from app.models.review import Review
from app.models.revision import Claim, ClaimEvidenceLink, Revision
from app.models.session import Session, SessionStatus
from migration import dryrun, provenance
from migration import engine as engine_mod
from migration.bundle_equivalence import (
    KNOWN_LOSSY,
    REVIEW_TO_V1_ACTION,
    BundleVerdict,
    assemble_v2,
    check_validity,
    compare_run,
    validate_run,
)
from migration.checkpoint import CheckpointOutcome, read_checkpoint
from migration.dryrun import put_checkpoint
from migration.ledger import TERMINAL, MigrationLedger, MigrationStatus
from migration.runner import migrate_all
from research_engine.bundle import content_hash
from research_engine.graph import _number_sources
from tests.migration_support import (
    CONTRADICTIONS,
    EVIDENCE,
    EVIDENCE_NO_URL,
    PLAN,
    REPORT,
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


async def test_contradictions_round_trip_at_the_granularity_v1_observed(db):
    """All seven V1 fields survive, and the pair is anchored where V1 anchored it.

    V1's detector is shown `{source_url: [snippets]}` and never sees an evidence row, so
    the pair is source-level. Until M2F the schema demanded evidence references V1 never
    recorded, which forced the migration to write `NOT_RUN` about a detector that had run.
    """
    sid = await _seed_complete(db)
    saver = FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": CONTRADICTIONS}})
    await migrate_all(db, saver)

    row = (await db.execute(select(Contradiction))).scalar_one()
    assert row.detection_state == "DETECTED"
    assert row.source_a_id is not None and row.source_b_id is not None
    assert row.nature and row.quote_a and row.summary_a

    session = (await db.execute(select(Session).where(Session.id == sid))).scalar_one()
    result = await compare_run(db, saver, session)
    assert result.verdict is BundleVerdict.BUNDLE_EQUIVALENT, (
        result.differing_fields,
        result.detail,
    )


async def test_an_ambiguous_quotation_does_not_become_an_evidence_reference(db):
    """Two evidence rows from one source carrying the same text: the refinement must not pick.

    Choosing "the first" would assert a link the detector never made. The pair stays
    DETECTED — V1 did detect it — with the evidence anchors NULL.
    """
    duplicated = [
        {**EVIDENCE[0], "task_id": 1},
        {**EVIDENCE[0], "task_id": 2},
        EVIDENCE[1],
    ]
    sid = await _seed_complete(db, sources=_number_sources(duplicated)[0])
    saver = FakeSaver({str(sid): {"evidence": duplicated, "contradictions": CONTRADICTIONS}})
    await migrate_all(db, saver)

    row = (await db.execute(select(Contradiction))).scalar_one()
    assert row.detection_state == "DETECTED", "the detector did run and did find a pair"
    assert row.source_a_id is not None, "the source anchor is what V1 guarantees"
    assert row.evidence_a_id is None, "an ambiguous quotation must not resolve"
    assert row.evidence_b_id is None, "ck_contra_refine: half a pair is not a pair"


async def test_a_unique_quotation_does_refine_to_its_evidence_row(db):
    """The refinement is allowed — it is only the guessing that is not."""
    sid = await _seed_complete(db)
    saver = FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": CONTRADICTIONS}})
    await migrate_all(db, saver)

    row = (await db.execute(select(Contradiction))).scalar_one()
    # `snippet_a` is the exact text of evidence[0]; `snippet_b` is empty, so side B cannot
    # resolve — and ck_contra_refine therefore clears side A too.
    assert row.quote_a == EVIDENCE[0]["snippet"]
    assert (row.evidence_a_id is None) == (row.evidence_b_id is None)


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"status": SessionStatus.FAILED}, {"V1_STATUS_NOT_COMPLETED"}),
        ({"report": None}, {"V1_NO_REPORT"}),
        (
            # Both are true at once, and the point of a reason *set* is that both are said.
            {"status": SessionStatus.FAILED, "report": None},
            {"V1_STATUS_NOT_COMPLETED", "V1_NO_REPORT"},
        ),
    ],
)
async def test_uncomparable_runs_report_every_applicable_v1_reason(db, kwargs, expected):
    sid = await seed(db, **kwargs)
    saver = FakeSaver({str(sid): {"evidence": [], "contradictions": []}})
    session = (await db.execute(select(Session).where(Session.id == sid))).scalar_one()
    result = await compare_run(db, saver, session)
    assert result.verdict is BundleVerdict.NOT_COMPARABLE
    assert set(result.v1_reasons) == expected
    assert result.v2_reasons, "the V2 axis must always be stated too, never left blank"


async def test_a_missing_checkpoint_is_not_comparable_rather_than_empty(db):
    """The tri-state again, one level up: no snapshot ≠ a bundle with no evidence."""
    sid = await _seed_complete(db)
    session = (await db.execute(select(Session).where(Session.id == sid))).scalar_one()
    result = await compare_run(db, FakeSaver({}), session)
    assert result.verdict is BundleVerdict.NOT_COMPARABLE
    assert result.v1_reasons == ["V1_CHECKPOINT_MISSING"]


async def test_a_refused_run_reports_V2_RUN_ABSENT_and_not_only_a_v1_property(db):
    """The masking defect, pinned.

    Before the two-axis form, this run reported `V1_STATUS_FAILED` — a property of V1 —
    while the material fact was that the migration had refused it. 12 of the 48
    not-comparable runs in the M2E-2 corpus were in exactly this position (M2F §9.2).
    """
    sid = await seed(db, status=SessionStatus.FAILED, report=None, sources=[])
    saver = FakeSaver({str(sid): {"evidence": EVIDENCE_NO_URL, "contradictions": []}})
    await migrate_all(db, saver)
    assert (
        await db.execute(select(MigrationLedger))
    ).scalar_one().status == MigrationStatus.INCONSISTENT_V1

    session = (await db.execute(select(Session).where(Session.id == sid))).scalar_one()
    result = await compare_run(db, saver, session)
    assert result.verdict is BundleVerdict.NOT_COMPARABLE
    assert result.v2_reasons == ["V2_RUN_ABSENT"], "the migration outcome must not be masked"
    assert set(result.v1_reasons) == {"V1_STATUS_NOT_COMPLETED", "V1_NO_REPORT"}


async def test_no_not_comparable_run_lands_in_an_empty_bucket(db):
    """Every axis always names at least one reason — there is no 'other'."""
    for kwargs in ({"status": SessionStatus.FAILED}, {"report": None}, {"sources": []}):
        sid = await seed(db, **kwargs)
        session = (await db.execute(select(Session).where(Session.id == sid))).scalar_one()
        result = await compare_run(db, FakeSaver({}), session)
        assert result.v1_reasons and result.v2_reasons, (kwargs, result)


async def test_the_audit_action_map_is_invertible(db):
    """The V2 approval chain is rebuilt by inverting `engine.AUDIT_MAP`.

    If a fourth action is ever added on one side only, this fails rather than silently
    emitting an empty `action` into a bundle that then verifies against nothing.
    """
    forward = {(gate, dec): action for action, (gate, dec, _) in engine_mod.AUDIT_MAP.items()}
    assert len(forward) == len(engine_mod.AUDIT_MAP), "AUDIT_MAP is not injective"
    # A subset, not equality: the shared map also covers decisions only a V2-NATIVE run can
    # reach (REJECTED, plan rework), which V1 had no action for. What must hold is that
    # every V1 action round-trips and that no two V2 pairs share a serialized action.
    assert forward.items() <= REVIEW_TO_V1_ACTION.items()
    assert len(set(REVIEW_TO_V1_ACTION.values())) == len(REVIEW_TO_V1_ACTION), (
        "two V2 decisions serialize to one action — the chain is no longer comparable"
    )


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
    plan_only = await seed(
        db, status=SessionStatus.AWAITING_PLAN, report=None, audits=[("plan_approved", "a" * 64)]
    )

    saver = FakeSaver(
        {
            str(good): {"evidence": EVIDENCE, "contradictions": []},
            str(empty): {"evidence": [], "contradictions": []},
            str(unreadable): FakeSaver.BOOM,
            str(orphan): {"evidence": EVIDENCE_NO_URL, "contradictions": []},
            str(plan_only): {"evidence": [], "contradictions": []},
            str(no_report): {"evidence": EVIDENCE, "contradictions": []},
            str(nothing_at_all): {"evidence": [], "contradictions": []},
        }
    )
    report = await migrate_all(db, saver)

    sessions = (await db.execute(select(func.count()).select_from(Session))).scalar_one()
    assert report.considered == sessions == 8
    assert report.accounted == report.considered, "unexplained remainder"

    rows = {r.session_id: r for r in (await db.execute(select(MigrationLedger))).scalars()}
    assert len(rows) == 8, "one ledger row per considered session, no more and no less"
    assert all(r.status in TERMINAL for r in rows.values()), "a run left IN_PROGRESS"
    assert rows[good].status == MigrationStatus.MIGRATED
    assert rows[empty].status == MigrationStatus.EMPTY
    assert rows[missing].status == MigrationStatus.CHECKPOINT_MISSING
    assert rows[unreadable].status == MigrationStatus.READ_FAILURE
    assert rows[orphan].status == MigrationStatus.INCONSISTENT_V1
    assert rows[plan_only].failure_category == "PLAN_REVIEW_WITHOUT_PLAN"
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


# ── Gate B: internal bundle validity, kept apart from fidelity ───────────────────
#
# M2E-2 reported 124 runs BUNDLE_EQUIVALENT and would have failed `verify_bundle` on every
# one of them, because the corpus used placeholder approval hashes. "Says the same thing"
# and "is internally valid" are different properties, and the whole point of these tests is
# that neither implies the other.


def _real_audits(report: str) -> list[tuple[str, str]]:
    """Approval hashes that actually bind to the report, as V1's gate writes them."""
    return [
        ("plan_approved", content_hash("the plan")),
        ("approved", content_hash(report)),
    ]


async def test_a_migrated_run_produces_a_bundle_that_verifies(db):
    sid = await _seed_complete(db, audits=_real_audits(REPORT))
    saver = FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": []}})
    await migrate_all(db, saver)
    session = (await db.execute(select(Session).where(Session.id == sid))).scalar_one()

    result = await validate_run(db, saver, session)
    assert result.fidelity.verdict is BundleVerdict.BUNDLE_EQUIVALENT
    assert result.validity_v1.passed is True, result.validity_v1.failed_checks
    assert result.validity_v2.passed is True, result.validity_v2.failed_checks


async def test_a_bundle_can_be_equivalent_and_invalid(db):
    """The distinction the three gates exist to preserve, as a live example.

    Placeholder approval hashes — exactly what the M2E-2 corpus used — make both bundles
    fail `approval_chain` while the two representations remain identical.
    """
    sid = await _seed_complete(db)  # the default fixture's hashes are placeholders
    saver = FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": []}})
    await migrate_all(db, saver)
    session = (await db.execute(select(Session).where(Session.id == sid))).scalar_one()

    result = await validate_run(db, saver, session)
    assert result.fidelity.verdict is BundleVerdict.BUNDLE_EQUIVALENT
    assert result.validity_v1.passed is False
    assert result.validity_v2.passed is False
    assert "approval_chain" in result.validity_v2.failed_checks
    # Both sides fail identically: V1 was already unverifiable and V2 inherited it. That is
    # not a migration defect, and must not be reported as one.
    assert result.validity_v1.failed_checks == result.validity_v2.failed_checks


async def test_an_unassembled_bundle_is_not_measured_rather_than_failed(db):
    """`passed is None` is the unmeasured-vs-zero rule applied to Gate B."""
    sid = await seed(db, report=None)
    session = (await db.execute(select(Session).where(Session.id == sid))).scalar_one()
    v1, v2 = await check_validity(db, FakeSaver({}), session)
    for side in (v1, v2):
        assert side.assembled is False
        assert side.passed is None, "a bundle that could not be built has not failed"
        assert side.failed_checks == []


async def test_no_v2_bundle_is_emitted_when_the_evidence_was_unreadable(db, real_saver):
    """Invariant I10: a read path must not present evidence the migration could not read.

    Found by measurement in F1 — before this, V1 refused to assemble such a run while V2
    emitted a bundle whose every citation resolved to nothing and which failed its own
    `claim_evidence_linkage` check.
    """
    sid = await _seed_complete(db, audits=_real_audits(REPORT))
    await put_checkpoint(
        real_saver, str(sid), {"evidence": EVIDENCE, "contradictions": []}, corrupt=True
    )
    await migrate_all(db, real_saver)
    assert await _count(db, ResearchRun) == 1, "the run itself still migrates"

    manifest, why = await assemble_v2(db, sid)
    assert manifest is None
    assert why == "V2_EVIDENCE_UNAVAILABLE"


async def test_a_v2_native_run_is_not_gated_on_a_ledger_row(db):
    """Absence of a ledger row means V2-native: its evidence rows ARE the record.

    Without this the read contract would be inverted — every unmigrated run would look
    like one whose evidence could not be read.
    """
    sid = await _seed_complete(db, audits=_real_audits(REPORT))
    saver = FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": []}})
    await migrate_all(db, saver)
    await db.execute(MigrationLedger.__table__.delete())
    await db.commit()

    manifest, why = await assemble_v2(db, sid)
    assert manifest is not None, why


# ── I4: a PLAN approval must never serialize as a report approval ────────────────


async def test_a_plan_approval_never_serializes_as_approved(db):
    """`verify_bundle` treats `action == "approved"` as report authorization.

    It rejects `plan_approved` today only because V1 happens to use a distinct string —
    string inequality, not design. If a V2 assembler ever mapped an APPROVED review to
    `"approved"` regardless of gate, a plan approval would satisfy the verifier's
    load-bearing check, in a file no database constraint reaches (M2F Amendment §5.3).
    """
    assert REVIEW_TO_V1_ACTION[("PLAN", "APPROVED")] == "plan_approved"
    assert REVIEW_TO_V1_ACTION[("REPORT", "APPROVED")] == "approved"

    sid = await _seed_complete(db, audits=_real_audits(REPORT))
    saver = FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": []}})
    await migrate_all(db, saver)

    manifest, _ = await assemble_v2(db, sid)
    actions = [a.action for a in manifest.approval_chain]
    assert "plan_approved" in actions
    assert actions.count("approved") == 1, "the plan approval must not become a second one"


# ── Gate C: historical non-fabrication ───────────────────────────────────────────


def test_every_column_the_engine_writes_has_a_declared_provenance():
    """The structural half of Gate C. Static, so a column in an unexercised branch counts."""
    assert provenance.undeclared_columns() == []


def test_no_provenance_declaration_describes_a_column_that_is_gone():
    """The map must not become a description of a past version of the engine."""
    assert provenance.stale_declarations() == []


def test_an_undeclared_column_is_detected(tmp_path):
    """The plant, run against a copy so the real engine is never edited."""
    source = pathlib.Path(provenance.ENGINE_PATH).read_text()
    planted = source.replace(
        "                    content_hash=_sha(snippet),",
        "                    content_hash=_sha(snippet),\n"
        "                    made_up_column=1,  # PLANT: an undeclared write",
        1,
    )
    assert planted != source, "the plant did not apply — the anchor moved"
    path = tmp_path / "engine_planted.py"
    path.write_text(planted)
    assert provenance.undeclared_columns(path) == ["evidence.made_up_column"]


def test_every_declared_constant_is_backed_by_a_reason():
    """A constant without a stated reason is an unexamined default, not a decision."""
    for table, columns in provenance.PROVENANCE.items():
        for column, prov in columns.items():
            if prov.kind in (provenance.Kind.CONST, provenance.Kind.NULL):
                assert prov.reason.strip(), f"{table}.{column} has no reason"


async def test_declared_constants_hold_in_the_migrated_rows(db):
    """The runtime half. The map could say UNCHECKED while the engine writes ATTESTED."""
    sid = await _seed_complete(db, audits=_real_audits(REPORT))
    saver = FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": CONTRADICTIONS}})
    await migrate_all(db, saver)
    assert await _count(db, Evidence) > 0, "vacuous otherwise"
    assert await provenance.constant_violations(db) == []


# ── M8: the dry-run corpus itself is a fixture, and fixtures rot silently ────────
#
# M2E-2 measured bundle equivalence on 124 runs whose approval hashes were placeholders,
# so every one of those bundles would have failed `verify_bundle`. The corpus now uses real
# digests — and these tests exist because reverting that change broke nothing: the rest of
# the suite uses `tests/migration_support.py`, and the dry-run corpus is only exercised when
# someone runs the dry run by hand.


def test_the_dry_run_corpus_binds_its_approvals_to_its_reports():
    """An `approved` entry must hash the report it approved, or it authorizes nothing."""
    checked = 0
    for spec in (dryrun.build_shape(shape.name, i) for i, shape in enumerate(dryrun.SHAPES)):
        approvals = [h for action, h in spec["audits"] if action == "approved"]
        if not approvals:
            continue
        assert spec["report"], f"{spec['shape']} approves a report it does not have"
        assert approvals == [content_hash(spec["report"])], spec["shape"]
        checked += 1
    assert checked >= 5, "too few shapes carry an approval for this to mean anything"


def test_a_rework_request_does_not_hash_the_report_that_shipped():
    """The rework was asked for against an earlier draft; only the approval binds."""
    spec = dryrun.build_shape("reworked", 0)
    reworks = [h for action, h in spec["audits"] if action == "rework_requested"]
    assert reworks and reworks[0] != content_hash(spec["report"])


async def test_equivalent_corpus_bundles_are_valid_on_both_sides(maker, real_saver):
    """Acceptance criterion G4, as a test rather than only as a dry-run check.

    Gate A and Gate B are independent, so `BUNDLE_EQUIVALENT` never implies validity — but
    for a run where both sides assemble and V1 itself verifies, the migration must not have
    produced something that does not.
    """
    corpus = [dryrun.build_shape(shape.name, i) for i, shape in enumerate(dryrun.SHAPES)]
    async with maker() as db:
        await dryrun.seed_corpus(db, real_saver, corpus)
        await migrate_all(db, real_saver)

        equivalent = 0
        for sid in (await db.execute(select(Session.id))).scalars().all():
            session = (await db.execute(select(Session).where(Session.id == sid))).scalar_one()
            result = await validate_run(db, real_saver, session)
            if result.fidelity.verdict is not BundleVerdict.BUNDLE_EQUIVALENT:
                continue
            equivalent += 1
            assert result.validity_v1.passed is True, (
                sid,
                result.validity_v1.failed_checks,
            )
            assert result.validity_v2.passed is True, (
                sid,
                result.validity_v2.failed_checks,
            )
        assert equivalent >= 4, f"only {equivalent} equivalent runs — the assertion is thin"


async def test_the_migration_never_invalidates_a_bundle_v1_could_verify(maker, real_saver):
    """The one Gate B pairing that IS a migration defect: V1 valid, V2 invalid."""
    corpus = [dryrun.build_shape(shape.name, i) for i, shape in enumerate(dryrun.SHAPES)]
    async with maker() as db:
        await dryrun.seed_corpus(db, real_saver, corpus)
        await migrate_all(db, real_saver)

        broken = []
        for sid in (await db.execute(select(Session.id))).scalars().all():
            session = (await db.execute(select(Session).where(Session.id == sid))).scalar_one()
            v1, v2 = await check_validity(db, real_saver, session)
            if v1.passed is True and v2.passed is False:
                broken.append((str(sid), v2.failed_checks))
        assert broken == [], f"the migration broke {len(broken)} verifiable bundle(s)"


# ── The four gaps the F2/F3 plant sweep found silent ─────────────────────────────


async def test_the_bundle_chain_follows_decision_order_not_the_clock(db):
    """`reviews.sequence` is the order, and the bundle must read it.

    The fixture's later `audit_log` row carries an EARLIER timestamp, so a chain ordered by
    `created_at` comes out reversed. V1 guarantees neither distinctness nor monotonicity on
    that column — only `audit_log.id` is monotonic — which is why S5 exists.
    """
    sid = await _seed_complete(
        db,
        audits=[("plan_approved", content_hash("plan")), ("approved", content_hash(REPORT))],
        descending_audit_times=True,
    )
    saver = FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": []}})
    await migrate_all(db, saver)

    rows = (await db.execute(select(Review).order_by(Review.sequence))).scalars().all()
    assert [r.gate for r in rows] == ["PLAN", "REPORT"]
    assert rows[0].created_at > rows[1].created_at, "the fixture must invert the clock"

    manifest, _ = await assemble_v2(db, sid)
    assert [a.action for a in manifest.approval_chain] == ["plan_approved", "approved"]


async def test_an_ambiguous_quotation_leaves_both_anchors_null(db):
    """Both sides quoted, side A ambiguous: the refinement must decline, not pick.

    Distinct from the all-or-nothing rule — here side B resolves perfectly, so only the
    unique-match requirement can stop side A from guessing.
    """
    duplicated = [
        {**EVIDENCE[0], "task_id": 1},
        {**EVIDENCE[0], "task_id": 2},
        {**EVIDENCE[1], "snippet": "A distinct passage from source b."},
    ]
    pair = [
        {
            "claim_a": "a",
            "snippet_a": EVIDENCE[0]["snippet"],
            "source_a": "https://e.org/a",
            "claim_b": "b",
            "snippet_b": "A distinct passage from source b.",
            "source_b": "https://e.org/b",
            "nature": "n",
        }
    ]
    sid = await _seed_complete(db, sources=_number_sources(duplicated)[0])
    await migrate_all(db, FakeSaver({str(sid): {"evidence": duplicated, "contradictions": pair}}))

    row = (await db.execute(select(Contradiction))).scalar_one()
    assert row.detection_state == "DETECTED", "the sources resolve, so the pair is real"
    assert row.evidence_a_id is None, "two rows carry that quotation — it must not pick one"
    assert row.evidence_b_id is None, "and half a resolved pair is not a pair"


async def test_a_pair_naming_an_unknown_source_is_not_DETECTED(db):
    """`DETECTED` requires both source anchors. An unresolvable side is not a detection."""
    pair = [
        {
            "claim_a": "a",
            "snippet_a": EVIDENCE[0]["snippet"],
            "source_a": "https://e.org/a",
            "claim_b": "b",
            "snippet_b": "x",
            "source_b": "https://not-in-this-run.invalid/z",
            "nature": "n",
        }
    ]
    sid = await _seed_complete(db)
    await migrate_all(db, FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": pair}}))

    row = (await db.execute(select(Contradiction))).scalar_one()
    assert row.detection_state == "NOT_RUN"
    assert row.source_a_id is None and row.source_b_id is None
    # The quotations and the reason survive even though the pair could not be anchored:
    # dropping them would lose a V1 fact to make a constraint pass.
    assert row.quote_a and row.nature and row.summary_a
