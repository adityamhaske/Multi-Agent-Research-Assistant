"""
LangGraph pipeline state (docs/04_Agent_Design.md §2).

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
    current_task_index: int

    # Executor / Critic loop
    evidence: list[dict[str, Any]]
    critic_verdict: dict[str, Any] | None
    critic_retries: int

    # Synthesis / HITL
    draft_report: str | None
    sources: list[dict[str, Any]]
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
