"""
Host ports: the interfaces whose implementations differ per host.

Empty on purpose, like `app/handlers/`. Ports arrive in plan Phase 5, one at a time, each
with both implementations and a stated contract — lifecycle, error semantics, transaction
semantics, concurrency, and how it is tested.

**A port is only justified where the infrastructure genuinely differs.**
`research_engine/ports.py` already argues two candidates down to data (`KeyProvider`) and
to host scheduling (`RunLock`), and that reasoning applies here: persistence is one ORM on
both hosts, so a repository layer over it would be indirection, not a boundary. What does
differ is the event stream, the way a `RunConfig` is built, where secrets live, where a
corpus file is, where routing is stored, and whether project memory exists at all.

Protocols only. Nothing here may import an implementation, on either host.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Protocol, runtime_checkable

from research_engine.ports import Corpus


@runtime_checkable
class CorpusLocator(Protocol):
    """Where a project's corpus lives, and how to open it.

    A genuine host difference: the server keeps one SQLite file per project under
    `settings.corpus_path`, the desktop one `corpus.sqlite` for the whole app. That storage
    decision stays — what must not leak is the *convention*, which the server spelled out in
    seven places and `projects.py` reconstructed an eighth time in order to delete it.
    `AGENTS.md` records the two-home version of this going wrong in both homes at once, so
    that an uploaded document was invisible to the run that needed it.

    `for_project` returns `None` for a project with no corpus, and that is a distinction
    with teeth: report-scoped chat must not touch the filesystem to answer a question about
    a report, and a corpus-mode run with no corpus must fail rather than research nothing.
    `ensure` is the other intent — ingestion creates.

    `keys` are BYOK provider keys for the embedder. They are per-request rather than
    per-locator because a corpus is embedded on whichever key its owner supplied, and two
    concurrent requests must not see each other's.
    """

    async def for_project(
        self, project_id: uuid.UUID, *, keys: dict[str, str] | None = None
    ) -> Corpus | None: ...

    async def ensure(
        self, project_id: uuid.UUID, *, keys: dict[str, str] | None = None
    ) -> Corpus: ...

    def paths_to_delete(self, project_id: uuid.UUID) -> list[Path]:
        """Every file that is part of this corpus, including the SQLite sidecars.

        WAL and SHM are the corpus too: removing only `.sqlite` leaves a write-ahead log
        holding rows that were never checkpointed — orphan vectors, in the sense
        `app/models/project.py` says must not survive a delete.
        """
        ...

    def delete(self, project_id: uuid.UUID) -> None: ...
