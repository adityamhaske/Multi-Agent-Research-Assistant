"""
LangGraph pipeline state (docs/architecture/04_Agent_Design.md §2).

A plain TypedDict — LangGraph manages it and the Postgres checkpointer persists it
at every step, so it must stay JSON-serializable (primitives/lists/dicts only).
"""

from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    # Identity
    session_id: str
    user_id: str

    # Input
    original_query: str
    research_depth: str

    # Planner
    tasks: list[dict[str, Any]]
    # The planner's proposed report structure, editable at the plan gate (docs/07 §2,
    # Phase 4). Empty when the planner proposed none or the gate was skipped.
    proposed_outline: list[dict[str, Any]]
    # Set by plan_gate_node once the gate has been passed (approved or skipped) — lets
    # a resumed run tell "never reached the gate" apart from "passed it".
    plan_approved: bool | None

    # Executor / Critic rounds. Tasks run concurrently, so progress is tracked per task
    # rather than by a moving index (docs/12 M7).
    #
    # `evidence` is rebuilt every round in *task-definition order*, never in completion
    # order — otherwise the synthesizer would number citations differently on every run.
    # Each item carries its own `task_id`, so it is also the per-task store.
    #
    # `verdicts` and `retries` are keyed by `str(task_id)`: the checkpointer serializes
    # state as JSON, where dict keys are always strings.
    evidence: list[dict[str, Any]]
    verdicts: dict[str, dict[str, Any]]
    retries: dict[str, int]
    research_round: int

    # Synthesis / HITL
    draft_report: str | None
    sources: list[dict[str, Any]]
    # Conflicting-claim pairs found by the contradiction detector (docs/12 M11).
    # Surfaced in the report block and the gate count; never auto-resolved.
    contradictions: list[dict[str, Any]]
    human_feedback: str | None
    rework_count: int
    approved: bool | None

    # Output
    final_report: str | None

    # Telemetry
    tokens_input: int
    tokens_output: int
    cost_usd: float
    started_at: float

    # Terminal
    error: str | None
