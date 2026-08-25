"""
Request bodies for the V2 run routes.

**Why these live in `app/schemas/` rather than beside the routes.** The V2 surface has two
hosts — `app/api/v1/v2_runs.py` on the server and `desktop/sidecar.py` on the desktop — and
the desktop host must accept *exactly* the same bodies, so the models are imported rather
than restated (AGENTS.md, "two hosts, one contract").

They used to be imported straight from the server route module, which made the contract
single-homed but reached `app.db.base` → `app.config` on the way, and the desktop host has
no `DATABASE_URL` or `JWT_SECRET_KEY` to build `Settings` with. The packaged sidecar died
at import (#50). Schemas are pure pydantic and depend on nothing host-specific, so this is
where they belong: one home, importable by both hosts, no configuration required.

Nothing in this module may import `app.config`, `app.db`, or anything reaching them.
`tests/test_sidecar_startup.py` fails if that changes.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class CreateRunRequest(BaseModel):
    """The domain entry point for a V2-native run."""

    project_id: uuid.UUID
    question: str = Field(min_length=1, max_length=2000)
    depth: str = Field("balanced", description="fast | balanced | comprehensive")
    corpus_mode: bool = False
    skip_plan_gate: bool = True
    topic_seeds: list | None = None
    outline_template: str | None = None
    #: Per-run routing, one `provider:model` per agent role. `None` means "use whatever
    #: this user's saved preference and the deployment resolve to", which is the existing
    #: behaviour and stays the default — a caller that does not care must not be forced to
    #: name five models.
    #:
    #: Validated in the route rather than here: the check needs the catalog *and*
    #: `app.config`, and nothing in this module may import either (the packaged sidecar
    #: dies at import if it does — issue #50). Typed loosely for the same reason; the
    #: route's `model_routing.validate()` is the authority on shape and providers.
    model_routing: dict[str, str] | None = None
    #: Dispatch the run to the worker. False creates the domain row only — used by tests
    #: that drive the engine in-process, and by any caller that wants to stage a run.
    dispatch: bool = True


class PlanReviewRequest(BaseModel):
    decision: str = Field("APPROVED", description="APPROVED | REWORK_REQUESTED | REJECTED")
    feedback: str | None = None
    #: The reviewer's edited task list, or `None` for "unedited — use what the planner
    #: proposed". `None` and `[]` are deliberately different: the second is a reviewer who
    #: excluded everything, which the route refuses rather than silently treating as "no
    #: edit". An edit is recorded as its own plan version, so the plan a run executed is
    #: the one a later reader sees.
    tasks: list[dict] | None = None
    dispatch: bool = True


class ReportReviewRequest(BaseModel):
    """A decision about a revision. `dispatch` drives the rework resume."""

    revision_version: int | None = Field(
        None, description="Which revision was reviewed. Defaults to the latest."
    )
    decision: str = Field(..., description="APPROVED | REWORK_REQUESTED | REJECTED")
    feedback: str | None = None
    dispatch: bool = True
