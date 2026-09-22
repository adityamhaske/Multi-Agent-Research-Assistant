"""
An installed desktop database loses its obsolete `agent_logs` foreign key on upgrade.

**The defect.** `agent_logs.session_id` used to carry
`fk_agent_logs_session_id_sessions` — an FK to `sessions` with `ON DELETE CASCADE`. The
column is polymorphic now: it names a `sessions.id` *or* a `research_runs.id`, so an FK can
only ever point at one of them (`app/models/agent_log.py`). Alembic drops it in
`0018_agent_logs_polymorphic`, but **the desktop does not run Alembic** — it builds its
schema with `create_all` plus `_add_missing_columns`, which is additive only and says so:
"Renames, drops, type changes and data backfills are not handled and pass silently."

So a fresh install is correct and an install created before that model change is not. On the
latter, `PRAGMA foreign_keys=ON` (set in the sidecar's engine listener) makes every
run-sourced trace insert fail:

    (sqlite3.IntegrityError) FOREIGN KEY constraint failed
    [SQL: INSERT INTO agent_logs (session_id, event_type, agent_name, payload) ...]

`persist_and_publish` catches that and logs `sidecar_event_persist_failed` at *warning*
level, so the run completes and nothing surfaces to the user — but `agent_logs` **is** the
run trace, so the live feed, the replayable trace and a bundle's `trace` array are all empty
for every run on an upgraded install. Measured on a real packaged binary: 28 failures in one
run against a database created 2026-08-14, zero against a fresh one.

**These tests use real SQLite throughout.** The legacy table is created with the DDL the old
model actually emitted, rows go in through SQLite, and the "does a trace event persist now"
case drives `persist_and_publish` — the desktop's real event sink — rather than inserting a
row itself. Asserting on a hand-made result instead of the real path is how
`test_corpus_egress.py` stayed green through a live defect.

**Structure is compared with `PRAGMA`, never with DDL text.** `ALTER TABLE … RENAME TO`
leaves the table name quoted in `sqlite_master`, so a rebuilt table's SQL differs from a
fresh one's by two characters while being structurally identical.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy import event as sa_event

from app.models import POSTGRES_ONLY_TABLES, Base
from desktop.sidecar import _rebuild_legacy_agent_logs

TABLES = [t for t in Base.metadata.sorted_tables if t.name not in POSTGRES_ONLY_TABLES]

#: The constraint as the pre-`70acc95` model emitted it through the metadata naming
#: convention. Everything else in this DDL — columns, types, nullability, the primary key,
#: both indexes — is byte-identical to what the current model emits; the FK is the only
#: delta, which is what makes a schema-preserving rebuild the right shape of fix.
LEGACY_AGENT_LOGS = """
CREATE TABLE agent_logs (
    id INTEGER NOT NULL,
    session_id CHAR(32) NOT NULL,
    event_type VARCHAR(40) NOT NULL,
    agent_name VARCHAR(50),
    payload JSON NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_agent_logs PRIMARY KEY (id),
    CONSTRAINT fk_agent_logs_session_id_sessions
        FOREIGN KEY(session_id) REFERENCES sessions (id) ON DELETE CASCADE
)
"""


def _structure(conn, table: str) -> dict:
    """Everything about the table that is allowed to matter, and nothing that is not."""
    return {
        "columns": [tuple(r) for r in conn.exec_driver_sql(f"PRAGMA table_info('{table}')")],
        "indexes": sorted(
            (r[1], r[2]) for r in conn.exec_driver_sql(f"PRAGMA index_list('{table}')")
        ),
        "foreign_keys": [
            tuple(r) for r in conn.exec_driver_sql(f"PRAGMA foreign_key_list('{table}')")
        ],
    }


def _rows(conn) -> list[tuple]:
    return [
        tuple(r)
        for r in conn.exec_driver_sql(
            "SELECT id, session_id, event_type, agent_name, payload, created_at "
            "FROM agent_logs ORDER BY id"
        )
    ]


def _sync(engine) -> None:
    """The real call, wired the way the sidecar's lifespan wires it: a sync connection
    inside one transaction."""
    with engine.begin() as conn:
        _rebuild_legacy_agent_logs(conn, TABLES)


def _engine(path):
    """A SQLite engine with the pragma the sidecar sets on every connection.

    `PRAGMA foreign_keys=ON` is not decoration here: SQLite leaves enforcement off by
    default, and with it off the obsolete constraint would be inert and these tests would
    pass against the unfixed code. The defect only exists because the sidecar turns it on
    (`desktop/sidecar.py`), so the fixture turns it on too.
    """
    engine = create_engine(f"sqlite:///{path}")

    @sa_event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _record):  # noqa: ANN001, ANN202
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine


def _required(conn, table: str, **values) -> dict:
    """Fill in every NOT NULL column the caller did not name.

    Derived from the metadata rather than spelled out, the same way
    `test_desktop_column_sync._insert` does it: most NOT NULL columns here default in Python
    rather than in the database, so a hand-written INSERT names them all and grows a new
    omission every time a model gains a column.
    """
    placeholder = {"INTEGER": 0, "BIGINT": 0, "BOOLEAN": 0, "NUMERIC": 0, "FLOAT": 0.0}
    row = dict(values)
    for column in Base.metadata.tables[table].columns:
        if column.name in row or column.nullable or column.server_default is not None:
            continue
        if column.primary_key and column.autoincrement:
            continue  # let SQLite mint it — `agent_logs.id` is the SSE cursor
        kind = column.type.compile(dialect=conn.dialect).split("(")[0].upper()
        row.setdefault(column.name, placeholder.get(kind, f"{table[:2]}-{column.name}"))
    return row


def _insert(conn, table: str, **values) -> None:
    row = _required(conn, table, **values)
    names = ", ".join(f'"{k}"' for k in row)
    binds = ", ".join(f":{k}" for k in row)
    conn.execute(text(f"INSERT INTO {table} ({names}) VALUES ({binds})"), row)  # noqa: S608


def _legacy_db(tmp_path, *, rows: int):
    """A database at the current schema except that `agent_logs` is the legacy shape.

    Built by creating everything current, dropping `agent_logs`, and putting the old table
    back — so every *other* table is genuinely what an installed app has, and the one under
    test is genuinely what the old model emitted.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    engine = _engine(tmp_path / "desktop.sqlite")
    Base.metadata.create_all(engine, tables=TABLES)
    user_id, project_id, session_id = (uuid.uuid4().hex for _ in range(3))
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE agent_logs")
        conn.exec_driver_sql(LEGACY_AGENT_LOGS)
        conn.exec_driver_sql("CREATE INDEX ix_agent_logs_session_id ON agent_logs (session_id)")
        conn.exec_driver_sql("CREATE INDEX ix_agent_logs_created_at ON agent_logs (created_at)")
        _insert(conn, "users", id=user_id, email=f"{user_id}@x.invalid", hashed_pw="x")
        _insert(conn, "projects", id=project_id, user_id=user_id, name="Legacy")
        _insert(
            conn,
            "sessions",
            id=session_id,
            user_id=user_id,
            project_id=project_id,
            prompt="q",
            status="COMPLETED",
            research_depth="fast",
        )
        for i in range(rows):
            _insert(
                conn,
                "agent_logs",
                session_id=session_id,
                event_type="agent_log",
                agent_name=f"agent-{i}",
                payload=json.dumps({"type": "agent_log", "message": f"event {i}"}),
            )
    return engine, session_id


@pytest.fixture()
def fresh(tmp_path):
    """What a first-ever launch produces — the structure the rebuild must land on."""
    engine = _engine(tmp_path / "fresh.sqlite")
    Base.metadata.create_all(engine, tables=TABLES)
    yield engine
    engine.dispose()


# ── 1. Legacy schema, populated ───────────────────────────────────────────────────


def test_a_populated_legacy_database_is_rebuilt_without_losing_a_row(tmp_path, fresh):
    engine, _ = _legacy_db(tmp_path / "a", rows=5)
    try:
        with engine.begin() as conn:
            before = _rows(conn)
            assert len(before) == 5, "fixture precondition"
            assert any(
                fk[2] == "sessions"
                for fk in conn.exec_driver_sql("PRAGMA foreign_key_list('agent_logs')")
            ), "fixture precondition: the obsolete FK must be present"

        _sync(engine)

        with engine.begin() as conn, fresh.begin() as ref:
            assert _rows(conn) == before, "trace rows changed across the rebuild"
            assert conn.exec_driver_sql("PRAGMA foreign_key_list('agent_logs')").fetchall() == []
            assert _structure(conn, "agent_logs") == _structure(ref, "agent_logs"), (
                "the rebuilt table is not structurally what a fresh install builds"
            )
            assert conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
    finally:
        engine.dispose()


def test_a_run_sourced_row_can_be_written_after_the_rebuild(tmp_path):
    """The defect itself: before the rebuild this insert raises, after it it does not."""
    engine, _ = _legacy_db(tmp_path / "b", rows=1)
    orphan = uuid.uuid4().hex  # a research_runs.id — no matching `sessions` row
    try:
        with engine.begin() as conn, pytest.raises(Exception, match="FOREIGN KEY"):
            conn.execute(
                text(
                    "INSERT INTO agent_logs (session_id, event_type, payload) "
                    "VALUES (:s, 'agent_log', '{}')"
                ),
                {"s": orphan},
            )

        _sync(engine)

        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO agent_logs (session_id, event_type, payload) "
                    "VALUES (:s, 'agent_log', '{}')"
                ),
                {"s": orphan},
            )
        with engine.begin() as conn:
            assert (
                conn.exec_driver_sql(
                    "SELECT count(*) FROM agent_logs WHERE session_id = ?", (orphan,)
                ).scalar()
                == 1
            )
    finally:
        engine.dispose()


# ── 2. Legacy schema, empty ───────────────────────────────────────────────────────


def test_an_empty_legacy_table_is_rebuilt(tmp_path, fresh):
    """Startup must be safe on an install that has the old schema and no trace rows yet."""
    engine, _ = _legacy_db(tmp_path / "c", rows=0)
    try:
        _sync(engine)
        with engine.begin() as conn, fresh.begin() as ref:
            assert _rows(conn) == []
            assert conn.exec_driver_sql("PRAGMA foreign_key_list('agent_logs')").fetchall() == []
            assert _structure(conn, "agent_logs") == _structure(ref, "agent_logs")
    finally:
        engine.dispose()


# ── 3. Already correct: no rebuild ────────────────────────────────────────────────


def test_a_current_database_is_left_completely_alone(tmp_path):
    """Not "still correct afterwards" — *untouched*.

    `sqlite_master.rootpage` changes when a table is recreated, so comparing it is how a
    silent unconditional rebuild is caught. A test that only re-checked the schema would
    pass against a function that rebuilds every startup.
    """
    engine = _engine(tmp_path / "current.sqlite")
    Base.metadata.create_all(engine, tables=TABLES)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO agent_logs (session_id, event_type, payload) "
                    "VALUES (:s, 'agent_log', '{}')"
                ),
                {"s": uuid.uuid4().hex},
            )
        with engine.begin() as conn:
            before_rootpage = conn.exec_driver_sql(
                "SELECT rootpage FROM sqlite_master WHERE name = 'agent_logs'"
            ).scalar()
            before_sql = conn.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE name = 'agent_logs'"
            ).scalar()
            before = _rows(conn)

        _sync(engine)

        with engine.begin() as conn:
            assert (
                conn.exec_driver_sql(
                    "SELECT rootpage FROM sqlite_master WHERE name = 'agent_logs'"
                ).scalar()
                == before_rootpage
            ), "the table was rebuilt when it did not need to be"
            assert (
                conn.exec_driver_sql(
                    "SELECT sql FROM sqlite_master WHERE name = 'agent_logs'"
                ).scalar()
                == before_sql
            )
            assert _rows(conn) == before
    finally:
        engine.dispose()


# ── 4. Idempotency ────────────────────────────────────────────────────────────────


def test_running_the_upgrade_twice_is_safe(tmp_path, fresh):
    engine, _ = _legacy_db(tmp_path / "d", rows=3)
    try:
        _sync(engine)
        with engine.begin() as conn:
            after_first = _rows(conn)
            rootpage = conn.exec_driver_sql(
                "SELECT rootpage FROM sqlite_master WHERE name = 'agent_logs'"
            ).scalar()

        _sync(engine)

        with engine.begin() as conn, fresh.begin() as ref:
            assert _rows(conn) == after_first, "the second run changed the data"
            assert (
                conn.exec_driver_sql(
                    "SELECT rootpage FROM sqlite_master WHERE name = 'agent_logs'"
                ).scalar()
                == rootpage
            ), "the second run rebuilt an already-correct table"
            assert _structure(conn, "agent_logs") == _structure(ref, "agent_logs")
    finally:
        engine.dispose()


# ── 5. Real trace persistence, through the desktop's own sink ─────────────────────


async def test_a_real_trace_event_persists_after_the_upgrade(tmp_path):
    """`persist_and_publish` — the function every desktop event actually goes through.

    Inserting a row directly would prove the schema changed. This proves the *product*
    works: the same sink the pipeline calls, with a run-sourced id that has no `sessions`
    row behind it, which is precisely what the obsolete FK rejected.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from desktop.sidecar import SessionEventBus, persist_and_publish

    engine, _ = _legacy_db(tmp_path / "e", rows=2)
    engine.dispose()
    _sync(_engine(tmp_path / "e" / "desktop.sqlite"))

    async_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'e' / 'desktop.sqlite'}")

    # The same pragma the sidecar's engine sets. Without it the FK would not be enforced
    # and this test would pass against the unfixed code — the defect only exists with
    # enforcement on, so the test has to reproduce it.
    from sqlalchemy import event as sa_event

    @sa_event.listens_for(async_engine.sync_engine, "connect")
    def _pragmas(dbapi_conn, _record):  # noqa: ANN001, ANN202
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    maker = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)
    run_id = uuid.uuid4()  # a research_runs.id: no `sessions` row exists for it
    try:
        await persist_and_publish(
            maker,
            SessionEventBus(),
            run_id,
            {"type": "agent_log", "agent": "synthesizer", "message": "Compiling the report"},
        )
        async with maker() as db:
            stored = (
                await db.execute(
                    text(
                        "SELECT event_type, agent_name, payload FROM agent_logs "
                        "WHERE session_id = :s"
                    ),
                    {"s": run_id.hex},
                )
            ).fetchall()
        assert len(stored) == 1, (
            "a run-sourced trace event did not persist — this is the defect, and it fails "
            "silently because persist_and_publish logs rather than raises"
        )
        assert stored[0][0] == "agent_log"
        assert stored[0][1] == "synthesizer"
        assert json.loads(stored[0][2])["message"] == "Compiling the report"
    finally:
        await async_engine.dispose()


# ── 6. Failure safety ─────────────────────────────────────────────────────────────


def test_a_failure_midway_leaves_the_database_exactly_as_it_was(tmp_path, monkeypatch):
    """A half-rebuilt table is how a database becomes unrecoverable.

    The rebuild runs inside the caller's transaction, so the guarantee is SQLite's, not a
    rollback mechanism of this migration's own. That is the claim under test: the rows and
    the table are still there after an exception between DROP and RENAME.
    """
    import desktop.sidecar as sidecar_mod

    engine, _ = _legacy_db(tmp_path / "f", rows=4)
    try:
        with engine.begin() as conn:
            before = _rows(conn)
            before_sql = conn.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE name = 'agent_logs'"
            ).scalar()

        real_create_index = sidecar_mod.CreateIndex

        def _explode(*args, **kwargs):  # noqa: ARG001, ANN002, ANN003
            raise RuntimeError("induced failure after the table was dropped")

        monkeypatch.setattr(sidecar_mod, "CreateIndex", _explode)
        with pytest.raises(RuntimeError, match="induced failure"), engine.begin() as conn:
            _rebuild_legacy_agent_logs(conn, TABLES)
        monkeypatch.setattr(sidecar_mod, "CreateIndex", real_create_index)

        with engine.begin() as conn:
            assert _rows(conn) == before, "trace rows were lost by a failed rebuild"
            assert (
                conn.exec_driver_sql(
                    "SELECT sql FROM sqlite_master WHERE name = 'agent_logs'"
                ).scalar()
                == before_sql
            ), "the table was left partially rebuilt"
            assert (
                conn.exec_driver_sql(
                    "SELECT count(*) FROM sqlite_master WHERE name LIKE 'agent_logs%rebuild%'"
                ).scalar()
                == 0
            ), "a scratch table was left behind"
    finally:
        engine.dispose()
