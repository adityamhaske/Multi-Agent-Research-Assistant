"""
The one place a domain refusal becomes an HTTP status, for both hosts.

Separate from `app/errors.py` on purpose, and the split is the point: the taxonomy is what
the product means and belongs in the domain, while `404` is how one delivery mechanism says
it. Same shape as `app/services/document_headers.py` and `app/services/sse.py` — shared
transport policy, in a module both hosts import, with the reasoning attached.

Both hosts install `install_error_handlers`, and
`tests/workflow/test_error_contract_has_one_home.py` asserts they install *the same
function object*, not two that agree today.

FastAPI and stdlib only. Nothing here may import `app.config`, `app.db` or anything
reaching them, or the packaged sidecar dies at import (#50).
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from app.errors import (
    AppError,
    CapabilityUnavailable,
    Conflict,
    DependencyUnavailable,
    Invalid,
    NotFound,
    PayloadTooLarge,
    Unprocessable,
)

#: The whole status contract, in one table.
#:
#: Keyed by class rather than by class *name*: a rename would otherwise be a silent status
#: change, which is the kind of edit that looks safe in review.
ERROR_STATUS: dict[type[AppError], int] = {
    NotFound: 404,
    Conflict: 409,
    Invalid: 400,
    Unprocessable: 422,
    PayloadTooLarge: 413,
    DependencyUnavailable: 503,
    CapabilityUnavailable: 501,
}

#: What an unmapped error becomes. 500 rather than a friendlier default, because an error
#: nobody assigned a status is a bug in this table, and a refusal that presents as a
#: successful-looking 4xx would hide it.
UNMAPPED_STATUS = 500


def status_for(exc: AppError) -> int:
    """The status for this error, honouring subclasses.

    Walks the MRO so a future `RunNotFound(NotFound)` inherits `404` without an entry —
    a subclass that means something narrower should not have to restate the contract.
    """
    for cls in type(exc).__mro__:
        if cls in ERROR_STATUS:
            return ERROR_STATUS[cls]
    return UNMAPPED_STATUS


def error_body(exc: AppError) -> dict:
    """`{"detail": ...}` — the shape every client in this product already reads.

    `detail` is FastAPI's own key for `HTTPException`, so this is deliberately not a new
    envelope: the frontend's `ApiError` reads `err.detail`, and changing the shape would be
    a client rewrite in exchange for nothing.
    """
    body = {"detail": exc.detail}
    if isinstance(exc, CapabilityUnavailable):
        # Machine-readable, so a client can branch on *which* capability is absent instead
        # of matching prose.
        body["capability"] = exc.capability
    return body


async def _handle(_request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=status_for(exc), content=error_body(exc))


def install_error_handlers(app) -> None:
    """Teach one FastAPI app to translate domain refusals. Called by both hosts.

    **Any app that mounts `app/api/v1/runs.py` must call this.** Those handlers raise
    domain errors, so without the translation every refusal surfaces as an unhandled 500 —
    a 404 for someone else's run would read as a crash. `test_error_contract_has_one_home`
    asserts both real hosts install it; a third mounting site is on its own, which is the
    one cost of moving the status out of the handlers.
    """
    app.add_exception_handler(AppError, _handle)


#: Exposed so a test can assert both hosts registered *this* handler rather than each
#: having some handler of its own.
install_error_handlers.handler = _handle
