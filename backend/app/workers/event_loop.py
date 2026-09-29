"""One event loop per Celery worker process, shared by every task the process runs.

Each task used to open and close a loop of its own. The loop closed; what the task had bound
to it did not. Provider SDKs keep their HTTP client process-wide — `langchain_openai` and
`langchain_anthropic` each cache one async client per base URL — and the keep-alive
connections pooled inside it belong to the loop that opened them. The next task in the same
prefork child then reused or expired one of those connections on a closed loop, so a gated
run's plan approval, routinely handed to the child that ran its start, failed on its first
model call with `RuntimeError: Event loop is closed` (openai 3 raises it; 2.x retried it
away, sending the request twice, as anthropic still does). Keeping the loop for the life of
the process keeps every such cache valid — including ones in libraries not adopted yet —
without reaching into any library's private names.

What a per-task loop did besides closing is kept. Anything a task leaves running is cancelled
and awaited before `run` returns, so nothing outlives the task that spawned it; and each task
starts from a fresh copy of the caller's context, so one run's bound log identity or run
config never reaches the next. The per-task `engine.dispose()` and Redis pool lifecycle in
the task bodies stay as they are — correct on one loop as on many.

The server worker is the only process that runs more than one top-level coroutine. The API
and the desktop sidecar each live on one uvicorn loop, and the CLI and evals run once per
process, so none of them needs this.
"""

from __future__ import annotations

import asyncio
import contextvars
import os
from collections.abc import Coroutine
from typing import Any, TypeVar

_T = TypeVar("_T")

_runner: asyncio.Runner | None = None
_runner_pid: int | None = None


def _process_runner() -> asyncio.Runner:
    global _runner, _runner_pid
    # A runner inherited through fork wraps the parent's selector; the child needs its own.
    if _runner is None or _runner_pid != os.getpid():
        # `loop_factory` keeps the runner from installing its loop as the thread's current
        # one — nothing here reads it, and a test process has its own loop management.
        _runner = asyncio.Runner(loop_factory=asyncio.new_event_loop)
        _runner_pid = os.getpid()
    return _runner


def run(coro: Coroutine[Any, Any, _T]) -> _T:
    """Run one Celery task's coroutine to completion on this process's loop."""
    runner = _process_runner()
    root: list[asyncio.Task] = []

    async def as_root() -> _T:
        root.append(asyncio.current_task())
        return await coro

    try:
        # A fresh copy per task: `asyncio.Runner` otherwise reuses one context for every
        # call, and the log identity bound just before this call would never be seen.
        return runner.run(as_root(), context=contextvars.copy_context())
    finally:
        loop = runner.get_loop()
        if root and not root[0].done():
            _unwind(loop, root[0])
        _cancel_leftovers(loop)


def _unwind(loop: asyncio.AbstractEventLoop, root: asyncio.Task) -> None:
    """Cancel an interrupted task's own coroutine and let it unwind before anything else.

    Celery's soft time limit raises out of the loop from a signal handler, leaving the task's
    coroutine pending mid-await. Cancelling it alone first sends the cancellation down the
    structured path — the fan-out cancels its children, `emit` lets a shielded event write
    land, the driver's `finally` releases its lock and closes its session. Cancelling every
    task at once would also cancel that shielded write directly, cutting a commit in half.
    """
    root.cancel()
    loop.run_until_complete(asyncio.wait([root]))
    if not root.cancelled() and root.exception() is not None:
        loop.call_exception_handler(
            {
                "message": "a Celery task's coroutine raised while unwinding after an interruption",
                "exception": root.exception(),
                "task": root,
            }
        )


def _cancel_leftovers(loop: asyncio.AbstractEventLoop) -> None:
    """Cancel and await whatever the task left running, as a per-task loop's close did."""
    leftovers = [task for task in asyncio.all_tasks(loop) if not task.done()]
    if not leftovers:
        return
    for task in leftovers:
        task.cancel()
    loop.run_until_complete(asyncio.gather(*leftovers, return_exceptions=True))
    for task in leftovers:
        if not task.cancelled() and task.exception() is not None:
            loop.call_exception_handler(
                {
                    "message": "a task left running by a finished Celery task raised",
                    "exception": task.exception(),
                    "task": task,
                }
            )


def shutdown() -> None:
    """Close this process's loop; the next `run` opens a new one."""
    global _runner, _runner_pid
    if _runner is not None and _runner_pid == os.getpid():
        _runner.close()
    _runner = None
    _runner_pid = None
