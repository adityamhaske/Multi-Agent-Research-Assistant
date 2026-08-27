"""
One operation, one owner — proved by object identity (parity Phase 6).

`test_host_parity` asks whether a route *exists* on both hosts, and Phase 1 taught it to
compare declared response shapes. Neither can tell the difference between "both hosts call
the same function" and "both hosts have their own function that currently agrees". That
difference is the entire subject of this refactor: the `/runs` surface is shared and the
`/research` surface is two implementations, and from the outside on a good day they look
identical.

Identity is the check that cannot be satisfied by agreement. Two copies of a function are
two objects, however alike; one function referenced twice is one object. So for every
operation below, both hosts' routes must resolve to the same `code` object.

**This measures ownership, not behaviour.** A wrapper could carry the marker and then do
something else. What covers that is `tests/parity/`, which drives the operation on both
hosts and compares the result to a recorded contract. The two are complementary: this says
who owns the operation, the goldens say what it does.

The table is the registry. When Phase 6 finishes moving handlers into `app/handlers/`, the
owner named here becomes the handler and both hosts become wrappers; the assertion does not
change.
"""

from __future__ import annotations

import tempfile

import pytest

from app.services.delegation import canonical_owner

#: Operations both hosts serve from one implementation, with the module that owns each.
#: An operation here is a promise that neither host has its own copy.
SHARED_OWNERSHIP: dict[str, str] = {
    "POST /runs": "app.api.v1.runs",
    "GET /runs": "app.api.v1.runs",
    "GET /runs/{run_id}": "app.api.v1.runs",
    "POST /runs/{run_id}/plan-review": "app.api.v1.runs",
    "POST /runs/{run_id}/report-review": "app.api.v1.runs",
    "GET /runs/{run_id}/export.md": "app.api.v1.runs",
    "POST /runs/{run_id}/cancel": "app.api.v1.runs",
    "POST /runs/{run_id}/archive": "app.api.v1.runs",
    "POST /runs/{run_id}/unarchive": "app.api.v1.runs",
    "GET /runs/{run_id}/bundle.json": "app.api.v1.runs",
    "GET /runs/{run_id}/verification": "app.api.v1.runs",
}

#: Shared operations whose two hosts legitimately run different code, with the reason.
#: Every entry is a place where the *mechanism* differs, never the contract — and each one
#: names the phase that removes it where the plan expects to.
DIVERGENT_BY_DESIGN: dict[str, str] = {
    "GET /runs/{run_id}/stream": (
        "plan phase 6 — the live tail is Redis pub/sub on the server and an in-process bus "
        "on the desktop. Backlog, replay and the stop-lists are already identical; the "
        "EventStream port (P7) is what lets the generator itself be shared"
    ),
    "DELETE /runs/{run_id}": (
        "plan phase 6 — the desktop additionally deletes its own LangGraph checkpoint "
        "thread, which the server's saver does not expose the same way. The lifecycle "
        "write itself is already `run_lifecycle.delete_run` on both"
    ),
    "GET /runs/{run_id}/export.pdf": (
        "capability difference — the desktop answers 501 by design (WeasyPrint stays out "
        "of the bundle); reclassified in plan phase 10"
    ),
}


def _endpoints(app, strip: str = "/api/v1") -> dict[str, object]:
    """`"POST /runs" -> endpoint function`, walking included routers.

    FastAPI does not flatten `include_router` into `app.routes` in this version — it keeps
    an `_IncludedRouter` holding the original router and the prefix — so the walk has to
    recurse. `test_host_parity` sidesteps this by reading the OpenAPI document, which gives
    paths but not the functions behind them, and the functions are the whole point here.
    """
    found: dict[str, object] = {}

    def walk(routes, prefix: str) -> None:
        for route in routes:
            inner = getattr(route, "original_router", None)
            if inner is not None:
                context = getattr(route, "include_context", None)
                walk(inner.routes, prefix + getattr(context, "prefix", ""))
                continue
            path = getattr(route, "path", None)
            endpoint = getattr(route, "endpoint", None)
            if path is None or endpoint is None:
                continue
            full = prefix + path
            normalised = full[len(strip) :] if full.startswith(strip) else full
            for method in sorted(getattr(route, "methods", None) or []):
                if method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                    found[f"{method} {normalised}"] = endpoint

    walk(app.routes, "")
    return found


@pytest.fixture(scope="module")
def hosts():
    from app.main import app as server
    from desktop.sidecar import create_sidecar_app

    desktop = create_sidecar_app(data_dir=tempfile.mkdtemp(), token="owner", fake=True)
    return _endpoints(server), _endpoints(desktop)


def test_the_walk_actually_found_the_run_surface(hosts):
    """Guards the walker. A recursion that silently found nothing would make every
    assertion below vacuous — the failure mode this whole suite exists to refuse."""
    server, desktop = hosts
    assert len([op for op in server if op.startswith(("GET /runs", "POST /runs"))]) >= 8
    assert len([op for op in desktop if op.startswith(("GET /runs", "POST /runs"))]) >= 8


@pytest.mark.parametrize("operation", sorted(SHARED_OWNERSHIP), ids=lambda o: o)
def test_both_hosts_resolve_to_the_same_function(operation, hosts):
    server, desktop = hosts
    assert operation in server, f"{operation} is not served by the server host"
    assert operation in desktop, f"{operation} is not served by the desktop host"

    owner = canonical_owner(server[operation])
    delegate = canonical_owner(desktop[operation])
    assert delegate is owner, (
        f"{operation} runs different code on each host: server={owner.__module__}."
        f"{owner.__qualname__}, desktop={delegate.__module__}.{delegate.__qualname__}. "
        "Two implementations that agree today are two implementations."
    )


@pytest.mark.parametrize("operation", sorted(SHARED_OWNERSHIP), ids=lambda o: o)
def test_the_owner_lives_where_the_registry_says(operation, hosts):
    """So a move shows up here as a deliberate edit rather than as nothing at all."""
    server, _ = hosts
    assert canonical_owner(server[operation]).__module__ == SHARED_OWNERSHIP[operation]


def test_every_declared_divergence_is_still_divergent(hosts):
    """Anti-rot, same contract as every other table in this suite: an operation that has
    become shared must leave the list, so it can only shrink."""
    server, desktop = hosts
    resolved = {
        op
        for op in DIVERGENT_BY_DESIGN
        if op in server
        and op in desktop
        and canonical_owner(server[op]) is canonical_owner(desktop[op])
    }
    assert not resolved, f"Now shared — remove from DIVERGENT_BY_DESIGN: {sorted(resolved)}"


def test_every_declared_divergence_states_a_reason(hosts):
    for operation, reason in DIVERGENT_BY_DESIGN.items():
        assert len(reason) > 40, f"{operation} needs a real reason, not {reason!r}"


def test_no_run_operation_is_unaccounted_for(hosts):
    """The list cannot be kept short by leaving operations off it.

    Every `/runs` path both hosts serve is either declared shared — and then proved shared
    by identity — or declared divergent with a reason. There is no third category.
    """
    server, desktop = hosts
    shared_paths = {
        op for op in set(server) & set(desktop) if op.split(" ", 1)[1].startswith("/runs")
    }
    unaccounted = shared_paths - set(SHARED_OWNERSHIP) - set(DIVERGENT_BY_DESIGN)
    assert not unaccounted, (
        "These run operations exist on both hosts and nobody has said whether they share "
        f"an implementation: {sorted(unaccounted)}"
    )
