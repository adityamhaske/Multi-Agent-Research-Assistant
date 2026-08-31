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


@runtime_checkable
class MemoryIndex(Protocol):
    """Nearest-neighbour search over project memory.

    A port because the *storage* is genuinely host-specific: pgvector on the server, and
    absent on the desktop, where project memory does not exist at all. What is NOT here is
    everything else `app/services/memory.py` does — chunking an approved report, deciding
    which reports count as indexed, the `status` accounting. That is product rule, it runs
    on either dialect, and hiding it behind an interface would obscure it rather than
    isolate anything.

    `available` is read from the port, never re-derived. `memory.is_available(db)` tests
    the SQL dialect, which is a fact about storage standing in for a fact about the
    product; a caller writing its own dialect test is a caller that will disagree with it.

    A host without memory **raises `CapabilityUnavailable`** rather than returning `[]`.
    An empty list says "this project has nothing indexed", which is a different and false
    claim, and it is the shape that makes a missing feature look like a working one.
    """

    @property
    def available(self) -> bool: ...

    async def nearest(
        self,
        db,
        *,
        project_id: uuid.UUID,
        query_vector: list[float],
        embedding_model: str,
        limit: int,
    ) -> list[tuple[object, float]]:
        """`(chunk, distance)` pairs, nearest first, already filtered to this project.

        Both predicates are the caller's isolation boundary and must be applied:
        `project_id` scopes the search, and `embedding_model` keeps vectors written by a
        different model out — they are not comparable to this query vector even at equal
        width, and ranking them together produces confident nonsense rather than an
        obvious error.
        """
        ...


@runtime_checkable
class CheckpointDeleter(Protocol):
    """Drops all checkpoint state for one thread (a session or run id).

    A genuine host difference, and a narrow one: the server opens a fresh
    `AsyncPostgresSaver` connection per call (`app.services.checkpoints.delete_thread`,
    which already matches this exact signature — no wrapper needed); the desktop's saver
    is a single long-lived `AsyncSqliteSaver` already held in `app.state`. Wrapping both
    as one async callable is what let `delete_project` stop hardcoding the server's saver
    directly, the same way `CorpusLocator` let it stop hardcoding the server's corpus
    convention.

    Best-effort by convention, not by the port: both implementations log and continue on
    failure rather than raising, because the row they were cleaning up after is already
    gone by the time this runs — the same reasoning `ServerCorpusLocator.delete` states
    for corpus files.
    """

    async def __call__(self, thread_id: str) -> None: ...


@runtime_checkable
class TerminalEventEmitter(Protocol):
    """Write one durable event, then publish it live — for a route that ends a session
    outside the pipeline's own event flow.

    `research_engine.ports.EventSink` covers events *during* a run, installed once per
    run via `events.set_emitter`; this is the narrower thing a route reaches for after
    the run has already been taken out of the graph's hands. `cancel_session` is the one
    caller: it commits a status change and then has exactly one event left to tell a live
    listener about, and unlike the pipeline's own sink, there is no already-open,
    run-scoped session to bind a lock to — one call, one write, one publish.

    A genuine host difference in more than the transport: the server's implementation
    reuses the caller's `db` session directly (the same reason `agent_log_sink` does);
    the desktop's `persist_and_publish` opens its own scope from a session factory,
    because it is shared with the pipeline's own event flow rather than written only
    for this seam. `db` is still threaded through so both shapes have somewhere to put
    it — the desktop's implementation is free to ignore it.
    """

    async def __call__(self, db, session_id: str, event: dict) -> None: ...
