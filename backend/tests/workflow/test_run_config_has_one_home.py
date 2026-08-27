"""
"The row records what actually ran" — one implementation (parity Phase 5).

`AGENTS.md` states the rule and names its homes:

    "Scripted"/`demo` must be decided from the request flag *or* the resolved `llm_mode`,
    in one branch, in all three homes: `pipeline_runner::_run_config_for`,
    `run_execution::run_config_for_run`, `sidecar::_drive_session`.

There were four, not three — `sidecar::_drive_run` is the fourth — and "in one branch, in
all N homes" is a discipline, not a property. This is the property: one function, four call
sites, and a test that asserts they resolve to the same object.

**Why this rule and not another.** `start.sh` exports `LLM_MODE=fake` for `--fake` *and*
silently as a fallback when `.env` has no provider key, so the commonest first-run setup is
a fake deployment. A run that reached no provider used to record `demo = false`: its bundle
named `google:gemini-2.5-pro` at a real-looking cost, its `.md` export skipped the demo
stamp, and `verify_bundle` printed PASS with no warning. That is the P0 honesty class this
repository is built around — a run that reached no provider must never be able to present
as one that did.

`test_scripted_runs_are_recorded_as_demo.py` pins the *behaviour* at all three original
homes and stays exactly as it is. This pins the *structure*, so a fifth home cannot appear.
"""

from __future__ import annotations

import pytest

from app.services.run_config import apply_demo_rule
from research_engine.runconfig import RunConfig

REAL = RunConfig(llm_mode="real", models={"planner": "google:gemini-2.5-flash"})
SCRIPTED = RunConfig(llm_mode="fake", models={"planner": "google:gemini-2.5-flash"})


# ── The rule ──────────────────────────────────────────────────────────────────────


def test_a_run_the_requester_asked_to_be_a_demo_is_scripted_and_stamped():
    config, stamp = apply_demo_rule(REAL, row_demo=True, host_is_scripted=False)
    assert config.llm_mode == "fake"
    assert config.demo is True
    assert stamp is False, "the row already says demo; there is nothing to stamp"


def test_a_run_on_a_scripted_deployment_is_recorded_as_a_demo_even_though_nobody_asked():
    """The bug this rule exists for. `start.sh` falls back to `LLM_MODE=fake` when there is
    no provider key, so this is the commonest first-run setup — and it used to record
    `demo = false` while nothing had been called."""
    config, stamp = apply_demo_rule(SCRIPTED, row_demo=False, host_is_scripted=True)
    assert config.demo is True
    assert stamp is True, "the row says demo=false and must be corrected to match reality"


def test_a_host_wide_scripted_flag_counts_even_when_the_config_says_real():
    """The desktop's `--fake` is a process flag, not a `RunConfig` field. Both ways in have
    to reach the same branch, or one host records honestly and the other does not."""
    config, stamp = apply_demo_rule(REAL, row_demo=False, host_is_scripted=True)
    assert config.llm_mode == "fake"
    assert config.demo is True
    assert stamp is True


def test_an_ordinary_run_is_left_alone():
    config, stamp = apply_demo_rule(REAL, row_demo=False, host_is_scripted=False)
    assert config.llm_mode == "real"
    assert config.demo is False
    assert stamp is False


def test_the_decision_is_stable_across_a_resume():
    """`demo` selects the seeded content while `llm_mode` keeps the run offline, so a flag
    that flipped False->True between a run and its resume would change what the run
    researches halfway through. Feeding the result back in must be a no-op."""
    first, _ = apply_demo_rule(SCRIPTED, row_demo=False, host_is_scripted=True)
    second, stamp = apply_demo_rule(first, row_demo=True, host_is_scripted=True)
    assert (second.llm_mode, second.demo) == (first.llm_mode, first.demo)
    assert stamp is False


def test_the_rule_never_downgrades_a_recorded_demo():
    """A row that says demo must stay scripted even if the host is not — otherwise a
    resumed demo would start calling a real provider mid-run."""
    config, _ = apply_demo_rule(REAL, row_demo=True, host_is_scripted=False)
    assert config.llm_mode == "fake"


# ── One home ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "module_path",
    [
        "app.workers.pipeline_runner",
        "app.run_execution",
        "desktop.sidecar",
    ],
)
def test_every_host_resolves_to_the_same_function(module_path):
    """Identity, not equality. Four copies that agree today are four copies."""
    import importlib

    module = importlib.import_module(module_path)
    assert getattr(module, "apply_demo_rule", None) is apply_demo_rule, (
        f"{module_path} does not use the shared demo rule — "
        "a run that reached no provider must never be able to present as one that did"
    )


def test_no_host_still_branches_on_the_rule_itself():
    """The four original branches, gone from the source rather than merely bypassed.

    A surviving `row.demo or base.llm_mode == "fake"` would be a fifth home waiting to
    drift, even if nothing currently calls it.
    """
    import ast
    import inspect

    from app import run_execution
    from app.workers import pipeline_runner
    from desktop import sidecar

    for module in (pipeline_runner, run_execution, sidecar):
        source = inspect.getsource(module)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.BoolOp) or not isinstance(node.op, ast.Or):
                continue
            rendered = ast.unparse(node)
            assert not ("demo" in rendered and ("fake" in rendered or "state.fake" in rendered)), (
                f"{module.__name__} still decides the demo rule itself: {rendered}"
            )
