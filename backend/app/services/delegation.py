"""
Marking a route as a thin adapter over a named owner.

`AGENTS.md`'s invariant is that a product operation is implemented once and exposed by both
hosts through thin adapters. Nothing could check that: the desktop's run routes *do*
delegate to `app/api/v1/runs.py`, but they delegate by calling an imported function inside a
wrapper, and "this wrapper calls that function" is not something a test can read off an
application object.

`@delegates_to` makes it readable. It records the owner on the wrapper, so
`tests/workflow/test_one_canonical_owner.py` can assert that both hosts' routes for one
operation point at the **same function object** — which two copies of a function cannot do,
however identical they look.

It is a claim, not an enforcement: a wrapper could carry the marker and then do something
else entirely. What stops that is the parity suite, which drives the operation on both
hosts and compares the result to a recorded contract. The two work together — this says
*who owns it*, the goldens say *what it does*.

Stdlib only; both hosts import it.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import TypeVar

F = TypeVar("F", bound=Callable)


def delegates_to(owner: str) -> Callable[[F], F]:
    """Record that this route is an adapter over `owner`, and nothing more.

    `owner` is a `"module:function"` string, not the function itself, and that is
    load-bearing rather than stylistic. The desktop's run routes import their handlers
    *inside* the request, because importing `app.api.v1.runs` at module scope reaches
    `app.config` — which requires `database_url` and `jwt_secret_key`, neither of which an
    installed app has, and which killed the packaged sidecar at launch (#50).

    A decorator taking the function object would have to resolve it at import time and
    would reintroduce exactly that. A string costs nothing until something asks.
    """

    def mark(route: F) -> F:
        route.__canonical__ = owner
        return route

    return mark


def canonical_owner(route: Callable) -> Callable:
    """The function this route delegates to, or the route itself when it owns the operation.

    Resolves the reference here rather than at decoration time — callers are tests and
    tooling, where importing the owning module is free.
    """
    reference = getattr(route, "__canonical__", None)
    if reference is None:
        return route
    module_path, _, name = reference.partition(":")
    return getattr(importlib.import_module(module_path), name)
