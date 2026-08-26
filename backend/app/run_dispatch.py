"""How a research run gets driven, per host.

The *rules* around dispatch are the product contract and live in the route handlers, once:
commit the row before handing it to anything, move a run to RUNNING in the same transaction
as the decision that resumed it, and send a rejected draft back to the synthesizer rather
than re-running the research. What differs per host is only the *mechanism* — the server
hands the run to a Celery worker over Redis; the desktop has neither broker nor worker and
drives it in-process.

This seam exists because the desktop previously had no way to swap that mechanism without
restating the handlers, so it did not swap it at all: `create_run` imports
`app.workers.tasks` whenever `dispatch` is set, and `research-sidecar.spec` **excludes**
`celery`, so the packaged app answered 500 on the one control the product is named after.
Widening the bundle would have been the wrong fix — this host genuinely has no broker; it
needs a different mechanism, not the same one shipped twice.

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


class CeleryDispatcher:
    """The server's mechanism: hand the run to a worker over the broker.

    Every import is deferred to the call. `app.workers.tasks` pulls in Celery and the whole
    pipeline module tree, and this module is imported by the run routes on *both* hosts — an
    import at module scope here would reintroduce the packaged-app `ModuleNotFoundError`
    this seam exists to remove.
    """

    async def start(self, run_id: str, user_id: str) -> None:
        from app.workers.tasks import run_research_pipeline

        run_research_pipeline.delay(run_id, user_id)

    async def resume_plan(self, run_id: str, user_id: str, plan: dict) -> None:
        from app.workers.tasks import resume_research_plan_gate

        resume_research_plan_gate.delay(run_id, user_id, plan)

    async def rework(self, run_id: str, user_id: str, feedback: str | None) -> None:
        from app.workers.tasks import resume_research_pipeline

        resume_research_pipeline.delay(run_id, user_id, False, feedback)


def get_run_dispatcher() -> RunDispatcher:
    """FastAPI dependency: the mechanism this deployment uses.

    The server resolves it through `Depends`. The desktop sidecar calls the same handler
    functions directly and passes its own dispatcher explicitly — the pattern it already
    uses for `db` and `user`, so nothing about the handler changes shape per host.
    """
    return CeleryDispatcher()
