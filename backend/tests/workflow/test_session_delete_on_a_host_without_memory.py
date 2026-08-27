"""
Deleting a session must work on a host that has no project memory.

**A live defect, found by driving the desktop rather than reading it.**
`DELETE /research/{session_id}` is in `DESKTOP_UI_CALLS` — "SessionCard — delete" — so it
is a control the desktop build renders. It answered 500:

    sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) no such table: memory_chunks

`Session.memory_chunks` is a relationship with `cascade="all, delete-orphan"` and
`lazy="select"`, so `db.delete(session)` SELECTs the chunk table to cascade into it.
`memory_chunks` is pgvector-backed and excluded from the desktop's schema
(`POSTGRES_ONLY_TABLES`), so the query has nothing to read.

**Why nothing caught it.** `test_host_parity` proves the route *exists* on both hosts.
`test_one_canonical_owner` covers `/runs`, and run deletion goes through
`run_lifecycle.delete_run`, which already asks `memory.is_available(db)` first. No test
deleted a *session* on the desktop, and the two delete paths differ in exactly the place
that matters. This is the class `AGENTS.md` opens on, once more: "a difference nobody
decided on reaches a user as" — here, a 500.

The fix follows `run_lifecycle.delete_run`: the cleanup is explicit and guarded rather than
a cascade that assumes the table exists. The guarantee it protects is unchanged — deleting
a session still takes its indexed text with it, or project chat keeps quoting a report
nobody can open.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
async def desktop():
    from tests.parity.drivers import desktop_driver

    async with desktop_driver(Path(tempfile.mkdtemp()) / "d") as driver:
        yield driver


async def _settled_session(driver) -> str:
    resp = await driver.request(
        "POST",
        "/research",
        json={"query": "What is retrieval-augmented generation?", "depth": "fast"},
    )
    assert resp.status_code == 202, resp.text
    session_id = resp.json()["session_id"]

    deadline = asyncio.get_event_loop().time() + 60
    while asyncio.get_event_loop().time() < deadline:
        detail = await driver.request("GET", f"/research/{session_id}")
        if detail.json()["status"] in ("AWAITING_APPROVAL", "COMPLETED", "FAILED"):
            return session_id
        await asyncio.sleep(0.1)
    raise AssertionError("the session never settled")


async def test_a_session_can_be_deleted_on_a_host_with_no_memory_table(desktop):
    session_id = await _settled_session(desktop)

    resp = await desktop.request("DELETE", f"/research/{session_id}")
    assert resp.status_code == 204, resp.text

    gone = await desktop.request("GET", f"/research/{session_id}")
    assert gone.status_code == 404, "the row must actually be gone, not merely un-erroring"


async def test_deleting_a_session_still_removes_its_chat(desktop):
    """The cascade does more than memory. Weakening it to fix one table would silently
    orphan the rest, and chat messages are the ones a user would notice."""
    from sqlalchemy import func, select

    from app.models.chat_message import ChatMessage

    session_id = await _settled_session(desktop)
    factory = desktop.client._transport.app.state.sidecar["db"]  # noqa: SLF001

    import uuid as _uuid

    async with factory() as db:
        db.add(ChatMessage(session_id=_uuid.UUID(session_id), role="user", content="hello"))
        await db.commit()

    assert (await desktop.request("DELETE", f"/research/{session_id}")).status_code == 204

    async with factory() as db:
        remaining = (
            await db.execute(
                select(func.count())
                .select_from(ChatMessage)
                .where(ChatMessage.session_id == _uuid.UUID(session_id))
            )
        ).scalar_one()
    assert remaining == 0, "deleting a session must take its chat with it"
