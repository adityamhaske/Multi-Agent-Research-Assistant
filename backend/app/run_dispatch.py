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


class SessionDispatcher(Protocol):
    """Starts and resumes sessions. The same seam as `RunDispatcher`, for the older surface.

    Sessions are the pipeline this product recorded research with before runs, and they are
    not going away: users' history lives there, and follow-up chat scoped to a single report
    exists only there (`AGENTS.md`). What they did not have is this — `app/api/v1/research.py`
    called `app.workers.tasks.*.delay` directly, so there was no way to drive a session
    without a broker.

    That is why the desktop *restates* the whole session journey rather than importing it,
    and why the parity harness can drive a run on both hosts but not a session: the run
    surface has a seam and the session surface did not. Adding it is the first rung of the
    plan's Phase 7 ladder — the baseline that lets the rest be measured.

    Three named operations rather than one `enqueue`, for the reason `RunDispatcher` gives:
    a dispatcher that cannot express "resume from the plan gate" is one that will silently
    do the wrong thing when a new gate is added.
    """

    async def start(self, session_id: str, user_id: str) -> None:
        """Drive a freshly created session from the beginning."""
        ...

    async def resume_plan(self, session_id: str, user_id: str, plan: dict) -> None:
        """Resume a session suspended at the design gate, with the approved plan."""
        ...

    async def resume_review(
        self, session_id: str, user_id: str, approved: bool, feedback: str | None
    ) -> None:
        """Resume a session suspended at the draft gate.

        `approved` is not implied: `True` finalizes, `False` sends the draft back to the
        synthesizer. `RunDispatcher` names its equivalent `rework` because the run surface
        finalizes through a review record instead, and collapsing the two would hide that.
        """
        ...
