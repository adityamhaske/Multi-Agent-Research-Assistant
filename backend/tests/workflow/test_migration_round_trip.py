"""
The migration chain is walkable in both directions, on a database with data in it.

`docs/architecture/05-data-model.md` has claimed for a long time that "every migration has a
real `downgrade()`, and the round-trip is exercised in CI". Neither half was true: nothing
anywhere ran a downgrade, and when one was finally run it failed — `0008_chat_threads`
dropped `ck_chat_messages_ck_chat_messages_one_parent`, a doubled prefix produced by passing
an already-rendered name back through the metadata naming convention. That constraint has
never existed in any database, so **every** downgrade past revision 0008 died there, on any
data, empty or not. V3 adds nine migrations on top of a chain nobody had ever reversed.

**Its own database, never the suite's.** These tests take the schema apart and put it back;
`conftest.migrated_database` brings the shared test database to head once per session and
every other test in the suite depends on it staying there. So this file creates and drops a
scratch database of its own, per test, and touches nothing else on the server.

**Two populated scenarios, because "reversible" is not one property.**

*Compatible* (`test_a_populated_database_survives_a_full_round_trip`) — a realistic row in
every table, all of it expressible in the historical schemas, goes down to base and back up.

*Incompatible* (`test_a_run_sourced_memory_chunk_refuses_the_0022_downgrade`) — project
memory indexed from a **run** cannot satisfy `0022`'s reinstated foreign key to `sessions`,
and the migration says so itself: "Reinstating the FK fails if any run from the current
pipeline has been indexed, which is correct: those rows reference `research_runs`, and the
constraint would be a lie." So `0022` is not irreversible; it is *conditionally* reversible,
and the condition is a real product state. What matters there is that the refusal is clean —
PostgreSQL's transactional DDL must leave the schema and every row exactly as they were,
because a half-applied downgrade is how a database becomes unrecoverable.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

BACKEND = Path(__file__).resolve().parents[2]

#: Its own database, named so that finding it left behind says where it came from.
SCRATCH_DB = "a9_migration_round_trip"

#: The revision that reversing the chain has to get through. Named rather than implied: this
#: file exists because it did not.
CHAT_THREADS = "0008_chat_threads"

#: Where the data-dependent boundary lives (§ the module docstring).
MEMORY_POLYMORPHIC = "0022_memory_chunks_polymorphic"

#: The other one, and the reason there are two. Found by Scenario A rather than by reading.
AGENT_LOGS_POLYMORPHIC = "0018_agent_logs_polymorphic"


def _sync_dsn(url: str, database: str) -> str:
    """`postgresql://…/<database>` — psycopg's form, not SQLAlchemy's."""
    parts = urlsplit(url.replace("postgresql+asyncpg://", "postgresql://"))
    return urlunsplit(parts._replace(path=f"/{database}"))


def _async_dsn(url: str, database: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{database}"))


@pytest.fixture()
def scratch_db():
    """A database of this file's own, dropped again however the test ends."""
    psycopg = pytest.importorskip("psycopg")
    url = os.environ["DATABASE_URL"]
    admin = _sync_dsn(url, "postgres")
    try:
        conn = psycopg.connect(admin, connect_timeout=5, autocommit=True)
    except Exception as exc:  # noqa: BLE001 — a developer without a server gets a reason
        pytest.skip(f"no PostgreSQL at {urlsplit(admin).netloc}: {exc}")
    with conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{SCRATCH_DB}"')
    try:
        yield _async_dsn(url, SCRATCH_DB)
    finally:
        with psycopg.connect(admin, connect_timeout=5, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)')


def alembic(dsn: str, *args: str) -> subprocess.CompletedProcess:
    """Run Alembic against `dsn` in a subprocess.

    A subprocess for the reason `conftest.migrated_database` uses one: `env.py` builds its
    own engine from `settings.database_url`, read at import, so pointing it somewhere else
    in-process would mean re-importing configuration the rest of the suite is holding.
    `-m alembic` rather than the console script — the interpreter running the tests is the
    one with the dependencies.
    """
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "DATABASE_URL": dsn},
    )


def _query(dsn: str, sql: str):
    import psycopg

    with psycopg.connect(_sync_dsn(dsn, SCRATCH_DB), connect_timeout=5) as conn:
        return conn.execute(sql).fetchall()


def _snapshot(dsn: str) -> dict:
    """Everything a refused downgrade must leave exactly as it found it."""
    counts = {
        table: _query(dsn, f"SELECT count(*) FROM {table}")[0][0]  # noqa: S608 - fixed names
        for table in ("agent_logs", "memory_chunks", "research_runs", "revisions", "sessions")
    }
    return {
        "revision": _query(dsn, "SELECT version_num FROM alembic_version")[0][0],
        "tables": _tables(dsn),
        **counts,
    }


def _tables(dsn: str) -> set[str]:
    rows = _query(
        dsn, "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
    )
    return {r[0] for r in rows}


#: One realistic row per table, in dependency order, all of it expressible in the schemas
#: the chain passes through on the way down. `sessions` is parked at `AWAITING_PLAN` on
#: purpose: that is the status `0013` added and the state its downgrade note is about.
_COMPATIBLE_ROWS = (
    "INSERT INTO users (id,email,hashed_pw,is_active,created_at)"
    " VALUES (gen_random_uuid(),'round-trip@x.invalid','x',true,now())",
    "INSERT INTO projects (id,user_id,name,created_at,updated_at)"
    " SELECT gen_random_uuid(),id,'Round trip',now(),now() FROM users LIMIT 1",
    "INSERT INTO sessions (id,user_id,project_id,prompt,status,research_depth,created_at,updated_at)"
    " SELECT gen_random_uuid(),u.id,p.id,'q','AWAITING_PLAN','fast',now(),now()"
    " FROM users u,projects p LIMIT 1",
    # Every NOT NULL column is named: these carry Python-side ORM defaults, not database
    # ones, so raw SQL has to supply them. Reading them off `information_schema` beats
    # trusting the model, which is the layer this file is checking the database against.
    "INSERT INTO research_runs (id,project_id,owner_id,question,status,depth,corpus_mode,demo,"
    "skip_plan_gate,cost_usd,tokens_input,tokens_output,created_at,updated_at)"
    " SELECT gen_random_uuid(),p.id,u.id,'q','COMPLETED','fast',false,false,false,0,0,0,now(),now()"
    " FROM users u,projects p LIMIT 1",
    "INSERT INTO research_plans (id,run_id,version,tasks,outline_sections,origin,created_at)"
    " SELECT gen_random_uuid(),id,1,'[]'::json,'[]'::json,'MODEL_PROPOSED',now()"
    " FROM research_runs LIMIT 1",
    "INSERT INTO sources (id,run_id,url,normalized_url,kind,retrieval_status,retrieved_at,citation_index)"
    " SELECT gen_random_uuid(),id,'https://x.invalid/a','x.invalid/a','WEB','FETCHED',now(),1"
    " FROM research_runs LIMIT 1",
    "INSERT INTO evidence (id,run_id,source_id,sequence,snippet,content_hash,provenance_state)"
    " SELECT gen_random_uuid(),r.id,s.id,1,'snippet',repeat('a',64),'UNCHECKED'"
    " FROM research_runs r,sources s LIMIT 1",
    "INSERT INTO revisions (id,run_id,version,report_markdown,report_hash,evidence_watermark,"
    "created_at,report_document)"
    " SELECT gen_random_uuid(),id,1,'# report [1]',repeat('b',64),1,now(),'{\"schema_version\":1}'::json"
    " FROM research_runs LIMIT 1",
    "INSERT INTO claims (id,revision_id,run_id,position,text,extraction_method,verification_state,"
    "verification_method)"
    " SELECT gen_random_uuid(),v.id,r.id,0,'a claim','DERIVED_FROM_REPORT','UNCHECKED','NOT_RUN'"
    " FROM revisions v,research_runs r LIMIT 1",
    "INSERT INTO claim_evidence_links (id,run_id,claim_id,evidence_id,stance,origin)"
    " SELECT gen_random_uuid(),r.id,c.id,e.id,'SUPPORTS','CITATION_MARKER'"
    " FROM research_runs r,claims c,evidence e LIMIT 1",
    "INSERT INTO reviews (id,run_id,sequence,revision_id,reviewer_id,gate,decision,reviewed_hash,created_at)"
    " SELECT gen_random_uuid(),r.id,1,v.id,u.id,'REPORT','APPROVED',v.report_hash,now()"
    " FROM research_runs r,revisions v,users u LIMIT 1",
    "INSERT INTO research_artifacts (id,owner_id,run_id,project_id,revision_id,review_id,review_gate,"
    "review_decision,format_version,payload,artifact_hash,demo,created_at)"
    " SELECT gen_random_uuid(),u.id,r.id,p.id,v.id,w.id,'REPORT','APPROVED',1,'{}'::json,"
    "repeat('c',64),false,now()"
    " FROM users u,research_runs r,projects p,revisions v,reviews w LIMIT 1",
    "INSERT INTO contradictions (id,run_id,detection_state,review_state,created_at)"
    " SELECT gen_random_uuid(),id,'NOT_RUN','UNREVIEWED',now() FROM research_runs LIMIT 1",
    "INSERT INTO agent_logs (session_id,event_type,payload,created_at)"
    " SELECT id,'agent_log','{}'::json,now() FROM sessions LIMIT 1",
    "INSERT INTO audit_events (actor_id,action,subject_type,subject_id,metadata,occurred_at)"
    " SELECT u.id,'review.approved','research_run',r.id,'{}'::json,now()"
    " FROM users u,research_runs r LIMIT 1",
    "INSERT INTO audit_log (session_id,user_id,action,draft_hash,created_at)"
    " SELECT s.id,u.id,'approved',repeat('d',64),now() FROM sessions s,users u LIMIT 1",
    "INSERT INTO chat_threads (id,project_id,title,created_at,last_message_at)"
    " SELECT gen_random_uuid(),id,'thread',now(),now() FROM projects LIMIT 1",
    # A thread-parented message: the row `0008`'s downgrade deliberately deletes, because a
    # narrowed `chat_messages.session_id` has nowhere to put it.
    "INSERT INTO chat_messages (id,thread_id,role,content,created_at)"
    " SELECT gen_random_uuid(),id,'user','hello',now() FROM chat_threads LIMIT 1",
    "INSERT INTO chat_messages (id,session_id,role,content,created_at)"
    " SELECT gen_random_uuid(),id,'user','hello',now() FROM sessions LIMIT 1",
    "INSERT INTO refresh_tokens (id,user_id,token_hash,expires_at)"
    " SELECT gen_random_uuid(),id,repeat('e',64),now() FROM users LIMIT 1",
)

#: Project memory indexed from a **session**, which is what the pre-0022 foreign key can
#: express. 768 dimensions, matching the column.
_SESSION_SOURCED_MEMORY = (
    "INSERT INTO memory_chunks (id,project_id,source_report_id,chunk_index,text,embedding,"
    "embedding_model,created_at)"
    " SELECT gen_random_uuid(),p.id,s.id,0,'remembered',"
    "array_fill(0.1::real, ARRAY[768])::vector,'fake:embed',now()"
    " FROM projects p,sessions s LIMIT 1"
)

#: The same row sourced from a **run** — legitimate, and the state `0022` exists to permit.
_RUN_SOURCED_MEMORY = _SESSION_SOURCED_MEMORY.replace("sessions s", "research_runs s")

#: The *other* polymorphic column with the same property. `agent_logs.session_id` names a
#: `sessions.id` or a `research_runs.id` (`AGENTS.md` — an FK can only point at one), and
#: `0018_agent_logs_polymorphic`'s downgrade reinstates the foreign key to `sessions`. A run's
#: trace row cannot satisfy it, exactly as a run-sourced memory chunk cannot satisfy `0022`'s.
#: Kept out of the compatible set for that reason, not overlooked.
_RUN_SOURCED_AGENT_LOG = (
    "INSERT INTO agent_logs (session_id,event_type,payload,created_at)"
    " SELECT id,'COMPLETED','{}'::json,now() FROM research_runs LIMIT 1"
)


def _populate(dsn: str, *extra: str) -> None:
    import psycopg

    with psycopg.connect(_sync_dsn(dsn, SCRATCH_DB), connect_timeout=5) as conn:
        for statement in (*_COMPATIBLE_ROWS, *extra):
            conn.execute(statement)
        conn.commit()


# ── The defect this file was written for ─────────────────────────────────────────


def test_0008_downgrades_the_constraint_it_actually_created(scratch_db):
    """Upgrade to `0008_chat_threads`, then reverse exactly that revision.

    Isolated to one step on purpose: the whole-chain tests below would also catch this, but
    they would report "the chain is broken" where this reports which revision and why. The
    upgrade names the constraint `one_parent` and lets the metadata convention render it;
    the downgrade passed the rendered name back in, and the convention rendered it again."""
    assert alembic(scratch_db, "upgrade", CHAT_THREADS).returncode == 0

    constraints = {
        row[0]
        for row in _query(
            scratch_db,
            "SELECT conname FROM pg_constraint"
            " WHERE conrelid='chat_messages'::regclass AND contype='c'",
        )
    }
    assert "ck_chat_messages_one_parent" in constraints, (
        f"the upgrade did not create the constraint this test is about: {constraints}"
    )

    result = alembic(scratch_db, "downgrade", "-1")

    assert result.returncode == 0, (
        "0008's downgrade failed — the name it drops is not the name it created:\n"
        + result.stderr[-1500:]
    )
    assert "chat_threads" not in _tables(scratch_db)


# ── Scenario A: a compatible populated database, all the way down and back ───────


def test_a_populated_database_survives_a_full_round_trip(scratch_db):
    """head → populate → base → head, with a realistic row in every table.

    The assertion is not merely that the commands exit zero: an empty database would pass
    that while proving nothing about `DROP COLUMN` on rows that exist, about the foreign-key
    order the drops have to respect, or about `0008` deleting the chat messages that cannot
    survive a narrowed parent column."""
    assert alembic(scratch_db, "upgrade", "head").returncode == 0
    _populate(scratch_db, _SESSION_SOURCED_MEMORY)

    populated = {
        table: _query(scratch_db, f"SELECT count(*) FROM {table}")[0][0]  # noqa: S608 - fixed names
        for table in ("users", "research_runs", "revisions", "memory_chunks", "chat_messages")
    }
    assert all(populated.values()), f"nothing to reverse — populate did nothing: {populated}"

    down = alembic(scratch_db, "downgrade", "base")
    assert down.returncode == 0, (
        "a populated database could not be reversed to base:\n" + down.stderr[-2000:]
    )
    assert down.stderr.count("Running downgrade") == 27, (
        f"expected all 27 revisions to reverse, saw {down.stderr.count('Running downgrade')}"
    )
    assert _tables(scratch_db) <= {"alembic_version"}, "base still holds application tables"

    up = alembic(scratch_db, "upgrade", "head")
    assert up.returncode == 0, "the chain would not go back up:\n" + up.stderr[-2000:]
    assert len(_tables(scratch_db)) == 24


# ── Scenario B: the data-dependent boundary at 0022 ──────────────────────────────


def test_a_run_sourced_memory_chunk_refuses_the_0022_downgrade(scratch_db):
    """The refusal is correct, and it must be clean.

    `0022` reinstates `memory_chunks.source_session_id → sessions(id)`. A chunk indexed from
    a run cannot satisfy it, and the migration's own comment says failing there is the right
    answer — the alternative is a foreign key that lies about what the column holds.

    What this test is really about is the *aftermath*. A downgrade that got halfway before
    refusing would leave a schema no version pointer describes, which is how a database
    becomes unrecoverable. PostgreSQL's transactional DDL means it does not, and that is
    worth asserting rather than assuming."""
    assert alembic(scratch_db, "upgrade", "head").returncode == 0
    _populate(scratch_db, _RUN_SOURCED_MEMORY)

    before = _snapshot(scratch_db)
    assert before["memory_chunks"] == 1

    result = alembic(scratch_db, "downgrade", "base")

    assert result.returncode != 0, (
        "0022's downgrade accepted a run-sourced memory chunk — the reinstated foreign key "
        "would then be claiming those rows point at `sessions`, which they do not"
    )
    assert "fk_memory_chunks_source_session_id_sessions" in result.stderr
    assert "ForeignKeyViolationError" in result.stderr

    after = _snapshot(scratch_db)
    assert after == before, (
        "the refused downgrade did not leave the database as it found it — a partially "
        f"applied downgrade is unrecoverable:\n  before {before}\n  after  {after}"
    )


def test_the_0022_boundary_is_about_the_data_and_not_the_migration(scratch_db):
    """The same revision reverses cleanly when no run has been indexed.

    Without this, the test above would be equally satisfied by `0022` being unreversible
    under all conditions — and it is not. That distinction is the whole reason `0022` sits
    in a different registry from `0006` and `0013`."""
    assert alembic(scratch_db, "upgrade", "head").returncode == 0
    _populate(scratch_db, _SESSION_SOURCED_MEMORY)

    result = alembic(scratch_db, "downgrade", MEMORY_POLYMORPHIC + "-1")

    assert result.returncode == 0, (
        "0022 refused a database whose memory came only from sessions, which the "
        "reinstated foreign key can express:\n" + result.stderr[-1500:]
    )
    columns = {
        row[0]
        for row in _query(
            scratch_db,
            "SELECT column_name FROM information_schema.columns WHERE table_name='memory_chunks'",
        )
    }
    assert "source_session_id" in columns and "source_report_id" not in columns


# ── The other data-dependent boundary: 0018, and it is symmetric with 0022 ───────


def test_a_run_sourced_agent_log_refuses_the_0018_downgrade(scratch_db):
    """`agent_logs.session_id` is the other polymorphic column, and it behaves identically.

    Found by Scenario A, not by inspection: R1's whole-chain attempt stopped at `0022` and
    never reached this revision, so the first run of the compatible round-trip is what
    surfaced it. `0018`'s downgrade reinstates `fk_agent_logs_session_id_sessions`, and a
    trace row belonging to a run names `research_runs` — the same refusal, for the same
    reason, on the other half of the pair `AGENTS.md` names."""
    assert alembic(scratch_db, "upgrade", "head").returncode == 0
    _populate(scratch_db, _RUN_SOURCED_AGENT_LOG)

    before = _snapshot(scratch_db)
    assert before["agent_logs"] == 2, "one session row and one run row, or this proves nothing"

    result = alembic(scratch_db, "downgrade", "base")

    assert result.returncode != 0, (
        "0018's downgrade accepted a run's trace row — the reinstated foreign key would then "
        "be claiming it points at `sessions`, which it does not"
    )
    assert "fk_agent_logs_session_id_sessions" in result.stderr
    assert "ForeignKeyViolationError" in result.stderr
    assert _snapshot(scratch_db) == before, (
        "the refused downgrade did not leave the database as it found it"
    )


def test_the_0018_boundary_is_about_the_data_and_not_the_migration(scratch_db):
    """The positive control: session-sourced trace rows reverse cleanly, and the foreign key
    comes back. Without this, the test above is equally satisfied by `0018` being broken."""
    assert alembic(scratch_db, "upgrade", "head").returncode == 0
    _populate(scratch_db)  # the compatible set: agent_logs from a session only

    result = alembic(scratch_db, "downgrade", AGENT_LOGS_POLYMORPHIC + "-1")

    assert result.returncode == 0, (
        "0018 refused a database whose trace rows all belong to sessions, which the "
        "reinstated foreign key can express:\n" + result.stderr[-1500:]
    )
    restored = _query(
        scratch_db,
        "SELECT conname FROM pg_constraint WHERE conrelid='agent_logs'::regclass AND contype='f'",
    )
    assert "fk_agent_logs_session_id_sessions" in {row[0] for row in restored}, (
        f"the foreign key was not reinstated: {restored}"
    )


def test_both_data_dependent_boundaries_are_declared():
    """The registry and this file cannot drift apart: every migration declared as
    data-dependent is characterised here, in both directions."""
    from tests.task.test_migration_downgrade_policy import DATA_DEPENDENT_DOWNGRADE

    assert set(DATA_DEPENDENT_DOWNGRADE) == {AGENT_LOGS_POLYMORPHIC, MEMORY_POLYMORPHIC}, (
        "a data-dependent boundary was declared without a refusal test and a positive "
        "control, or one here is no longer declared"
    )
