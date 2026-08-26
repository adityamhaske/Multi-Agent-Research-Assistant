"""
Engine boundary guard (docs/12 M6, docs/13 §3).

`research_engine/` (formerly `app/agent/`) is a standalone package that must run inside
a desktop app with no Postgres, no Redis, and no `.env`. These tests are the enforcement:
they fail the moment engine code re-couples to the server host.

Without a test like this the refactor decays back — the coupling it removes was itself
introduced one convenient import at a time. docs/13 §3 calls for an import-linter
contract in CI; this is that contract, implemented with the stdlib so it needs no new
dependency.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.config import Settings
from research_engine.runconfig import (
    DEFAULT_MODELS,
    ROLES,
    RunConfig,
    get_run_config,
    reset_run_config,
    set_run_config,
)

ENGINE_DIR = Path(__file__).resolve().parents[2] / "research_engine"

# The engine may not import the server host at all — not just `app.config`. Now that the
# package is physically separate (M6 step 2) the contract is the whole `app` namespace.
#
# `evals` joined the list in M0A. It was never in it, and `bundle.py` consequently imported
# `evals.metrics` for claim extraction while `graph.py`'s own docstring asserted the engine
# imported nothing from evals. The practical cost was that the "standalone" engine could
# not be shipped to a desktop build without also shipping the eval harness. The dependency
# now runs the other way: `research_engine.claims` is canonical and `evals.metrics`
# re-exports from it.
FORBIDDEN_ROOTS = ("app", "evals")

# Remaining known couplings, each with the milestone that removes it. A violation NOT in
# this set fails the test; an entry here that no longer occurs also fails it, so the list
# cannot rot.
#
# Empty as of M6 step 3: the last one (`app.db.redis` in retrievers.py) became the Cache
# port. The engine now imports nothing from the host at all. Adding an entry here should
# take an argument, not a convenience.
KNOWN_EXCEPTIONS: set[tuple[str, str]] = set()


def _imported_host_modules() -> set[tuple[str, str]]:
    """Every (filename, module) pair where engine code imports a forbidden host module."""
    found: set[tuple[str, str]] = set()
    paths = sorted(ENGINE_DIR.glob("*.py"))
    assert paths, f"no engine modules found under {ENGINE_DIR} — did the package move?"
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module]
            for module in modules:
                if any(module == root or module.startswith(root + ".") for root in FORBIDDEN_ROOTS):
                    found.add((path.name, module))
    return found


def test_engine_package_does_not_import_the_server_host():
    """The engine reads config through RunConfig, never from app.config or the data plane."""
    assert _imported_host_modules() == KNOWN_EXCEPTIONS


def test_known_exceptions_are_still_real():
    """Guards the allowlist itself: a resolved exception must be deleted from it."""
    stale = KNOWN_EXCEPTIONS - _imported_host_modules()
    assert not stale, f"Resolved — remove from KNOWN_EXCEPTIONS: {sorted(stale)}"


def test_runconfig_defaults_mirror_settings_defaults():
    """A host that forgets to install a config must degrade to today's behaviour.

    Compares against Settings' declared field defaults, not an instantiated Settings,
    so the assertion is independent of the environment the tests run in.
    """
    declared = Settings.model_fields
    cfg = RunConfig()

    assert cfg.llm_mode == declared["llm_mode"].default
    assert cfg.max_critic_loops == declared["max_critic_loops"].default
    assert cfg.max_cost_per_session_usd == declared["max_cost_per_session_usd"].default
    assert cfg.max_wallclock_seconds == declared["max_wallclock_seconds"].default

    for role in ROLES:
        assert DEFAULT_MODELS[role] == declared[f"model_{role}"].default


def test_conftest_installed_fake_mode():
    """The test process is a host, and it installed a config — otherwise the graph
    would run in real mode and hit the network."""
    assert get_run_config().llm_mode == "fake"


def test_run_override_beats_process_default():
    """Per-run override is the mechanism the M8 per-session model picker needs."""
    baseline = get_run_config()
    assert baseline.llm_mode == "fake"

    token = set_run_config(RunConfig(llm_mode="real", max_critic_loops=7))
    try:
        assert get_run_config().llm_mode == "real"
        assert get_run_config().max_critic_loops == 7
    finally:
        reset_run_config(token)

    assert get_run_config() is baseline


def test_model_for_rejects_unknown_role():
    cfg = RunConfig()
    for role in ROLES:
        assert cfg.model_for(role)
    try:
        cfg.model_for("nonexistent")
    except ValueError as e:
        assert "nonexistent" in str(e)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for an unrouted role")
