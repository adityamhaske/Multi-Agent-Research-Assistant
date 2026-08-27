"""
What the product refuses, and why — stated once, in the product's own terms.

**Not HTTP.** A use case knows that a run belongs to someone else, or that a gate is not
pending, or that this host has no project memory. It does not know whether that reaches a
client as `404`, as a gRPC status, or as an exception in a library caller. Deciding here
would make the application layer import one delivery mechanism — which is precisely what
`tests/workflow/test_layer_boundaries.py` refuses, and what stopped `app/api/v1/runs.py`
from being movable: it raised `HTTPException` at 13 sites while *both* hosts called it.

The mapping to a status code lives in `app/services/error_responses.py`, which both hosts
install. One table, so a status can only change in one place, and so the question "what
does this product return when a run is not yours?" has an answer you can read rather than
grep for.

Nothing here may import FastAPI, the host, or anything under `desktop/`.
"""

from __future__ import annotations


class AppError(Exception):
    """A refusal the product means, as opposed to a crash it did not.

    `detail` is written for the person who will read it in the interface — `AGENTS.md`
    requires that a guard which fires says which one and by how much, and a bare
    "bad request" forces a source read to learn what happened.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFound(AppError):
    """The thing does not exist, **or is not yours**.

    Deliberately one error for both. Distinguishing them would confirm that a run exists to
    someone who cannot read it, which is a disclosure the product does not need to make —
    `research.py::_authorized_session` and `runs.py::_run_or_404` have always answered 404
    rather than 403, and the parity suite asserts it on both hosts.
    """


class Conflict(AppError):
    """The request is well-formed and the current state refuses it.

    The gates are the reason this exists: resuming a thread that is not suspended at the
    matching interrupt pushes a plan-shaped payload into whichever interrupt is pending,
    and `hitl_gate_node` reads a missing `approved` key as a rejection — silently counting
    a rework nobody asked for.
    """


class Invalid(AppError):
    """The caller's input cannot be honoured — an unroutable model, an empty task list.

    Distinct from FastAPI's own body validation, which rejects a malformed *shape* before
    any of this runs and answers 422. This is a well-shaped request the domain refuses.
    """


class Unprocessable(AppError):
    """Well-formed, understood, and semantically refused — answered `422`.

    `Invalid` and `Unprocessable` both mean "the domain will not accept this", and they are
    two errors only because the product already answers two codes: the run surface has
    always used `422` for an unknown depth, an unroutable model or an emptied task list,
    while the corpus surface uses `400`. Phase 4 is a refactor, so it preserves both rather
    than picking one — unifying them is a client-visible contract change and needs its own
    decision, recorded as a follow-up in the plan.
    """


class PayloadTooLarge(AppError):
    """Well-formed, and simply too big to accept."""


class DependencyUnavailable(AppError):
    """Something the product needs is not reachable right now — an embedding server, a
    provider. Not the caller's mistake, and the difference between "fix your file" and
    "try again later" is the whole value of separating it from `Invalid`."""


class CapabilityUnavailable(AppError):
    """This host does not have the feature, by product design.

    Project memory is pgvector-only; server-side PDF is not in the desktop bundle. A `404`
    would say "you asked wrong" and a `500` would say "we broke"; both are false. The
    `capability` field is what lets a client branch on *which* thing is absent rather than
    parsing prose, and it is what makes a capability difference observable instead of a
    claim in a table.
    """

    def __init__(self, detail: str, *, capability: str) -> None:
        super().__init__(detail)
        self.capability = capability
