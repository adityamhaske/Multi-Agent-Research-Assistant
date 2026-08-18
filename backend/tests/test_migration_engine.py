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

import pytest
from sqlalchemy import func, select

from app.models.audit_log import AuditLog
from app.models.research import Contradiction, Evidence, ResearchPlan, ResearchRun, Source
from app.models.review import Review
from app.models.revision import Claim, ClaimEvidenceLink, Revision
from app.models.session import SessionStatus
from migration.checkpoint import CheckpointOutcome, read_checkpoint
from migration.ledger import MigrationLedger, MigrationStatus
from migration.runner import migrate_all
from tests.migration_support import (
    CONTRADICTIONS,
    EVIDENCE,
    EVIDENCE_NO_URL,
    PLAN,
    FakeSaver,
    open_db,
    seed,
)


@pytest.fixture
async def db(tmp_path):
    """A disposable SQLite database. Explicitly not the production DSN."""
    async with open_db(tmp_path / "m2e.sqlite") as maker, maker() as session:
        yield session


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


async def test_a_plan_approval_without_a_report_migrates_against_the_plan(db):
    """`submit_plan` runs at AWAITING_PLAN, before any draft exists (verified in code).

    A plan approval with no report is therefore normal V1 behaviour. Its subject is the
    PLAN version, and since M2F/S1 that is representable — with `revision_id` NULL and no
    revision fabricated to hold it.
    """
    sid = await seed(
        db,
        status=SessionStatus.AWAITING_PLAN,
        report=None,
        plan=PLAN,
        audits=[("plan_approved", "a" * 64)],
    )
    await migrate_all(db, FakeSaver({str(sid): {"evidence": [], "contradictions": []}}))

    review = (await db.execute(select(Review))).scalar_one()
    assert review.gate == "PLAN"
    assert review.decision == "APPROVED"
    assert review.revision_id is None, "no revision may be fabricated to hold a plan review"
    assert review.plan_version_id is not None
    assert review.run_id == sid
    assert await _count(db, Revision) == 0


async def test_a_plan_approval_with_no_plan_is_still_refused(db):
    """There is nothing to point `plan_version_id` at, and a plan version is not invented."""
    sid = await seed(
        db, status=SessionStatus.AWAITING_PLAN, report=None, audits=[("plan_approved", "a" * 64)]
    )
    await migrate_all(db, FakeSaver({str(sid): {"evidence": [], "contradictions": []}}))
    led = (await db.execute(select(MigrationLedger))).scalar_one()
    assert led.status == MigrationStatus.INCONSISTENT_V1
    assert led.failure_category == "PLAN_REVIEW_WITHOUT_PLAN"
    assert await _count(db, ResearchRun) == 0
    assert (await db.execute(select(func.count()).select_from(AuditLog))).scalar_one() == 1


async def test_a_report_review_without_a_report_is_still_refused(db):
    """Not merely unrepresentable — incoherent. The V1 gate requires a draft to exist."""
    sid = await seed(db, status=SessionStatus.FAILED, report=None, audits=[("approved", "a" * 64)])
    await migrate_all(db, FakeSaver({str(sid): {"evidence": [], "contradictions": []}}))
    led = (await db.execute(select(MigrationLedger))).scalar_one()
    assert led.failure_category == "REVIEW_WITHOUT_REVISION"
    assert await _count(db, Revision) == 0


async def test_a_source_is_recovered_from_the_evidence_that_names_it(db):
    """`EvidenceChunk.source_url` is a required V1 field — recovery, not synthesis.

    A run that failed before the synthesizer has no `sessions.sources`, but the executor
    still recorded where each snippet came from. The source is created with NO citation
    index, because the number is the synthesizer's and it never ran.
    """
    sid = await seed(db, status=SessionStatus.FAILED, report=None, sources=None)
    await migrate_all(db, FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": []}}))

    led = (await db.execute(select(MigrationLedger))).scalar_one()
    assert led.status != MigrationStatus.INCONSISTENT_V1, led.failure_category
    sources = (await db.execute(select(Source))).scalars().all()
    assert len(sources) == 2
    assert all(s.citation_index is None for s in sources), "no index may be generated"
    assert {s.url for s in sources} == {"https://e.org/a", "https://e.org/b"}
    assert await _count(db, Evidence) == 2


async def test_a_recovered_source_and_a_snapshot_source_are_one_row(db):
    """Both are keyed on the normalized URL, so the same source cannot duplicate."""
    sid = await seed(db)  # snapshot holds both URLs; evidence names the same two
    await migrate_all(db, FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": []}}))
    assert await _count(db, Source) == 2


async def test_evidence_with_no_url_at_all_is_classified_not_invented(db):
    """The one source case with no identity anywhere in V1."""
    sid = await seed(db, sources=None)
    await migrate_all(
        db, FakeSaver({str(sid): {"evidence": EVIDENCE_NO_URL, "contradictions": []}})
    )
    led = (await db.execute(select(MigrationLedger))).scalar_one()
    assert led.status == MigrationStatus.INCONSISTENT_V1
    assert led.failure_category == "EVIDENCE_SOURCE_UNRESOLVED"
    assert await _count(db, Source) == 0, "no synthetic source may be invented"
    assert await _count(db, Evidence) == 0


# ── F: transaction boundary ──────────────────────────────────────────────────────


async def test_a_refused_run_leaves_no_partial_v2_rows(db):
    """The run inserts research_runs/sources first, then hits the refusal — all must roll back."""
    sid = await seed(db, sources=None)
    await migrate_all(
        db, FakeSaver({str(sid): {"evidence": EVIDENCE_NO_URL, "contradictions": []}})
    )
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
            str(bad): {"evidence": EVIDENCE_NO_URL, "contradictions": []},
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


# ── P3: deterministic CHILD identity, independent of the run's primary key ───────
#
# The accurate statement of the idempotency design, which the M2E-1 plant got wrong:
#
#   `research_runs.id = session.id` is the current TOP-LEVEL idempotency boundary.
#   uuid5 child ids are deterministic DEFENCE IN DEPTH.
#
# A plant that swapped uuid5 for uuid4 therefore did not break end-to-end migration —
# the run row collided first and the whole transaction rolled back, hiding the change.
# The test below removes that shield: two disjoint target databases share no primary key
# at all, so the only thing that can make the child ids agree is the derivation being a
# pure function of (V1 source, mapping).

CHILD_ID_COLUMNS = {
    "research_plans": ResearchPlan.id,
    "sources": Source.id,
    "evidence": Evidence.id,
    "contradictions": Contradiction.id,
    "revisions": Revision.id,
    "claims": Claim.id,
    "claim_evidence_links": ClaimEvidenceLink.id,
    "reviews": Review.id,
}


async def _child_ids(db) -> dict[str, list[str]]:
    return {
        name: sorted(str(v) for v in (await db.execute(select(col))).scalars())
        for name, col in CHILD_ID_COLUMNS.items()
    }


async def test_child_identity_is_deterministic_across_independent_databases(tmp_path):
    """Same V1 source + same mapping → same child identity, with no PK to collide on.

    Two disposable databases are migrated from a byte-identical V1 fixture. Neither can
    see the other, so `research_runs.id = session.id` cannot mask a random id: if any
    child id were freshly generated, the two sets would differ.
    """
    ids = (uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    sid = ids[2]
    saver = FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": CONTRADICTIONS}})

    async def migrate_into(path):
        async with open_db(path) as maker, maker() as target:
            await seed(target, ids=ids, audits=[("approved", "b" * 64)], plan=PLAN)
            report = await migrate_all(target, saver)
            assert report.by_status == {str(MigrationStatus.MIGRATED): 1}, report.by_status
            return await _child_ids(target)

    first = await migrate_into(tmp_path / "target_a.sqlite")
    second = await migrate_into(tmp_path / "target_b.sqlite")

    # Vacuity guard: every child table must actually have rows, or "the ids match" is
    # a statement about two empty sets.
    for table, rows in first.items():
        assert rows, f"{table} produced no rows — the comparison below would be vacuous"

    assert first == second, "child ids are not a function of the V1 source"


async def test_child_identity_survives_a_rebuilt_target(db, tmp_path):
    """The same property stated the other way: rebuild the target, get the same children.

    Deletes every V2 row *and* the ledger — so nothing is left to collide with — and
    migrates again. Random ids would produce a disjoint set; deterministic ids reproduce
    the first result exactly.
    """
    sid = await seed(db, audits=[("approved", "c" * 64)], plan=PLAN)
    saver = FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": CONTRADICTIONS}})
    await migrate_all(db, saver)
    before = await _child_ids(db)
    assert all(before.values())

    # Children first, then the run: nothing remains for the second pass to collide on.
    for model in (
        ClaimEvidenceLink,
        Claim,
        Review,
        Revision,
        Contradiction,
        Evidence,
        Source,
        ResearchPlan,
        ResearchRun,
        MigrationLedger,
    ):
        await db.execute(model.__table__.delete())
    await db.commit()
    assert await _count(db, ResearchRun) == 0

    await migrate_all(db, saver)
    assert await _child_ids(db) == before


# ── The remaining refusals: audit rows V2 cannot represent ───────────────────────
#
# Added in M2E-2 after a planted "accept a duplicate approval" violation survived the
# suite. The partial unique index `uq_review_approval` would have caught it at the
# database, but as an IntegrityError — classifying an inconsistent V1 row as a *retryable*
# FAILED, which a retry would then hit forever. The engine's own refusal is what makes it
# INCONSISTENT_V1, and that is what these pin.


async def test_two_approvals_for_one_revision_are_refused_not_retried(db):
    """`uq_review_approval` allows one approving REPORT review per revision (M2E §6)."""
    sid = await seed(db, audits=[("approved", "a" * 64), ("approved", "b" * 64)])
    await migrate_all(db, FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": []}}))

    led = (await db.execute(select(MigrationLedger))).scalar_one()
    assert led.status == MigrationStatus.INCONSISTENT_V1, "a retry would fail identically forever"
    assert led.failure_category == "DUPLICATE_APPROVAL"
    assert await _count(db, Review) == 0
    assert await _count(db, ResearchRun) == 0


async def test_a_malformed_draft_hash_is_refused_not_padded(db):
    sid = await seed(db, audits=[("approved", "tooshort")])
    await migrate_all(db, FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": []}}))

    led = (await db.execute(select(MigrationLedger))).scalar_one()
    assert led.status == MigrationStatus.INCONSISTENT_V1
    assert led.failure_category == "MALFORMED_DRAFT_HASH"
    assert await _count(db, Review) == 0


async def test_an_unknown_audit_action_stops_the_run_rather_than_being_skipped(db):
    """A fourth V1 action would otherwise migrate as an approval-shaped hole."""
    sid = await seed(db, audits=[("archived", "a" * 64)])
    await migrate_all(db, FakeSaver({str(sid): {"evidence": EVIDENCE, "contradictions": []}}))

    led = (await db.execute(select(MigrationLedger))).scalar_one()
    assert led.status == MigrationStatus.INCONSISTENT_V1
    assert led.failure_category == "UNKNOWN_AUDIT_ACTION"
