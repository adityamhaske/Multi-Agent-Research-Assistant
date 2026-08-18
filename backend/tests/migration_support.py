"""
Shared scaffolding for the M2E migration tests. **Not a test module.**

Everything here builds a *disposable* SQLite database and a fake checkpoint saver. No
function in this file reads `DATABASE_URL`, opens a Postgres connection, or writes anything
outside the pytest `tmp_path` it is handed — which is the property that lets the migration
dry-run be exercised without going anywhere near production.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import event, insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import POSTGRES_ONLY_TABLES, Base
from app.models.agent_log import AgentLog
from app.models.audit_log import AuditLog
from app.models.project import Project
from app.models.session import Session, SessionStatus
from app.models.user import User
from research_engine.graph import _number_sources

REPORT = (
    "# Findings\n\nRecall improved by twelve points on the benchmark [1]. "
    "A second sentence that also carries a marker [2].\n\n## Sources\n\n1. https://e.org/a\n"
)
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
#: Evidence the executor recorded with no URL at all. `_number_sources` skips it,
#: `group_snippets_by_source` skips it, and no other V1 location records an identity for
#: it — so it is the one source case that stays non-migratable (M2F Amendment §6.3).
EVIDENCE_NO_URL = [
    {"task_id": 1, "source_url": "", "source_title": "", "snippet": "orphaned", "key_fact": "x"}
]
CONTRADICTIONS = [
    {
        "source_a": "https://e.org/a",
        "source_b": "https://e.org/b",
        "claim_a": "recall rose",
        "snippet_a": "Recall improved by twelve points.",
        "claim_b": "recall fell",
        "snippet_b": "",
        "nature": "the two measurements cannot both describe the same benchmark",
    }
]
PLAN = [{"id": 1, "query": "q", "rationale": "r"}]

#: V1's `sessions.sources` is not free-form JSON — `graph._number_sources` writes it, from
#: the evidence list, at synthesis time. Deriving the fixture the same way is what makes
#: bundle equivalence a real measurement: a hand-written source list that no V1 code path
#: could have produced would make the comparison test its own fixture rather than the
#: migration.
SOURCES = _number_sources(EVIDENCE)[0]


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


@asynccontextmanager
async def open_db(path):
    """Open one disposable SQLite database at `path`, schema built from the ORM.

    A context manager rather than only a fixture because some tests need **two independent
    databases** at once — see the deterministic-identity test, whose whole point is that
    there is no shared primary key to collide on.
    """
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")

    @event.listens_for(engine.sync_engine, "connect")
    def _fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    tables = [t for t in Base.metadata.sorted_tables if t.name not in POSTGRES_ONLY_TABLES]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield maker
    finally:
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
    ids=None,
    plan=None,
    trace=(),
    demo=False,
    routing=None,
    descending_audit_times=False,
):
    """Insert one representative V1 session (plus its user, project, audit and trace rows).

    `ids` pins the identity so the same V1 source can be seeded into two databases.
    """
    now = datetime(2026, 8, 17, 12, 0, tzinfo=UTC) if ids else datetime.now(UTC)
    uid, pid, sid = ids or (uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
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
            demo=demo,
            skip_plan_gate=False,
            error_message=error,
            model_routing=routing,
            plan_json=({"tasks": plan} if plan else None),
            outline_json=({"sections": ["Findings"]} if plan else None),
            created_at=now,
            updated_at=now,
        )
    )
    for i, (action, h) in enumerate(audits):
        await db.execute(
            insert(AuditLog).values(
                session_id=sid,
                user_id=uid,
                action=action,
                feedback=None,
                draft_hash=h,
                # Distinct timestamps: V2 has no per-run review ordinal, so `reviews` can
                # only be ordered by (created_at, id). Two reviews sharing a timestamp are
                # a genuine ordering ambiguity, recorded as a limitation rather than
                # papered over here.
                # Descending on request: a later `audit_log.id` with an EARLIER timestamp,
                # so ordering by `created_at` gives a different answer from ordering by
                # decision order. V1 guarantees no distinctness or monotonicity here.
                created_at=(
                    now - timedelta(seconds=i)
                    if descending_audit_times
                    else now + timedelta(seconds=i)
                ),
            )
        )
    for payload in trace:
        await db.execute(
            insert(AgentLog).values(
                session_id=sid,
                event_type=payload.get("event", "node_finished"),
                agent_name=payload.get("agent"),
                payload=payload,
                created_at=now,
            )
        )
    await db.commit()
    return sid
