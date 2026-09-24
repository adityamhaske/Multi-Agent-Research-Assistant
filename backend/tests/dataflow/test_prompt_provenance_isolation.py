"""
The provenance recorder holds per-run mutable state, so isolation is a correctness property.

A `ContextVar` carrying a dict is the right shape for this — a graph node running in its own
task still records into the run that spawned it — but the same reference-sharing that makes
that work is what would let two concurrent runs write into one collection. These tests exist
because the failure would be silent and the worst possible kind: run B's bundle asserting a
prompt that run A was given.

The lifecycle half matters just as much. The variable is reset in a `finally`, so a run that
raises or is cancelled must not leave its recorder installed for whatever the event loop
picks up next.
"""

from __future__ import annotations

import asyncio

import pytest

from research_engine.prompt_composition import (
    PURPOSE_CONSTANTS,
    PromptProvenanceConflict,
    recording_provenance,
    system_prompt,
)
from research_engine.prompt_composition import _provenance as RECORDER
from research_engine.runconfig import RunConfig, reset_run_config, set_run_config


async def _run(overrides: dict, purposes: list[str], *, hold: float = 0) -> dict:
    """One run: its own config, its own recorder, interleaved with whatever else is running."""
    token = set_run_config(RunConfig(prompt_overrides=overrides))
    try:
        with recording_provenance() as records:
            for purpose in purposes:
                system_prompt(purpose)
                await asyncio.sleep(hold)  # yield, so the runs genuinely interleave
            return dict(records)
    finally:
        reset_run_config(token)


# ── Concurrency ───────────────────────────────────────────────────────────────────


async def test_two_concurrent_runs_keep_separate_provenance():
    """Interleaved on one event loop, each recording a different override."""
    a, b = await asyncio.gather(
        _run({"planner": "PROMPT FROM RUN A"}, ["planner.main", "executor.main"], hold=0.001),
        _run({"planner": "PROMPT FROM RUN B"}, ["planner.main", "critic.research"], hold=0.001),
    )

    assert a["planner.main"]["effective_prompt"] == "PROMPT FROM RUN A"
    assert b["planner.main"]["effective_prompt"] == "PROMPT FROM RUN B"
    assert set(a) == {"planner.main", "executor.main"}
    assert set(b) == {"planner.main", "critic.research"}


async def test_no_run_can_see_another_runs_prompt():
    """The leak this file exists to prevent, stated directly."""
    runs = await asyncio.gather(
        *(_run({"planner": f"SECRET {i}"}, ["planner.main"], hold=0.001) for i in range(8))
    )
    for i, records in enumerate(runs):
        others = {f"SECRET {j}" for j in range(8) if j != i}
        assert records["planner.main"]["effective_prompt"] == f"SECRET {i}"
        assert records["planner.main"]["effective_prompt"] not in others


async def test_each_run_gets_a_fresh_collection():
    """No shared mutable default: two recorders must never be the same object."""
    seen = []

    async def capture():
        with recording_provenance() as records:
            seen.append(id(records))
            await asyncio.sleep(0)

    await asyncio.gather(capture(), capture(), capture())
    assert len(set(seen)) == 3


async def test_a_child_task_records_into_the_run_that_spawned_it():
    """Graph nodes run in their own tasks; their prompts still belong to this run.

    The other side of isolation — too much separation would lose the nodes' provenance
    entirely, which is how the planner's prompt would go missing.
    """
    token = set_run_config(RunConfig(prompt_overrides={}))
    try:
        with recording_provenance() as records:

            async def node(purpose):
                system_prompt(purpose)

            await asyncio.gather(
                node("planner.main"), node("executor.main"), node("critic.research")
            )
    finally:
        reset_run_config(token)

    assert set(records) == {"planner.main", "executor.main", "critic.research"}


async def test_a_sibling_task_started_outside_the_block_records_nothing():
    """A task created before the recorder was installed has its own context copy without it."""
    outside: dict = {}

    async def unrelated():
        await asyncio.sleep(0.005)
        outside["leaked"] = RECORDER.get()

    sibling = asyncio.create_task(unrelated())
    await _run({"planner": "MINE"}, ["planner.main"], hold=0.001)
    await sibling

    assert outside["leaked"] is None


# ── Lifecycle ─────────────────────────────────────────────────────────────────────


def test_the_recorder_is_uninstalled_after_the_block():
    assert RECORDER.get() is None
    with recording_provenance():
        assert RECORDER.get() is not None
    assert RECORDER.get() is None


def test_an_exception_does_not_leave_a_recorder_installed():
    """`finally`, not a happy-path reset: a crashed run must not capture the next one's work."""
    with pytest.raises(RuntimeError, match="boom"), recording_provenance():
        raise RuntimeError("boom")
    assert RECORDER.get() is None


async def test_a_cancelled_run_does_not_leave_a_recorder_installed():
    async def doomed():
        with recording_provenance():
            await asyncio.sleep(10)

    task = asyncio.create_task(doomed())
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert RECORDER.get() is None


async def test_a_crashed_run_does_not_contaminate_the_next_one():
    """The sequential version of the leak: one event loop, one task, two runs in a row."""
    with pytest.raises(RuntimeError), recording_provenance():
        system_prompt("planner.main")
        raise RuntimeError("crash mid-run")

    second = await _run({}, ["executor.main"])
    assert set(second) == {"executor.main"}


def test_nesting_restores_the_outer_recorder():
    with recording_provenance() as outer:
        system_prompt("planner.main")
        with recording_provenance() as inner:
            system_prompt("executor.main")
        assert RECORDER.get() is outer
        system_prompt("critic.research")

    assert set(outer) == {"planner.main", "critic.research"}
    assert set(inner) == {"executor.main"}


def test_an_explicit_collection_is_the_one_used():
    """The desktop hands its own dict in; nothing else may be substituted for it."""
    mine: dict = {}
    with recording_provenance(mine) as records:
        assert records is mine
        system_prompt("planner.main")
    assert set(mine) == {"planner.main"}


# ── The conflict must be loud ─────────────────────────────────────────────────────


def test_composing_one_purpose_two_different_ways_raises():
    """Only reachable if the run's overrides stop being frozen. Silently keeping the first
    would publish one of two prompts as though the model saw only that one."""
    with pytest.raises(PromptProvenanceConflict, match="planner.main"), recording_provenance():
        token = set_run_config(RunConfig(prompt_overrides={"planner": "FIRST"}))
        try:
            system_prompt("planner.main")
        finally:
            reset_run_config(token)
        token = set_run_config(RunConfig(prompt_overrides={"planner": "SECOND"}))
        try:
            system_prompt("planner.main")
        finally:
            reset_run_config(token)


def test_an_identical_repeat_is_not_a_conflict():
    """`executor.main` composes twice per run on the normal path."""
    token = set_run_config(RunConfig(prompt_overrides={"executor": "SAME"}))
    try:
        with recording_provenance() as records:
            system_prompt("executor.main")
            system_prompt("executor.main")
    finally:
        reset_run_config(token)
    assert len(records) == 1
    assert "SAME" in records["executor.main"]["effective_prompt"]


def test_a_protected_purpose_repeated_is_never_a_conflict():
    with recording_provenance() as records:
        for _ in range(3):
            system_prompt("critic.citation_verify")
    assert (
        records["critic.citation_verify"]["effective_prompt"]
        == (PURPOSE_CONSTANTS["critic.citation_verify"])
    )
