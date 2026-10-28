"""
The legacy corpus move survives a failure at every step (RFC V3.1 §7.3, §16; AC-37).

`test_desktop_legacy_corpus_migration` covers one crash on each side of the commit. This
injects a failure at every step boundary of the move:
- a process killed at the boundary, modelled by an exception no handler catches;
- the disk filling during the store copy;
- a backup damaged between being written and being checked.

After each one the app is started again with nothing injected, and the same invariants are
asserted every time:
- **While the layout is still `shared`, the shared store is the only one any project sees.**
  No "Documents from before 3.1" project exists yet, so no second store is reachable.
- **No document is lost:** the moved store and the backup each reconcile with the original
  on `(id, doc_key, version, sha256, superseded_at)`.
- **The recovery finishes:** one later launch completes the move.
"""

from __future__ import annotations

import sqlite3

import pytest

from desktop import corpus_layout
from tests.workflow.test_desktop_legacy_corpus_migration import _launch, _legacy_store, _rows


class Killed(BaseException):
    """The process ending at this line: not an `Exception`, so no handler intercepts it."""


def _die_on_call(monkeypatch, name: str, nth: int, error: BaseException) -> None:
    """Make the `nth` call to `corpus_layout.<name>` raise `error` instead of running."""
    real = getattr(corpus_layout, name)
    calls = {"n": 0}

    def wrapper(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == nth:
            raise error
        return real(*args, **kwargs)

    if name == "_set_meta":

        async def async_wrapper(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == nth:
                raise error
            return await real(*args, **kwargs)

        monkeypatch.setattr(corpus_layout, name, async_wrapper)
    else:
        monkeypatch.setattr(corpus_layout, name, wrapper)


#: (step boundary, function, which call, what happens there). The calls are counted in the
#: order `migrate_legacy_corpus` makes them: `_backup` 1 is the backup and 2 the project
#: store, `verify_copy` 1 checks the backup and 2 the store, `_set_meta` 1 is the commit.
BOUNDARIES = [
    ("killed while writing the backup", "_backup", 1, Killed()),
    ("killed before the backup is checked", "verify_copy", 1, Killed()),
    ("killed while building the project store", "_backup", 2, Killed()),
    ("killed before the project store is checked", "verify_copy", 2, Killed()),
    ("killed before the commit", "_set_meta", 1, Killed()),
    (
        "disk full during the store copy",
        "_backup",
        2,
        sqlite3.OperationalError("database or disk is full"),
    ),
    ("killed before the shared store is retired", "_remove", 2, Killed()),
]


@pytest.mark.parametrize("where,name,nth,error", BOUNDARIES, ids=[b[0] for b in BOUNDARIES])
async def test_a_failure_at_each_step_is_recovered_by_the_next_launch(
    tmp_path, monkeypatch, where, name, nth, error
):
    before = await _legacy_store(tmp_path)
    _die_on_call(monkeypatch, name, nth, error)

    try:
        projects, docs, warning = await _launch(tmp_path)
    except Killed:
        projects = None
    else:
        # A failure the app survives keeps the shared layout and says why.
        assert warning, where
        assert corpus_layout.LEGACY_PROJECT_NAME not in projects, where
        assert docs["General"] == sorted(i for i, _ in before), "still served from the shared store"
    if (tmp_path / corpus_layout.LEGACY_FILENAME).exists():
        assert _rows(tmp_path / corpus_layout.LEGACY_FILENAME) == before, "the live store untouched"

    monkeypatch.undo()
    projects, docs, warning = await _launch(tmp_path)

    assert warning is None, (where, warning)
    legacy = [n for n in projects if n.startswith(corpus_layout.LEGACY_PROJECT_NAME)]
    assert legacy == [corpus_layout.LEGACY_PROJECT_NAME], (where, legacy)
    assert docs[corpus_layout.LEGACY_PROJECT_NAME] == sorted(i for i, _ in before)
    assert all(ids == [] for n, ids in docs.items() if n != corpus_layout.LEGACY_PROJECT_NAME)
    moved = (
        tmp_path / "corpus" / f"corpus_{projects[corpus_layout.LEGACY_PROJECT_NAME]['id']}.sqlite"
    )
    assert _rows(moved) == before, "no document lost or altered"
    assert _rows(tmp_path / corpus_layout.BACKUP_FILENAME) == before
    assert not (tmp_path / corpus_layout.LEGACY_FILENAME).exists()


def _damage_backups(monkeypatch, times: int) -> None:
    """Corrupt the backup just before each of its first `times` checks."""
    real_verify = corpus_layout.verify_copy
    left = {"n": times}

    def damage_then_check(original, copy):
        if left["n"] and copy.name == corpus_layout.BACKUP_FILENAME:
            left["n"] -= 1
            with copy.open("r+b") as fh:
                fh.seek(4096)
                fh.write(b"\x00" * 4096)
        return real_verify(original, copy)

    monkeypatch.setattr(corpus_layout, "verify_copy", damage_then_check)


async def test_a_backup_damaged_before_its_check_is_made_again(tmp_path, monkeypatch):
    """Until the commit the shared store is the authority, so a backup that never passed its
    check is rebuilt from it, not reused and refused on every launch for ever."""
    before = await _legacy_store(tmp_path)
    _damage_backups(monkeypatch, times=1)

    projects, docs, warning = await _launch(tmp_path)

    assert warning is None, warning
    assert docs[corpus_layout.LEGACY_PROJECT_NAME] == sorted(i for i, _ in before)
    assert _rows(tmp_path / corpus_layout.BACKUP_FILENAME) == before


async def test_a_backup_that_fails_twice_refuses_and_a_later_launch_finishes(tmp_path, monkeypatch):
    before = await _legacy_store(tmp_path)
    _damage_backups(monkeypatch, times=2)

    projects, docs, warning = await _launch(tmp_path)
    assert warning and "malformed" in warning
    assert corpus_layout.LEGACY_PROJECT_NAME not in projects
    assert docs["General"] == sorted(i for i, _ in before), "still served from the shared store"
    assert _rows(tmp_path / corpus_layout.LEGACY_FILENAME) == before

    monkeypatch.undo()
    projects, docs, warning = await _launch(tmp_path)
    assert warning is None, warning
    assert docs[corpus_layout.LEGACY_PROJECT_NAME] == sorted(i for i, _ in before)
    assert _rows(tmp_path / corpus_layout.BACKUP_FILENAME) == before
