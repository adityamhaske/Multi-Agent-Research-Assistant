"""How a research run gets driven, per host.

The *rules* around dispatch are the product contract and live in the route handlers, once:
commit the row before handing it to anything, move a run to RUNNING in the same transaction
as the decision that resumed it, and send a rejected draft back to the synthesizer rather
than re-running the research. What differs per host is only the *mechanism* — the server
hands the run to a Celery worker over Redis; the desktop has neither broker nor worker and
drives it in-process.

This seam exists because the desktop previously had no way to swap that mechanism without
restating the handlers, so it did not swap it at all: `create_run` imported
`app.workers.tasks` whenever `dispatch` was set, and `research-sidecar.spec` **excludes**
`celery`, so the packaged app answered 500 on the one control the product is named after.
Widening the bundle would have been the wrong fix — this host genuinely has no broker; it
needs a different mechanism, not the same one shipped twice.

**The protocol only.** The server's implementation lives in `app/workers/dispatch.py`,
beside the tasks it hands work to; the desktop's is `sidecar::_SidecarDispatcher`. This
module used to hold the protocol *and* the Celery adapter, which meant a file both hosts
import reached `app.workers.tasks` — deferred to the call, and load-bearing that it was,
but still a dependency the desktop layer had no business carrying.
`tests/workflow/test_layer_boundaries.py` recorded it as the one violation it found.

The protocol is deliberately three named operations rather than one `enqueue(task, *args)`:
a dispatcher that cannot express "resume from the plan gate" is one that will silently do
the wrong thing when a new gate is added.
"""

from __future__ import annotations

from typing import Protocol


class RunDispatcher(Protocol):
    """Starts and resumes research runs. One implementation per host."""

    async def start(self, run_id: str, user_id: str) -> None:
        """Drive a freshly created run from the beginning."""
        ...

    async def resume_plan(self, run_id: str, user_id: str, plan: dict) -> None:
        """Resume a run suspended at the design gate, with the approved plan."""
        ...

    async def rework(self, run_id: str, user_id: str, feedback: str | None) -> None:
        """Resume a run whose draft was rejected, back into synthesis."""
        ...
