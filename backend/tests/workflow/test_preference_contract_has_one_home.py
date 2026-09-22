"""
"Which preferences a run honours" is one implementation, not four (RFC AP-2).

The same shape as `test_run_config_has_one_home.py`, for the neighbouring contract. Before
this, the field list lived in four states at once:

    app/workers/pipeline_runner.py   the definition, private to a module `desktop/` may
                                     not import (`app.workers` is infrastructure)
    app/run_execution.py             imported it, and re-exported it under a private name
    desktop/sidecar.py::_drive_session   restated it as an inline literal
    desktop/sidecar.py::_drive_run       did not have it at all

Three copies kept in step by discipline, and a fourth call site written without any. That
fourth one is the whole argument: a list you have to remember to copy is a list someone
eventually does not.

`test_desktop_run_honours_preferences.py` pins the *behaviour*. This pins the *structure*,
so a fifth home cannot appear — and so the canonical home stays somewhere both hosts are
architecturally allowed to import from.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from app import run_execution
from app.services.run_config import PREFERENCE_FIELDS, preference_overrides
from app.workers import pipeline_runner
from desktop import sidecar

BACKEND = Path(__file__).resolve().parents[2]

#: The five keys, unchanged by AP-2. Stated literally so a silent widening of the
#: preference surface — which AgentSpec will be tempted to do — fails here first.
EXPECTED_FIELDS = (
    "retrieval_k",
    "min_sources_per_task",
    "snippet_max_chars",
    "tavily_api_key",
    "brave_api_key",
)


# ── One object ────────────────────────────────────────────────────────────────────


def test_the_preference_surface_is_exactly_what_it_was():
    """AP-2 moves the contract; it must not broaden it."""
    assert PREFERENCE_FIELDS == EXPECTED_FIELDS


def test_every_host_resolves_to_the_same_extractor():
    """Unfakeable: two copies cannot be one object."""
    assert pipeline_runner.preference_overrides is preference_overrides
    assert run_execution.preference_overrides is preference_overrides
    assert sidecar.preference_overrides is preference_overrides


def test_the_canonical_home_is_importable_by_both_hosts():
    """`app.services.run_config` and nothing below it.

    The previous home was `app.workers.pipeline_runner`, and `app.workers` is
    infrastructure (`tests/workflow/test_layer_boundaries.py`), so the desktop could never
    have imported it — which is precisely why it held a copy instead. The module this now
    lives in is the one both hosts already import for `apply_demo_rule`.
    """
    assert preference_overrides.__module__ == "app.services.run_config"


def test_the_shared_module_stays_free_of_infrastructure_and_the_orm():
    """It is on the desktop's request-time import path, so what it imports ships.

    `app.config` builds `Settings` from environment an installed app does not have, and
    `app.models` drags the ORM in for a rule that only reads a mapping.
    """
    source = (BACKEND / "app" / "services" / "run_config.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = ("app.config", "app.db", "app.dependencies", "app.workers", "app.models")
    assert not [m for m in imported if m.startswith(forbidden)], sorted(imported)


# ── No copy left behind ───────────────────────────────────────────────────────────


def test_no_host_restates_the_field_list():
    """The literal is gone from `desktop/` and from both server builders.

    Matched on the two keys most specific to this contract rather than on all five, so a
    partial copy — the likeliest way one comes back — is caught too.
    """
    for path in (
        BACKEND / "desktop" / "sidecar.py",
        BACKEND / "app" / "workers" / "pipeline_runner.py",
        BACKEND / "app" / "run_execution.py",
    ):
        source = path.read_text(encoding="utf-8")
        assert not ('"min_sources_per_task"' in source and '"snippet_max_chars"' in source), (
            f"{path.name} restates the preference field list; import PREFERENCE_FIELDS "
            "from app.services.run_config instead"
        )


def test_every_per_run_builder_reads_the_preferences():
    """The defect AP-1 fixed, pinned structurally.

    `_drive_run` was the one builder of four with no call at all. Asserting the call exists
    in each function body is what stops it being dropped again by someone editing one host.
    """
    builders = {
        "app/workers/pipeline_runner.py": "_run_config_for",
        "app/run_execution.py": "run_config_for_run",
    }
    for rel, func in builders.items():
        tree = ast.parse((BACKEND / rel).read_text(encoding="utf-8"))
        body = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef) and n.name == func
        ]
        assert body, f"{rel}::{func} not found"
        assert "preference_overrides(" in ast.unparse(body[0]), (
            f"{rel}::{func} does not read the user's preferences"
        )

    # The sidecar's two drivers are nested inside `create_sidecar_app`, so they are found
    # by walking the whole module rather than its top level.
    sidecar_tree = ast.parse(inspect.getsource(sidecar))
    for func in ("_drive_session", "_drive_run"):
        found = [
            n
            for n in ast.walk(sidecar_tree)
            if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef) and n.name == func
        ]
        assert found, f"desktop/sidecar.py::{func} not found"
        assert "preference_overrides(" in ast.unparse(found[0]), (
            f"desktop/sidecar.py::{func} does not read the user's preferences — this is "
            "the AP-1 defect returning"
        )
