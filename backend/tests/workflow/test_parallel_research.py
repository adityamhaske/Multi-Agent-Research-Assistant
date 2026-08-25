"""
Parallel research rounds (docs/12 M7).

Three properties matter and none of them are visible from a passing golden journey:

1. tasks really do overlap in time (otherwise this milestone changed nothing),
2. citation numbering is byte-identical across runs (concurrency must not reorder
   evidence, or the same research would cite different numbers each time),
3. the budget guard still stops a run, and overshoot stays bounded.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from langgraph.checkpoint.memory import MemorySaver

from research_engine import graph as graph_mod
from research_engine.runconfig import RunConfig, reset_run_config, set_run_config
from research_engine.runner import run

QUERY = "What is the state of AI research assistants in 2026?"


def _state(n_tasks: int, **overrides) -> dict:
    state = {
        "session_id": "parallel-test",
        "tasks": [{"id": i, "query": f"task {i}"} for i in range(1, n_tasks + 1)],
        "evidence": [],
        "verdicts": {},
        "retries": {},
        "research_round": 0,
        "cost_usd": 0.0,
        "tokens_input": 0,
        "tokens_output": 0,
        "started_at": time.time(),
    }
    state.update(overrides)
    return state


# ── 1. Tasks actually overlap ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tasks_run_concurrently(monkeypatch):
    """Four slow tasks must finish in roughly one task's time, not four."""
    in_flight = 0
    peak = 0

    async def slow_research(state, task, guard):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        try:
            await asyncio.sleep(0.05)
            return {
                "evidence": [{"task_id": task["id"], "source_url": f"https://s/{task['id']}"}],
                "cost": 0.0,
                "in": 0,
                "out": 0,
            }
        finally:
            in_flight -= 1

    monkeypatch.setattr(graph_mod, "_research_one", slow_research)

    started = time.perf_counter()
    out = await graph_mod.executor_node(_state(4))
    elapsed = time.perf_counter() - started

    assert peak == 4, f"expected 4 tasks in flight at once, saw {peak}"
    assert elapsed < 0.15, f"4x50ms tasks took {elapsed:.3f}s — they ran sequentially"
    assert len(out["evidence"]) == 4
    assert out["research_round"] == 1


@pytest.mark.asyncio
async def test_max_parallel_tasks_is_respected(monkeypatch):
    """The bound exists so a 20-task comprehensive run can't open 20 model connections."""
    in_flight = 0
    peak = 0

    async def slow_research(state, task, guard):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        try:
            await asyncio.sleep(0.02)
            return {"evidence": [], "cost": 0.0, "in": 0, "out": 0}
        finally:
            in_flight -= 1

    monkeypatch.setattr(graph_mod, "_research_one", slow_research)

    token = set_run_config(RunConfig(llm_mode="fake", max_parallel_tasks=2))
    try:
        await graph_mod.executor_node(_state(6))
    finally:
        reset_run_config(token)

    assert peak == 2, f"semaphore should cap concurrency at 2, saw {peak}"


@pytest.mark.asyncio
async def test_sequential_when_max_parallel_is_one(monkeypatch):
    """max_parallel_tasks=1 restores the pre-M7 behaviour exactly."""
    peak = 0
    in_flight = 0

    async def slow_research(state, task, guard):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        try:
            await asyncio.sleep(0.01)
            return {"evidence": [], "cost": 0.0, "in": 0, "out": 0}
        finally:
            in_flight -= 1

    monkeypatch.setattr(graph_mod, "_research_one", slow_research)

    token = set_run_config(RunConfig(llm_mode="fake", max_parallel_tasks=1))
    try:
        await graph_mod.executor_node(_state(4))
    finally:
        reset_run_config(token)

    assert peak == 1


# ── 2. Determinism ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_evidence_is_ordered_by_task_not_by_completion(monkeypatch):
    """The slowest task finishes last but must still appear in task order.

    This is the property that keeps `[1]` meaning the same source between two identical
    runs. Without it the synthesizer renumbers citations non-deterministically.
    """

    async def variable_speed(state, task, guard):
        # Task 1 is slowest, task 3 fastest — completion order is the reverse of task order.
        await asyncio.sleep(0.04 / task["id"])
        return {
            "evidence": [{"task_id": task["id"], "source_url": f"https://s/{task['id']}"}],
            "cost": 0.0,
            "in": 0,
            "out": 0,
        }

    monkeypatch.setattr(graph_mod, "_research_one", variable_speed)

    out = await graph_mod.executor_node(_state(3))
    assert [e["task_id"] for e in out["evidence"]] == [1, 2, 3]


@pytest.mark.asyncio
async def test_retry_round_preserves_passed_tasks_evidence_and_order(monkeypatch):
    """A second round must not drop or reshuffle the evidence of tasks that already passed."""

    async def research(state, task, guard):
        return {
            "evidence": [{"task_id": task["id"], "source_url": f"https://retry/{task['id']}"}],
            "cost": 0.0,
            "in": 0,
            "out": 0,
        }

    monkeypatch.setattr(graph_mod, "_research_one", research)

    # Task 2 passed in round 1; task 1 and 3 are pending.
    state = _state(
        3,
        evidence=[
            {"task_id": 1, "source_url": "https://old/1"},
            {"task_id": 2, "source_url": "https://kept/2"},
            {"task_id": 3, "source_url": "https://old/3"},
        ],
        verdicts={"2": {"passed": True}},
        retries={"1": 1, "3": 1},
        research_round=1,
    )

    out = await graph_mod.executor_node(state)

    assert [e["task_id"] for e in out["evidence"]] == [1, 2, 3]
    urls = [e["source_url"] for e in out["evidence"]]
    assert urls[0] == "https://retry/1", "re-researched task gets fresh evidence"
    assert urls[1] == "https://kept/2", "passed task keeps its original evidence"
    assert urls[2] == "https://retry/3"
    assert out["research_round"] == 2


@pytest.mark.asyncio
async def test_two_identical_runs_number_citations_identically():
    """End to end, through the real fake-mode graph: same input, same citation numbers."""
    reports = []
    for i in range(2):
        outcome = await run(
            checkpointer=MemorySaver(),
            session_id=f"determinism-{i}",
            user_id="u",
            query=QUERY,
            run_config=RunConfig(llm_mode="fake"),
        )
        reports.append((outcome.draft_report, outcome.sources))

    assert reports[0][0] == reports[1][0], "report text drifted between identical runs"
    assert reports[0][1] == reports[1][1], "source numbering drifted between identical runs"


# ── 3. Budget under concurrency ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_guard_stops_dispatching_once_the_limit_is_crossed(monkeypatch):
    """Tasks queued behind the semaphore must not run after the budget is blown."""
    researched: list[int] = []

    async def spend(state, task, guard):
        researched.append(task["id"])
        await guard.add(1.0)  # each task alone blows a $0.50 limit
        return {"evidence": [], "cost": 1.0, "in": 0, "out": 0}

    monkeypatch.setattr(graph_mod, "_research_one", spend)

    token = set_run_config(
        RunConfig(llm_mode="fake", max_parallel_tasks=1, max_cost_per_session_usd=0.50)
    )
    try:
        out = await graph_mod.executor_node(_state(5))
    finally:
        reset_run_config(token)

    assert researched == [1], f"only the first task should run, got {researched}"
    assert out["cost_usd"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_guard_bounds_overshoot_to_tasks_already_in_flight(monkeypatch):
    """With N workers, overshoot is bounded by N — not by the whole task list.

    This is the honest guarantee: a hard cap and true concurrency cannot both hold
    without pre-reserving budget. `max_parallel_tasks=1` is the strict setting.
    """

    async def spend(state, task, guard):
        await asyncio.sleep(0.01)  # all in-flight workers overlap
        await guard.add(1.0)
        return {"evidence": [], "cost": 1.0, "in": 0, "out": 0}

    monkeypatch.setattr(graph_mod, "_research_one", spend)

    token = set_run_config(
        RunConfig(llm_mode="fake", max_parallel_tasks=3, max_cost_per_session_usd=0.50)
    )
    try:
        out = await graph_mod.executor_node(_state(10))
    finally:
        reset_run_config(token)

    # 3 workers can each be mid-call when the limit is crossed; the remaining 7 are not
    # dispatched. Without the guard this would be 10.
    assert out["cost_usd"] == pytest.approx(3.0)


@pytest.mark.asyncio
async def test_budget_breach_routes_to_failer_after_a_parallel_round(monkeypatch):
    async def spend(state, task, guard):
        await guard.add(1.0)
        return {"evidence": [], "cost": 1.0, "in": 0, "out": 0}

    monkeypatch.setattr(graph_mod, "_research_one", spend)

    token = set_run_config(
        RunConfig(llm_mode="fake", max_parallel_tasks=2, max_cost_per_session_usd=0.50)
    )
    try:
        out = await graph_mod.executor_node(_state(2))
        after = {**_state(2), **out}
        assert graph_mod.route_after_critic(after) == "failer"
    finally:
        reset_run_config(token)


@pytest.mark.asyncio
async def test_guard_accounts_across_concurrent_workers():
    """The guard is shared: one worker's spend is visible to the others immediately."""
    guard = graph_mod._BudgetGuard(0.0, 1.0)
    assert not guard.exceeded()

    await asyncio.gather(*(guard.add(0.3) for _ in range(3)))

    assert guard.spent == pytest.approx(0.9)
    assert not guard.exceeded()

    await guard.add(0.2)
    assert guard.exceeded()
