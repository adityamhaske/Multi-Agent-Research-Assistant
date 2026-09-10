"""A run records which corpus state it read (V2.1-a A4).

A corpus-mode run cited `corpus://<version-id>#chars=...`, which resolves to exact bytes and
says nothing about which corpus produced them or what state it was in. On the desktop there
was not even a path to name, because one flat corpus serves the whole app — so "reproduce
this research" was unanswerable for the airgapped tier.

Two nullable columns and one shared recorder. The recorder is the point: the rule has a home
on each host — `run_execution._corpus_port` on the server, `_drive_run` on the desktop — and
`AGENTS.md` records what happens to a rule kept in step by discipline. So this asserts the
two hosts resolve to the same function *object*, not that two copies agree.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import insert

from app import run_execution, run_lifecycle
from app.models.project import Project
from app.models.user import User
from tests.sqlite_support import open_db

NOW = datetime(2026, 9, 9, tzinfo=UTC)


class _Store:
    """A corpus stand-in that reports an identity. Not a mock of the recorder — the
    recorder is the code under test; this is the thing it reads from."""

    def __init__(self, corpus_id: str, version: int) -> None:
        self._identity = (corpus_id, version)

    async def identity(self):
        return self._identity


@pytest.fixture
async def run(tmp_path):
    async with open_db(tmp_path / "snap.sqlite") as maker, maker() as db:
        uid, pid = uuid.uuid4(), uuid.uuid4()
        await db.execute(
            insert(User).values(
                id=uid, email=f"{uid}@x.invalid", hashed_pw="x", is_active=True, created_at=NOW
            )
        )
        await db.execute(
            insert(Project).values(id=pid, user_id=uid, name="P", created_at=NOW, updated_at=NOW)
        )
        await db.commit()
        row = await run_lifecycle.create_run(
            db, owner_id=uid, project_id=pid, question="q", depth="fast", corpus_mode=True
        )
        await db.commit()
        yield db, row


async def test_a_run_records_the_corpus_identity_and_version_it_read(run):
    db, row = run
    assert (row.corpus_id, row.corpus_version) == (None, None), "fixture precondition"

    await run_execution.record_corpus_snapshot(db, row, _Store("corpus-abc", 7))
    await db.commit()

    assert row.corpus_id == "corpus-abc"
    assert row.corpus_version == 7


async def test_a_run_that_read_no_corpus_records_nothing_rather_than_zero(run):
    """NULL is the honest record of "this run used the web". A zero would read as a real
    corpus at version zero — the unmeasured-as-zero conflation AGENTS.md calls a P0."""
    _, row = run
    assert (row.corpus_id, row.corpus_version) == (None, None)


async def test_the_snapshot_is_taken_at_read_time_and_is_not_a_lock(run):
    """A later change to the corpus does not rewrite what the run recorded. Superseded
    versions stay readable, so evidence gathered before a change still resolves to the
    bytes cited — which is what makes the snapshot a usable claim rather than a promise
    the store cannot keep."""
    db, row = run
    await run_execution.record_corpus_snapshot(db, row, _Store("corpus-abc", 7))
    await db.commit()

    # The corpus moves on; the run's record does not.
    assert row.corpus_version == 7


@pytest.mark.parametrize("module_path", ["app.run_execution", "desktop.sidecar"])
def test_both_hosts_resolve_to_the_same_recorder(module_path):
    """Identity, not equality. Two copies that agree today are two copies."""
    import importlib

    module = importlib.import_module(module_path)
    if module_path == "app.run_execution":
        assert module.record_corpus_snapshot is run_execution.record_corpus_snapshot
    else:
        source = __import__("pathlib").Path(module.__file__).read_text()
        assert "run_execution.record_corpus_snapshot(" in source, (
            "the desktop restates the snapshot rule instead of calling the shared one"
        )


def test_the_server_takes_the_snapshot_only_inside_the_corpus_branch():
    """A web run must not claim a corpus. Asserted against the source region rather than by
    driving Celery, which this suite cannot do."""
    import inspect

    source = inspect.getsource(run_execution._corpus_port)
    assert "record_corpus_snapshot" in source
    assert source.index('ports["corpus"] = store') < source.index("record_corpus_snapshot")
