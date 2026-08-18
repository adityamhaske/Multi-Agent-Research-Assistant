"""
The V2 database contract, proven identical on PostgreSQL and SQLite (M2D).

The server runs Postgres via Alembic; the desktop sidecar runs SQLite via `create_all`. One
model set serves both (`app/models/types.py`), and every prior release of this project has
found a divergence between the two hosts *after* shipping. So the schema is not merely
declared here — it is exercised against both dialects with the same assertions.

**Structure, not just DDL.** Comparing generated SQL would prove the two look alike.
These tests insert rows that violate each invariant and require the database to *refuse*
them, on both engines, with the same outcome. That is what "behaves identically" means.

Three exclusions are expected and asserted rather than assumed: `memory_chunks`,
`project_memory_items` and `project_memory_provenance` carry pgvector and cannot exist on
SQLite (`POSTGRES_ONLY_TABLES`). Project memory is the one feature absent on desktop by
design (docs/12 M10).

**Nothing reads or writes these tables in production yet.** M2D builds the contract; the
migration plan's later phases fill it (`internal/V2_Migration_Plan_M2C.md`).
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, delete, insert, inspect, text, update
from sqlalchemy.exc import IntegrityError

from app.models import POSTGRES_ONLY_TABLES, Base
from app.models.project import Project
from app.models.research import Evidence, ResearchPlan, ResearchRun, Source
from app.models.review import ResearchArtifact, Review
from app.models.revision import Claim, ClaimEvidenceLink, Revision
from app.models.user import User

V2_TABLES = (
    "research_runs",
    "research_plans",
    "sources",
    "evidence",
    "contradictions",
    "revisions",
    "claims",
    "claim_evidence_links",
    "reviews",
    "claim_annotations",
    "research_artifacts",
    "audit_events",
    "project_memory_items",
    "project_memory_provenance",
)


def _pg_url() -> str:
    """The same database the rest of the suite uses, in sync-driver form.

    Deliberately not a dedicated scratch DSN: CI runs `alembic upgrade head` against its
    own Postgres (`ci.yml`), so pointing elsewhere would make the Postgres half of these
    tests skip in CI — a parity suite that only ever proves the SQLite side.
    """
    return os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://research_user:research_pass@localhost:5432/research_test_db",
    ).replace("postgresql+asyncpg://", "postgresql+psycopg://")


HASH64 = "a" * 64

#: Tables that carry a pgvector column, or reference one that does — stated **literally**,
#: not read from `POSTGRES_ONLY_TABLES`.
#:
#: An earlier version compared the exclusion set against itself, which is tautological:
#: removing a table from the set removed it from both sides and the test still passed.
#: SQLite accepts an unknown type name like `VECTOR(768)` without complaint, so the table
#: would have been created there and failed at query time instead. Verified by planting
#: exactly that.
PGVECTOR_DEPENDENT = frozenset(
    {"memory_chunks", "project_memory_items", "project_memory_provenance"}
)


# ── Engines ───────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def sqlite_engine(tmp_path_factory):
    """The desktop host's path: `create_all`, minus the pgvector tables."""
    path = tmp_path_factory.mktemp("v2parity") / "desktop.sqlite"
    engine = create_engine(f"sqlite:///{path}")
    # SQLite enforces foreign keys only when asked, and the desktop app does ask
    # (`sidecar.py` sets the pragma on connect). Without this the FK assertions below
    # would pass vacuously — the exact "test that mocks the mechanism" trap.
    with engine.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):  # pragma: no cover — trivial
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    tables = [t for t in Base.metadata.sorted_tables if t.name not in POSTGRES_ONLY_TABLES]
    Base.metadata.create_all(engine, tables=tables)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def pg_engine():
    """The server host's path: whatever `alembic upgrade head` produced."""
    engine = create_engine(_pg_url())
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover — environment dependent
        pytest.skip(f"no Postgres at DATABASE_URL ({type(exc).__name__})")
    names = set(inspect(engine).get_table_names())
    missing = set(V2_TABLES) - names
    if missing:
        pytest.skip(
            f"m2d_test is not migrated (missing {sorted(missing)}) — run alembic upgrade head"
        )
    yield engine
    engine.dispose()


# ── 1. The tables exist, on the dialect that should have them ────────────────────


def test_sqlite_creates_every_portable_v2_table(sqlite_engine):
    names = set(inspect(sqlite_engine).get_table_names())
    expected = set(V2_TABLES) - POSTGRES_ONLY_TABLES
    assert expected <= names, f"create_all missed {sorted(expected - names)}"


def test_sqlite_excludes_exactly_the_pgvector_tables(sqlite_engine):
    """Asserted against a literal list, so shrinking the exclusion set is caught here."""
    names = set(inspect(sqlite_engine).get_table_names())
    leaked = PGVECTOR_DEPENDENT & names
    assert not leaked, f"pgvector tables reached SQLite: {sorted(leaked)}"


def test_the_exclusion_set_covers_every_pgvector_table(sqlite_engine):
    """The set itself is correct, independently of what `create_all` happened to do."""
    assert PGVECTOR_DEPENDENT <= POSTGRES_ONLY_TABLES, (
        f"not excluded from the desktop schema: {sorted(PGVECTOR_DEPENDENT - POSTGRES_ONLY_TABLES)}"
    )


def test_postgres_has_every_v2_table_including_pgvector(pg_engine):
    names = set(inspect(pg_engine).get_table_names())
    assert set(V2_TABLES) <= names, f"alembic missed {sorted(set(V2_TABLES) - names)}"


def test_the_exclusion_set_is_the_only_difference(sqlite_engine, pg_engine):
    """The two hosts' V2 surfaces differ by exactly the declared exclusions and nothing else."""
    sqlite_v2 = set(inspect(sqlite_engine).get_table_names()) & set(V2_TABLES)
    pg_v2 = set(inspect(pg_engine).get_table_names()) & set(V2_TABLES)
    assert pg_v2 - sqlite_v2 == POSTGRES_ONLY_TABLES & set(V2_TABLES)
    assert sqlite_v2 - pg_v2 == set(), "SQLite has a V2 table Postgres does not"


# ── 2. Constraints and indexes are present on both ───────────────────────────────

#: Named constraints/indexes that must exist on both dialects. Alembic prefixes CHECK
#: constraints with its naming convention on Postgres, so comparison is by suffix.
REQUIRED_CHECKS = (
    "ck_run_status",
    "ck_run_cancelled",
    "ck_run_resolution",
    "ck_ev_state",
    "ck_ev_unchecked",
    "ck_ev_grade",
    "ck_claim_unchecked",
    "ck_review_plan",
    "ck_artifact_approved",
    "ck_source_corpus",
    "ck_contra_pair",
)
REQUIRED_INDEXES = (
    "uq_plan_approved",
    "uq_review_approval",
    "uq_artifact_run",
    "ix_link_evidence",
)


@pytest.mark.parametrize("name", REQUIRED_CHECKS)
def test_check_constraint_exists_on_both(name, sqlite_engine, pg_engine):
    for engine, label in ((sqlite_engine, "sqlite"), (pg_engine, "postgres")):
        found = set()
        insp = inspect(engine)
        for table in insp.get_table_names():
            if table in POSTGRES_ONLY_TABLES and label == "sqlite":
                continue
            for ck in insp.get_check_constraints(table):
                if ck.get("name"):
                    found.add(ck["name"])
        assert any(n.endswith(name) for n in found), f"{name} missing on {label}"


@pytest.mark.parametrize("name", REQUIRED_INDEXES)
def test_index_exists_on_both(name, sqlite_engine, pg_engine):
    for engine, label in ((sqlite_engine, "sqlite"), (pg_engine, "postgres")):
        found = set()
        insp = inspect(engine)
        for table in insp.get_table_names():
            if table in POSTGRES_ONLY_TABLES and label == "sqlite":
                continue
            found.update(ix["name"] for ix in insp.get_indexes(table) if ix.get("name"))
        assert name in found, f"{name} missing on {label}"


def test_partial_unique_indexes_are_actually_partial(sqlite_engine, pg_engine):
    """A partial index rendered without its predicate becomes a total one.

    `uq_plan_approved` would then forbid a second *unapproved* plan version and break the
    rework loop — silently, on whichever dialect lost the predicate. SQLAlchemy emits
    `postgresql_where` only for Postgres and `sqlite_where` only for SQLite, so both
    keywords have to be declared; this proves they were.
    """
    for engine, label in ((sqlite_engine, "sqlite"), (pg_engine, "postgres")):
        insp = inspect(engine)
        for ix in insp.get_indexes("research_plans"):
            if ix["name"] == "uq_plan_approved":
                assert (
                    ix.get("dialect_options")
                    or ix.get("expressions")
                    or _has_where(engine, "uq_plan_approved")
                ), f"uq_plan_approved is not partial on {label}"


def _has_where(engine, index_name: str) -> bool:
    """Read the index definition text — the portable way to see a WHERE clause."""
    if engine.dialect.name == "postgresql":
        sql = "SELECT indexdef FROM pg_indexes WHERE indexname = :n"
    else:
        sql = "SELECT sql FROM sqlite_master WHERE type='index' AND name = :n"
    with engine.connect() as conn:
        row = conn.execute(text(sql), {"n": index_name}).scalar()
    return bool(row) and " WHERE " in row.upper()


# ── 3. Behavioural parity: the same inserts are refused on both ──────────────────


def _seed(conn):
    """A minimal user/project/run/source/revision graph. Returns the ids.

    Built through the ORM models rather than literal SQL: hand-written column names are
    how a fixture ends up asserting against a schema that does not exist (`hashed_password`
    vs `hashed_pw`), and boolean literals do not render the same on both dialects.
    """
    uid, pid, rid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    now = datetime.now(UTC)
    conn.execute(
        insert(User).values(
            id=uid,
            email=f"{uid}@example.invalid",
            hashed_pw="x",
            is_active=True,
            created_at=now,
        )
    )
    conn.execute(
        insert(Project).values(
            id=pid,
            user_id=uid,
            name=f"P-{uid.hex[:8]}",
            created_at=now,
            updated_at=now,
        )
    )
    conn.execute(
        insert(ResearchRun).values(
            id=rid,
            project_id=pid,
            owner_id=uid,
            question="q",
            status="RUNNING",
            depth="fast",
            corpus_mode=False,
            demo=False,
            skip_plan_gate=False,
            cost_usd=0,
            tokens_input=0,
            tokens_output=0,
            created_at=now,
            updated_at=now,
        )
    )
    sid = uuid.uuid4()
    conn.execute(
        insert(Source).values(
            id=sid,
            run_id=rid,
            url="https://e.org/a",
            normalized_url="https://e.org/a",
            kind="WEB",
            retrieval_status="FETCHED",
            citation_index=1,
            retrieved_at=now,
        )
    )
    vid = uuid.uuid4()
    conn.execute(
        insert(Revision).values(
            id=vid,
            run_id=rid,
            version=1,
            report_markdown="# R",
            report_hash=HASH64,
            evidence_watermark=0,
            created_at=now,
        )
    )
    return {"user": uid, "project": pid, "run": rid, "source": sid, "revision": vid, "now": now}


def _both(sqlite_engine, pg_engine):
    return ((sqlite_engine, "sqlite"), (pg_engine, "postgres"))


def _refuses(engine, build):
    """Run `build(conn, ids)` in a rolled-back transaction; True if a CONSTRAINT refused it.

    Deliberately narrowed to `IntegrityError`. An earlier version caught `DatabaseError`,
    and several of these tests passed against SQLite for the wrong reason entirely — a
    raw `text()` statement binding a Python UUID raises `ProgrammingError`, which is also
    a `DatabaseError`. They were asserting "the database said no" while the database had
    never evaluated the constraint. That is the "test that mocks the mechanism it is
    testing" trap, and narrowing the exception is what closes it.

    Rollback keeps these side-effect free, which is what lets them share one migrated
    database across the module.
    """
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            ids = _seed(conn)
            build(conn, ids)
            return False
        except IntegrityError:
            return True
        finally:
            trans.rollback()


def _accepts(engine, build):
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            ids = _seed(conn)
            build(conn, ids)
            return True
        except IntegrityError:
            return False
        finally:
            trans.rollback()


# --- the provenance model (M2A §4) ---


def test_unchecked_evidence_cannot_carry_an_attestation_timestamp(sqlite_engine, pg_engine):
    """The unmeasured-vs-zero rule, made unstorable."""

    def build(conn, ids):
        conn.execute(
            insert(Evidence).values(
                id=uuid.uuid4(),
                run_id=ids["run"],
                source_id=ids["source"],
                sequence=1,
                snippet="s",
                content_hash=HASH64,
                provenance_state="UNCHECKED",
                attestation_run_at=ids["now"],
                created_at=ids["now"],
            )
        )

    for engine, label in _both(sqlite_engine, pg_engine):
        assert _refuses(engine, build), f"{label} accepted UNCHECKED evidence with a timestamp"


def test_attested_evidence_must_record_when_it_was_checked(sqlite_engine, pg_engine):
    def build(conn, ids):
        conn.execute(
            insert(Evidence).values(
                id=uuid.uuid4(),
                run_id=ids["run"],
                source_id=ids["source"],
                sequence=1,
                snippet="s",
                content_hash=HASH64,
                provenance_state="ATTESTED",
                attested_against="FETCHED_BODY",
                attestation_run_at=None,
                created_at=ids["now"],
            )
        )

    for engine, label in _both(sqlite_engine, pg_engine):
        assert _refuses(engine, build), f"{label} accepted ATTESTED evidence with no timestamp"


def test_only_attested_evidence_may_carry_a_grade(sqlite_engine, pg_engine):
    def build(conn, ids):
        conn.execute(
            insert(Evidence).values(
                id=uuid.uuid4(),
                run_id=ids["run"],
                source_id=ids["source"],
                sequence=1,
                snippet="s",
                content_hash=HASH64,
                provenance_state="UNATTESTED",
                attested_against="FETCHED_BODY",
                attestation_run_at=ids["now"],
                created_at=ids["now"],
            )
        )

    for engine, label in _both(sqlite_engine, pg_engine):
        assert _refuses(engine, build), f"{label} accepted a grade on non-attested evidence"


def test_a_valid_unchecked_row_is_accepted_on_both(sqlite_engine, pg_engine):
    """Guard the guard: if every insert failed, the tests above would pass vacuously."""

    def build(conn, ids):
        conn.execute(
            insert(Evidence).values(
                id=uuid.uuid4(),
                run_id=ids["run"],
                source_id=ids["source"],
                sequence=1,
                snippet="s",
                content_hash=HASH64,
                provenance_state="UNCHECKED",
                created_at=ids["now"],
            )
        )

    for engine, label in _both(sqlite_engine, pg_engine):
        assert _accepts(engine, build), f"{label} refused a valid UNCHECKED row"


# --- cross-run contamination (M2B §9.6) ---


def test_a_link_cannot_join_a_claim_to_another_runs_evidence(sqlite_engine, pg_engine):
    """The dual composite foreign key, doing the job the design claims for it."""

    def build(conn, ids):
        other = _seed(conn)  # a second, unrelated run
        conn.execute(
            insert(Evidence).values(
                id=(ev := uuid.uuid4()),
                run_id=other["run"],
                source_id=other["source"],
                sequence=1,
                snippet="s",
                content_hash=HASH64,
                provenance_state="UNCHECKED",
                created_at=ids["now"],
            )
        )
        conn.execute(
            insert(Claim).values(
                id=(cl := uuid.uuid4()),
                revision_id=ids["revision"],
                run_id=ids["run"],
                position=0,
                text="A claim.",
                extraction_method="DERIVED_FROM_REPORT",
                verification_state="UNCHECKED",
                verification_method="NOT_RUN",
                created_at=ids["now"],
            )
        )
        # run_id belongs to the claim's run; the evidence belongs to another.
        conn.execute(
            insert(ClaimEvidenceLink).values(
                id=uuid.uuid4(),
                run_id=ids["run"],
                claim_id=cl,
                evidence_id=ev,
                stance="SUPPORTS",
                origin="CITATION_MARKER",
                created_at=ids["now"],
            )
        )

    for engine, label in _both(sqlite_engine, pg_engine):
        assert _refuses(engine, build), f"{label} allowed a cross-run claim/evidence link"


# --- approval is the only path to an artifact (M2A §13.2) ---


def test_an_artifact_cannot_reference_a_rework_review(sqlite_engine, pg_engine):
    """The composite FK to `reviews(id, decision)` plus CHECK, working together."""

    def build(conn, ids):
        conn.execute(
            insert(Review).values(
                id=(rv := uuid.uuid4()),
                revision_id=ids["revision"],
                reviewer_id=ids["user"],
                gate="REPORT",
                decision="REWORK_REQUESTED",
                reviewed_hash=HASH64,
                created_at=ids["now"],
            )
        )
        conn.execute(
            insert(ResearchArtifact).values(
                id=uuid.uuid4(),
                owner_id=ids["user"],
                run_id=ids["run"],
                project_id=ids["project"],
                revision_id=ids["revision"],
                review_id=rv,
                review_decision="REWORK_REQUESTED",
                format_version=1,
                payload={},
                artifact_hash=HASH64,
                demo=False,
                created_at=ids["now"],
            )
        )

    for engine, label in _both(sqlite_engine, pg_engine):
        assert _refuses(engine, build), f"{label} allowed an artifact from a rework request"


def test_an_artifact_from_an_approving_review_is_accepted(sqlite_engine, pg_engine):
    def build(conn, ids):
        conn.execute(
            insert(Review).values(
                id=(rv := uuid.uuid4()),
                revision_id=ids["revision"],
                reviewer_id=ids["user"],
                gate="REPORT",
                decision="APPROVED",
                reviewed_hash=HASH64,
                created_at=ids["now"],
            )
        )
        conn.execute(
            insert(ResearchArtifact).values(
                id=uuid.uuid4(),
                owner_id=ids["user"],
                run_id=ids["run"],
                project_id=ids["project"],
                revision_id=ids["revision"],
                review_id=rv,
                review_decision="APPROVED",
                format_version=1,
                payload={},
                artifact_hash=HASH64,
                demo=False,
                created_at=ids["now"],
            )
        )

    for engine, label in _both(sqlite_engine, pg_engine):
        assert _accepts(engine, build), f"{label} refused a legitimate artifact"


def test_only_one_approving_review_per_revision(sqlite_engine, pg_engine):
    """The partial unique index (M2A §6.1 race table)."""

    def build(conn, ids):
        for _ in range(2):
            conn.execute(
                insert(Review).values(
                    id=uuid.uuid4(),
                    revision_id=ids["revision"],
                    reviewer_id=ids["user"],
                    gate="REPORT",
                    decision="APPROVED",
                    reviewed_hash=HASH64,
                    created_at=ids["now"],
                )
            )

    for engine, label in _both(sqlite_engine, pg_engine):
        assert _refuses(engine, build), f"{label} allowed two approvals of one revision"


def test_two_rework_reviews_of_one_revision_are_allowed(sqlite_engine, pg_engine):
    """Proves the index is partial rather than total — a rework loop must keep working."""

    def build(conn, ids):
        for _ in range(2):
            conn.execute(
                insert(Review).values(
                    id=uuid.uuid4(),
                    revision_id=ids["revision"],
                    reviewer_id=ids["user"],
                    gate="REPORT",
                    decision="REWORK_REQUESTED",
                    reviewed_hash=HASH64,
                    created_at=ids["now"],
                )
            )

    for engine, label in _both(sqlite_engine, pg_engine):
        assert _accepts(engine, build), f"{label} forbade a second rework — index is not partial"


# --- the draft_hash overload, resolved (M2A §3.2) ---


def test_a_plan_gate_review_must_name_the_plan_version(sqlite_engine, pg_engine):
    def build(conn, ids):
        conn.execute(
            insert(Review).values(
                id=uuid.uuid4(),
                revision_id=ids["revision"],
                reviewer_id=ids["user"],
                gate="PLAN",
                decision="APPROVED",
                reviewed_hash=HASH64,
                plan_version_id=None,
                created_at=ids["now"],
            )
        )

    for engine, label in _both(sqlite_engine, pg_engine):
        assert _refuses(engine, build), f"{label} accepted a PLAN review with no plan"


def test_a_report_gate_review_must_not_name_a_plan_version(sqlite_engine, pg_engine):
    def build(conn, ids):
        conn.execute(
            insert(ResearchPlan).values(
                id=(pl := uuid.uuid4()),
                run_id=ids["run"],
                version=1,
                tasks=[],
                outline_sections=[],
                origin="MODEL_PROPOSED",
                created_at=ids["now"],
            )
        )
        conn.execute(
            insert(Review).values(
                id=uuid.uuid4(),
                revision_id=ids["revision"],
                reviewer_id=ids["user"],
                gate="REPORT",
                decision="APPROVED",
                reviewed_hash=HASH64,
                plan_version_id=pl,
                created_at=ids["now"],
            )
        )

    for engine, label in _both(sqlite_engine, pg_engine):
        assert _refuses(engine, build), f"{label} accepted a REPORT review naming a plan"


# --- cancellation coherence (M2A §3.11) ---


def test_cancelled_requires_a_timestamp(sqlite_engine, pg_engine):
    def build(conn, ids):
        conn.execute(
            update(ResearchRun).where(ResearchRun.id == ids["run"]).values(status="CANCELLED")
        )

    for engine, label in _both(sqlite_engine, pg_engine):
        assert _refuses(engine, build), f"{label} allowed CANCELLED with no cancelled_at"


def test_a_timestamp_requires_the_cancelled_status(sqlite_engine, pg_engine):
    def build(conn, ids):
        conn.execute(
            update(ResearchRun).where(ResearchRun.id == ids["run"]).values(cancelled_at=ids["now"])
        )

    for engine, label in _both(sqlite_engine, pg_engine):
        assert _refuses(engine, build), f"{label} allowed cancelled_at without the status"


# --- unmeasured is not zero ---


def test_a_resolution_rate_outside_zero_to_one_is_refused(sqlite_engine, pg_engine):
    def build(conn, ids):
        conn.execute(
            update(ResearchRun)
            .where(ResearchRun.id == ids["run"])
            .values(citation_resolution_rate=1.5)
        )

    for engine, label in _both(sqlite_engine, pg_engine):
        assert _refuses(engine, build), f"{label} accepted a rate above 1"


def test_a_null_resolution_rate_is_accepted_on_both(sqlite_engine, pg_engine):
    """NULL is the honest value for unmeasured, and must remain storable."""

    def build(conn, ids):
        conn.execute(
            update(ResearchRun)
            .where(ResearchRun.id == ids["run"])
            .values(citation_resolution_rate=None)
        )

    for engine, label in _both(sqlite_engine, pg_engine):
        assert _accepts(engine, build), f"{label} refused NULL for an unmeasured rate"


# --- vocabularies ---


def test_an_unknown_run_status_is_refused(sqlite_engine, pg_engine):
    def build(conn, ids):
        conn.execute(
            update(ResearchRun).where(ResearchRun.id == ids["run"]).values(status="ABANDONED")
        )

    for engine, label in _both(sqlite_engine, pg_engine):
        assert _refuses(engine, build), f"{label} accepted a status outside the vocabulary"


def test_a_corpus_source_must_name_its_document(sqlite_engine, pg_engine):
    def build(conn, ids):
        conn.execute(
            insert(Source).values(
                id=uuid.uuid4(),
                run_id=ids["run"],
                url="corpus://x",
                normalized_url="corpus://x",
                kind="CORPUS",
                retrieval_status="FETCHED",
                citation_index=2,
                corpus_document_id=None,
                retrieved_at=ids["now"],
            )
        )

    for engine, label in _both(sqlite_engine, pg_engine):
        assert _refuses(engine, build), f"{label} accepted a CORPUS source with no document"


# --- approved research survives the ordinary delete path (M2B §9.3) ---


def test_deleting_a_run_that_carries_a_review_is_refused(sqlite_engine, pg_engine):
    """`DELETE run → CASCADE revisions → RESTRICT reviews` must fail at the restrict.

    This is the schema-level protection for approved research: the ordinary deletion path
    cannot reach it, and the application's only job is to turn the refusal into a message.
    """

    def build(conn, ids):
        conn.execute(
            insert(Review).values(
                id=uuid.uuid4(),
                revision_id=ids["revision"],
                reviewer_id=ids["user"],
                gate="REPORT",
                decision="APPROVED",
                reviewed_hash=HASH64,
                created_at=ids["now"],
            )
        )
        conn.execute(delete(ResearchRun).where(ResearchRun.id == ids["run"]))

    for engine, label in _both(sqlite_engine, pg_engine):
        assert _refuses(engine, build), f"{label} destroyed approved research on a run delete"


def test_deleting_a_run_with_no_review_is_allowed(sqlite_engine, pg_engine):
    def build(conn, ids):
        conn.execute(delete(ResearchRun).where(ResearchRun.id == ids["run"]))

    for engine, label in _both(sqlite_engine, pg_engine):
        assert _accepts(engine, build), f"{label} refused to delete an unreviewed run"


# --- evidence.sequence tolerates gaps (M2B §9.2) ---


def test_evidence_sequence_may_have_gaps(sqlite_engine, pg_engine):
    """Concurrency makes contiguity expensive and it buys nothing — it is a threshold."""

    def build(conn, ids):
        for seq in (1, 7, 41):
            conn.execute(
                insert(Evidence).values(
                    id=uuid.uuid4(),
                    run_id=ids["run"],
                    source_id=ids["source"],
                    sequence=seq,
                    snippet="s",
                    content_hash=HASH64,
                    provenance_state="UNCHECKED",
                    created_at=ids["now"],
                )
            )

    for engine, label in _both(sqlite_engine, pg_engine):
        assert _accepts(engine, build), f"{label} refused a gapped sequence"


def test_evidence_sequence_must_be_unique_within_a_run(sqlite_engine, pg_engine):
    """Gaps are fine; duplicates are not — a duplicate makes the watermark ambiguous."""

    def build(conn, ids):
        for _ in range(2):
            conn.execute(
                insert(Evidence).values(
                    id=uuid.uuid4(),
                    run_id=ids["run"],
                    source_id=ids["source"],
                    sequence=3,
                    snippet="s",
                    content_hash=HASH64,
                    provenance_state="UNCHECKED",
                    created_at=ids["now"],
                )
            )

    for engine, label in _both(sqlite_engine, pg_engine):
        assert _refuses(engine, build), f"{label} allowed a duplicate sequence"
