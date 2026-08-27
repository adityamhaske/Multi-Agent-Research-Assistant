"""
The dependency direction, enforced (parity Phase 3).

`test_engine_boundary` already guards the bottom of the stack: `research_engine/` imports
nothing from `app/` or `evals/`, and it has held because a test says so. Everything *above*
the engine has no such rule, and that is the whole reason this repository keeps growing
second implementations — `AGENTS.md` opens on it.

The direction, and it only ever points down:

    TRANSPORT        app/api/v1/*        desktop/sidecar.py, desktop/routes/*
        ↓            FastAPI, Depends, HTTPException, auth, rate limiting
    APPLICATION      app/handlers/*
        ↓            plain async functions over collaborators; no transport, no host
    DOMAIN           app/models, app/schemas, run_lifecycle, run_bundle, authorization
        ↓            research_engine/* (its own enforced boundary)
    PORTS            app/ports.py, research_engine/ports.py
        ↓            Protocols only; imports neither host
    INFRASTRUCTURE   app/config, app/db, app/dependencies, app/adapters, app/workers
                     desktop/infrastructure/*

**Why an import rule and not a review habit.** A route written the ordinary FastAPI way
binds `get_db`, `get_current_user`, `get_redis` and `settings` into the same function as
the product rule. The desktop then *cannot* reuse it, so it restates it — which is how
`desktop/sidecar.py` reached 2,973 lines. `app/api/v1/runs.py` avoided this by writing
handlers as plain functions with `Depends` only as defaults, and nothing enforced that
style, so every other module drifted back. This is the enforcement.

**Relationship to `test_sidecar_startup`.** That module asks whether a specific import
*happens* at startup in the packaged app (#50). This one asks whether an import is
*allowed* at all, anywhere in a layer. Different questions; a module can pass one and fail
the other.

`KNOWN_EXCEPTIONS` records what is true today, one entry per violation with the phase that
removes it, and it cannot rot: an entry that stops being a real violation fails the suite,
exactly as in `test_engine_boundary`. It found one on its first run — see the entry.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]

#: The host's own machinery. Nothing above the infrastructure layer may reach it: these
#: modules build `Settings` from environment the desktop does not have, open the server's
#: engine, or speak to a broker that only one host runs.
INFRASTRUCTURE = (
    "app.config",
    "app.db",
    "app.dependencies",
    "app.adapters",
    "app.workers",
    "celery",
    "redis",
    "keyring",
)

#: Delivery mechanism. The application layer states *what* happens; how it reaches a client
#: is the adapter's business, and a use case that raises `HTTPException` has already
#: decided one host's answer for both.
TRANSPORT = ("fastapi", "starlette")

#: The other host. Neither adapter may import the other, in either direction.
HOSTS = ("desktop",)


def _imports(path: Path) -> set[str]:
    """Every module named by a top-level or in-function import in one file."""
    found: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
    return found


def _violations(files: list[Path], forbidden: tuple[str, ...]) -> set[tuple[str, str]]:
    """`(relative path, module)` for every forbidden import, including deferred ones.

    Imports inside functions count. Deferring an import is how a module keeps a dependency
    out of *startup*, which is a real and different concern (`test_sidecar_startup`), but it
    does not make the dependency go away — the layer still depends on it at request time,
    and `app/run_execution.py` reaching `app.runtime` inside a function is exactly how the
    packaged sidecar's run routes came to 500.
    """
    out: set[tuple[str, str]] = set()
    for path in files:
        for module in _imports(path):
            if any(module == root or module.startswith(root + ".") for root in forbidden):
                out.add((str(path.relative_to(BACKEND)), module))
    return out


def _unexplained(files: list[Path], forbidden: tuple[str, ...]) -> set[tuple[str, str]]:
    """Violations that are not recorded in `KNOWN_EXCEPTIONS`."""
    return _violations(files, forbidden) - set(KNOWN_EXCEPTIONS)


def _files(*globs: str) -> list[Path]:
    found: list[Path] = []
    for pattern in globs:
        found.extend(p for p in BACKEND.glob(pattern) if p.name != "__init__.py")
    return sorted(found)


# ── The application layer ─────────────────────────────────────────────────────────

#: Empty until Phase 6 starts moving use cases in. The rule is declared first on purpose:
#: a boundary added after the code it governs is a boundary drawn around whatever the code
#: already does.
APPLICATION = _files("app/handlers/*.py", "app/handlers/**/*.py")

#: Violations that exist today, each with the phase that removes it. Same contract as
#: `test_engine_boundary.KNOWN_EXCEPTIONS` and the parity suite's `XFAIL_DIVERGENCES`:
#: adding an entry should take an argument, and one that stops being true fails the suite.
#: Violations that exist today, each with the phase that removes it. Same contract as
#: `test_engine_boundary.KNOWN_EXCEPTIONS` and the parity suite's `XFAIL_DIVERGENCES`:
#: adding an entry should take an argument, and one that stops being true fails the suite.
#:
#: **Empty.** It held one entry — `app/run_dispatch.py` reaching `app.workers.tasks`,
#: because that module was both the port and the server's Celery adapter. The adapter moved
#: to `app/workers/dispatch.py`, beside the tasks it hands work to, and the port now holds
#: only the protocol. Keep it empty: an entry here is a layer carrying a dependency it has
#: no business having.
KNOWN_EXCEPTIONS: dict[tuple[str, str], str] = {}


def test_the_application_layer_imports_no_infrastructure():
    """A use case only one host can call is not a use case."""
    assert _unexplained(APPLICATION, INFRASTRUCTURE) == set()


def test_the_application_layer_imports_no_transport():
    """`HTTPException`, `UploadFile` and `StreamingResponse` are one host's delivery
    mechanism. `app/errors.py` (Phase 4) is where a use case says what went wrong."""
    assert _unexplained(APPLICATION, TRANSPORT) == set()


def test_the_application_layer_does_not_import_a_host():
    assert _unexplained(APPLICATION, HOSTS) == set()


def test_known_exceptions_are_still_real():
    """Guards the allowlist itself, exactly as `test_engine_boundary` does."""
    live = _violations(APPLICATION, INFRASTRUCTURE) | _violations(DOMAIN, INFRASTRUCTURE)
    stale = set(KNOWN_EXCEPTIONS) - live
    assert not stale, f"Resolved — remove from KNOWN_EXCEPTIONS: {sorted(stale)}"


def test_every_exception_names_the_phase_that_closes_it():
    """An allowlist entry without a reason becomes permanent by default."""
    for entry, reason in KNOWN_EXCEPTIONS.items():
        assert "phase" in reason.lower() and len(reason) > 40, (
            f"{entry} needs a reason naming the phase that removes it, not {reason!r}"
        )


# ── Ports ─────────────────────────────────────────────────────────────────────────

PORTS = _files("app/ports.py", "research_engine/ports.py")


def test_ports_import_neither_host():
    """A port that imports an implementation is not a port. `research_engine/ports.py` is
    already held to this by `test_engine_boundary`; `app/ports.py` joins it here."""
    assert PORTS, "no ports module found — did app/ports.py move?"
    assert _unexplained(PORTS, INFRASTRUCTURE + HOSTS) == set()


# ── Domain ────────────────────────────────────────────────────────────────────────
#
# Ground this repository already holds. These modules are host-free today — that is what
# lets `desktop/sidecar.py` import them rather than restate them, and it is the single
# reason the `/runs` surface is genuinely shared while `/research` is not. Enforcing it
# costs nothing now and stops the next convenient import from taking it back.

DOMAIN = _files(
    "app/run_lifecycle.py",
    "app/run_bundle.py",
    "app/authorization.py",
    "app/run_dispatch.py",
    "app/schemas/*.py",
    "app/models/*.py",
    "app/services/document_headers.py",
    "app/services/sse.py",
    "app/services/session_events.py",
    "app/services/corpus_ingest.py",
    "app/services/chat_scope.py",
    "app/services/memory.py",
    "app/errors.py",
)


def test_the_domain_layer_imports_no_transport():
    """Enabled by Phase 4, and not before: `corpus_ingest` raised `HTTPException` until the
    taxonomy in `app/errors.py` gave it a way to refuse without naming a status.

    `app/services/error_responses.py` is deliberately NOT in this list — translating a
    domain error into an HTTP response is transport, shared by two transport adapters,
    the same shape as `document_headers.py` and `sse.py`.
    """
    assert _unexplained(DOMAIN, TRANSPORT) == set()


def test_the_domain_layer_imports_no_infrastructure():
    """Each of these is imported by BOTH hosts today. An infrastructure import here does
    not merely bend a rule — it takes a module away from the desktop, which is how #50
    killed the packaged sidecar at import."""
    assert _unexplained(DOMAIN, INFRASTRUCTURE) == set()


def test_the_domain_layer_does_not_import_a_host():
    assert _unexplained(DOMAIN, HOSTS) == set()


# ── The two pipelines stay two pipelines ──────────────────────────────────────────


def test_the_session_and_run_use_cases_do_not_import_each_other():
    """Consolidating the two pipelines is a milestone, not a side effect of this refactor
    (`AGENTS.md`). A no-op until both modules exist, and load-bearing the moment they do.
    """
    for a, b in (("sessions", "runs"), ("runs", "sessions")):
        module = BACKEND / "app" / "handlers" / f"{a}.py"
        if not module.exists():
            continue
        assert f"app.handlers.{b}" not in _imports(module), (
            f"app/handlers/{a}.py imports app/handlers/{b}.py — the session pipeline and "
            "the run pipeline are deliberately separate owners"
        )
