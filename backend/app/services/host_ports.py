"""
`Depends(...)` providers for the server's implementations of `app.ports` (docs/13 §5.2).

Lives here rather than in `app.adapters` for the same reason `get_run_dispatcher` lives
in `app.workers.dispatch` rather than in `app.run_dispatch`: `app.adapters` imports
`app.db.redis` at module scope, and the routes these providers serve — `projects.py`,
`corpus.py`, `research.py` — are imported by the desktop at *request* time to delegate
to them. An import at module scope here would pull `redis` into the sidecar's
request-time tree, which `research-sidecar.spec` excludes and `test_sidecar_startup.py`'s
`test_lazy_v2_imports_pull_in_no_excluded_package` catches.

Every import below is deferred to the call. The desktop never actually calls these — it
passes its own `CorpusLocator`/`CheckpointDeleter` explicitly to the shared handler, the
same pattern `get_run_dispatcher` documents — so the deferred imports never execute there;
they only need to resolve as names when this module is imported, which is why the module
itself stays clean while its function bodies are not.
"""

from __future__ import annotations

from app.ports import CheckpointDeleter, CorpusLocator, TerminalEventEmitter


def get_corpus_locator() -> CorpusLocator:
    """FastAPI dependency: this deployment's corpus convention.

    A plain `ServerCorpusLocator()` instantiation used to sit inline in route bodies —
    harmless on the server, but it meant those bodies could never run unmodified on a
    host with a different corpus convention. This is the seam: the desktop passes its own
    locator over its one flat store directly, and the route stops knowing which host it is.
    """
    from app.adapters import ServerCorpusLocator

    return ServerCorpusLocator()


def get_checkpoint_deleter() -> CheckpointDeleter:
    """FastAPI dependency: this deployment's way to drop a thread's checkpoint state.

    `checkpoints.delete_thread` already matches `CheckpointDeleter`'s call shape
    (`async (thread_id: str) -> None`), so the server's implementation of the port is
    that function itself — no wrapper class needed, unlike the corpus locator above.
    """
    from app.services import checkpoints

    return checkpoints.delete_thread


def get_terminal_event_emitter() -> TerminalEventEmitter:
    """FastAPI dependency: how this deployment writes and publishes one event outside
    the pipeline's own event flow.

    Reuses `agent_log_sink` rather than restating its write-then-publish-then-attach-id
    ordering a second time — the factory already takes exactly `(db, session_id)`, so
    this just calls the `EventSink` it returns once instead of for a whole run's worth
    of events.
    """
    from app.adapters import agent_log_sink

    async def _emit(db, session_id: str, event: dict) -> None:
        await agent_log_sink(db, session_id)(session_id, event)

    return _emit
