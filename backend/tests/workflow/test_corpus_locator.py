"""
Where a project's corpus lives has one home per host (parity Phase 5, port P10).

`AGENTS.md` lists corpus path resolution among the behaviours with two homes, and records
that **both were wrong**: "Resolving `corpus_dir` | 2 | 2 — both relative, so upload and run
disagreed." The API and the worker are separate processes with separate working
directories, so each resolved the same relative setting to a different absolute path, and a
document uploaded through one was invisible to the run that needed it.

That was fixed by routing everything through `settings.corpus_path`. What was not fixed is
the number of homes: the server had **eight** `CorpusStore(...)` construction sites and
**seven** places that spelled out `corpus_{project_id}.sqlite` by hand, plus a ninth in
`projects.py` that knows the same filename in order to delete it. The desktop had one.

So the fix held by repetition — every one of those sites happens to say `settings.corpus_path`
today. This makes it structural: one locator per host, behind `app.ports.CorpusLocator`.

The naming convention is the part worth pinning hardest. It is not private: the deletion
path has to reconstruct it, including the SQLite sidecar files, or a deleted project leaves
its documents and embeddings on disk — which contradicts the "no orphan vectors after a
delete" standard `app/models/project.py` itself documents.
"""

from __future__ import annotations

import uuid

import pytest

from app.adapters import ServerCorpusLocator
from app.ports import CorpusLocator


class _Embedder:
    is_local = True
    model_id = "fake:locator"
    dimensions = 8

    async def embed(self, texts):
        return [[0.0] * 8 for _ in texts]


@pytest.fixture
def locator(tmp_path, monkeypatch) -> ServerCorpusLocator:
    from app.config import settings

    monkeypatch.setattr(settings, "corpus_dir", str(tmp_path))
    return ServerCorpusLocator(lambda keys=None: _Embedder())


def test_the_server_locator_satisfies_the_port():
    assert isinstance(ServerCorpusLocator(lambda keys=None: None), CorpusLocator)


async def test_a_project_with_no_corpus_resolves_to_nothing(locator):
    """`None` rather than an empty store, because the two mean different things: report
    scope in chat must not touch the filesystem, and a corpus-mode run with no corpus has
    to fail rather than research nothing."""
    assert await locator.for_project(uuid.uuid4()) is None


async def test_ensure_creates_a_corpus_and_for_project_then_finds_it(locator):
    project_id = uuid.uuid4()
    created = await locator.ensure(project_id)
    assert created is not None
    found = await locator.for_project(project_id)
    assert found is not None


async def test_two_projects_get_two_corpora(locator):
    """Isolation is the whole point of keying the file by project."""
    a, b = uuid.uuid4(), uuid.uuid4()
    await locator.ensure(a)
    assert await locator.for_project(b) is None


async def test_the_same_project_resolves_to_the_same_file_every_time(locator):
    """The bug in the record: two callers resolving the same project to different paths."""
    project_id = uuid.uuid4()
    await locator.ensure(project_id)
    assert locator.path_for(project_id) == locator.path_for(project_id)


def test_deletion_covers_the_sqlite_sidecar_files(locator):
    """WAL and SHM are the corpus too. Removing only `.sqlite` leaves the write-ahead log
    holding rows that were never checkpointed — orphan vectors, in the exact sense
    `app/models/project.py` says must not survive a delete."""
    project_id = uuid.uuid4()
    suffixes = {p.suffix for p in locator.paths_to_delete(project_id)}
    assert suffixes == {".sqlite", ".sqlite-wal", ".sqlite-shm"}


async def test_delete_removes_a_real_corpus_and_leaves_others_alone(locator):
    keep, drop = uuid.uuid4(), uuid.uuid4()
    await locator.ensure(keep)
    await locator.ensure(drop)

    locator.delete(drop)

    assert await locator.for_project(drop) is None
    assert await locator.for_project(keep) is not None


def test_delete_is_quiet_about_a_project_that_never_had_one(locator):
    """Deleting a project is not conditional on it having uploaded anything."""
    locator.delete(uuid.uuid4())


# ── One home ──────────────────────────────────────────────────────────────────────


def test_no_server_module_still_spells_out_the_corpus_filename():
    """The convention is the locator's, and nobody else's.

    Seven modules built `corpus_{project_id}.sqlite` by hand. Each was correct; that is the
    problem — a convention that holds because seven places agree is one edit away from not
    holding, and the last time it drifted, upload and run stopped seeing the same corpus.
    """
    import pathlib

    backend = pathlib.Path(__file__).resolve().parents[2]
    offenders = []
    for path in sorted(backend.glob("app/**/*.py")):
        if path.name == "adapters.py":  # the locator itself
            continue
        text = path.read_text(encoding="utf-8")
        if "corpus_{" in text or 'f"corpus_' in text:
            offenders.append(str(path.relative_to(backend)))
    assert not offenders, (
        f"these modules still know the corpus filename convention: {offenders} — "
        "it belongs to the locator"
    )
