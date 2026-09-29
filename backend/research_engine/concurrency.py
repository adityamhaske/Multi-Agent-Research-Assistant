"""Fan-out for graph nodes that never outlives the node.

`asyncio.gather` returns the first exception while every other child keeps running. In a
node that is two defects at once. The orphans keep calling the model for a run that has
already failed — spend the failed node never returns, so no state update can record it. And
they keep writing events through the host's sink after the node has raised: on the server
that sink shares the run driver's database session, which the driver then closes under a
write in flight, and SQLAlchemy's refusal of that close replaced the provider error as the
run's recorded failure reason.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Iterable
from typing import TypeVar

import structlog

logger = structlog.get_logger()

_T = TypeVar("_T")


async def gather_or_cancel(*aws: Awaitable[_T]) -> list[_T]:
    """`asyncio.gather`, except a failure cancels the siblings and waits them out first.

    Results come back in argument order. When a child fails, every unfinished sibling is
    cancelled and awaited, so nothing this call started is still running when the failure
    propagates. What propagates is the earliest failure, as the original exception object,
    since every host records `str(exc)` and a wrapper such as `ExceptionGroup` would put its
    own text there.
    """
    tasks = [asyncio.ensure_future(aw) for aw in aws]
    if not tasks:
        return []
    # Completion order, because the failure worth reporting is the one that happened first:
    # a failing child often breaks what its siblings share (the sink's session, its lock), so
    # a sibling fails as a consequence within the same turn of the loop, and by the time the
    # wait returns both are done. Argument order would report whichever sits earlier.
    finished: list[asyncio.Task] = []
    for task in tasks:
        task.add_done_callback(finished.append)
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
    except asyncio.CancelledError:
        await _cancel_and_wait(tasks)
        raise
    # A child can be done with its callback not yet run; it finished last, so it goes last.
    ordered = finished + [t for t in tasks if t.done() and t not in finished]
    failed = [t for t in ordered if not t.cancelled() and t.exception() is not None]
    if not failed:
        return [t.result() for t in tasks]
    await _cancel_and_wait(tasks)
    first = failed[0]
    for other in tasks:
        # Retrieved so asyncio does not report them as never retrieved, and logged so a
        # second, different failure in the same round is not silently lost.
        if other is not first and not other.cancelled() and other.exception() is not None:
            logger.warning(
                "fan_out_sibling_also_failed",
                error=f"{type(other.exception()).__name__}: {other.exception()}",
            )
    raise first.exception()


async def _cancel_and_wait(tasks: Iterable[asyncio.Task]) -> None:
    pending = [t for t in tasks if not t.done()]
    for task in pending:
        task.cancel()
    # Waited out even if this await is itself cancelled — a worker's soft time limit unwinds
    # the task exactly then — and only then is that cancellation honoured. Giving up the wait
    # would leave the cancelled children finishing their cleanup unawaited. `wait`, not
    # `gather`: it neither re-raises the children's exceptions nor cancels them again.
    interrupted = False
    while pending:
        try:
            await asyncio.wait(pending)
        except asyncio.CancelledError:
            interrupted = True
        pending = [t for t in pending if not t.done()]
    if interrupted:
        raise asyncio.CancelledError
