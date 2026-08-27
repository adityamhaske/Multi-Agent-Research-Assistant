"""
One error taxonomy, one status map, both hosts (parity Phase 4).

`app/api/v1/runs.py` is imported and called by *both* hosts — it is the worked example of a
shared handler — and it raised `HTTPException` at 13 sites. So the status code a client
sees was never actually shared: it was thirteen literals that happened to be reached from
two places. Two things follow, and the second is why this phase comes before any code moves.

**A use case that raises `HTTPException` has already chosen one host's answer for both.**
It compiles on the desktop only because the desktop is also FastAPI. The moment a handler
moves into `app/handlers/`, `tests/workflow/test_layer_boundaries.py` refuses the import —
correctly, because "not found" is a product fact and `404` is a delivery detail.

**A status map that lives at its call sites cannot be read.** Asking "what does this
product return when a run is not yours?" meant grepping. It is one table now, and both
hosts install the same handler over it, so a status can only change in one place.

These tests assert the *structure* — one taxonomy, one map, both hosts wired to it. That
the conversion preserved behaviour is asserted by the suites that already existed
(`test_runs_api`, `test_run_lifecycle`, `test_corpus_upload_contract`, and the parity
goldens, which record every status and `detail` string this product emits).
"""

from __future__ import annotations

import tempfile

import pytest

from app import errors
from app.services.error_responses import error_body, install_error_handlers, status_for


def _subclasses(cls) -> set[type]:
    found = set()
    for sub in cls.__subclasses__():
        found.add(sub)
        found |= _subclasses(sub)
    return found


ERROR_TYPES = sorted(_subclasses(errors.AppError), key=lambda c: c.__name__)


def _make(cls, detail: str):
    """One of each error. `CapabilityUnavailable` takes a required keyword — it has to name
    the capability, or a client cannot branch on which one is absent."""
    if cls is errors.CapabilityUnavailable:
        return cls(detail, capability="project_memory")
    return cls(detail)


# ── The taxonomy ──────────────────────────────────────────────────────────────────


def test_there_is_at_least_one_error_per_thing_the_product_actually_refuses():
    names = {cls.__name__ for cls in ERROR_TYPES}
    assert {
        "NotFound",
        "Conflict",
        "Invalid",
        "PayloadTooLarge",
        "DependencyUnavailable",
        "CapabilityUnavailable",
    } <= names


@pytest.mark.parametrize("cls", ERROR_TYPES, ids=lambda c: c.__name__)
def test_every_error_maps_to_a_status(cls):
    """A new error with no entry would fall through to a 500 — the failure looking like a
    crash rather than a refusal."""
    assert status_for(_make(cls, "because")) in range(400, 600)


@pytest.mark.parametrize("cls", ERROR_TYPES, ids=lambda c: c.__name__)
def test_every_error_carries_a_message_a_client_can_show(cls):
    assert error_body(_make(cls, "no tasks"))["detail"] == "no tasks"


def test_a_capability_refusal_names_the_capability():
    """`CapabilityUnavailable` is how a host says "this is absent by design, and here is
    which thing" — a 404 says "you asked wrong", which is a different claim."""
    exc = errors.CapabilityUnavailable("project memory is not available here", capability="memory")
    assert status_for(exc) == 501
    assert error_body(exc)["capability"] == "memory"


def test_the_map_is_not_derived_from_the_exception_name():
    """Mapping by class name would make a rename a silent status change."""
    assert status_for(errors.NotFound("x")) == 404
    assert status_for(errors.Conflict("x")) == 409
    assert status_for(errors.Invalid("x")) == 400
    assert status_for(errors.PayloadTooLarge("x")) == 413
    assert status_for(errors.DependencyUnavailable("x")) == 503


# ── Both hosts are wired to it ────────────────────────────────────────────────────


def _server_app():
    from app.main import app

    return app


def _desktop_app():
    from desktop.sidecar import create_sidecar_app

    return create_sidecar_app(data_dir=tempfile.mkdtemp(), token="errors", fake=True)


@pytest.mark.parametrize("factory", [_server_app, _desktop_app], ids=["server", "desktop"])
def test_both_hosts_install_the_shared_handler(factory):
    """Identity, not "both have a handler": two handlers that agree today are two homes."""
    app = factory()
    handler = app.exception_handlers.get(errors.AppError)
    assert handler is not None, "this host does not translate domain errors at all"
    assert handler is install_error_handlers.handler


def test_the_shared_handlers_no_longer_raise_transport_exceptions():
    """`app/api/v1/runs.py` is called directly by the desktop, so every `HTTPException` in
    it is a status code chosen by the server for a host that never got a say.

    Asserted on the source rather than by exercising all thirteen paths: the point is that
    the construct is gone, and a single surviving `raise HTTPException` would be a
    thirteenth home for the map this phase created.
    """
    import ast
    import inspect

    from app.api.v1 import runs

    tree = ast.parse(inspect.getsource(runs))
    raised = {
        node.exc.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Raise)
        and isinstance(node.exc, ast.Call)
        and isinstance(node.exc.func, ast.Name)
    }
    assert "HTTPException" not in raised, (
        "app/api/v1/runs.py still raises HTTPException — the desktop calls these handlers "
        "directly, so the status code has to come from the shared map"
    )
