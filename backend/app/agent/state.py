from typing import TypedDict


class Task(TypedDict):
    id: int
    query: str
    status: str  # "pending" | "running" | "passed" | "failed"
    rationale: str


class ContextChunk(TypedDict):
    task_id: int
    source_url: str
    source_title: str
    source_date: str
    key_facts: str
    relevance_score: float


class AgentState(TypedDict):
    # Identity
    session_id: str
    user_id: str

    # Research Input
    original_query: str
    research_depth: str
    selected_sources: list[str]

    # Planner output
    tasks: list[Task]
    current_task_index: int

    # Executor / Critic loop state
    raw_context: list[ContextChunk]
    critic_feedback: dict | None  # {"passed": bool, "reason": str, "feedback": str}
    critic_loop_count: int  # Circuit breaker counter

    # HITL Gate
    synthesized_draft: str | None
    human_feedback: str | None  # Populated when user requests rework

    # Output
    final_report: str | None

    # Telemetry
    total_tokens_input: int
    total_tokens_output: int
    total_cost_usd: float
    start_time: float  # Unix timestamp

    # Error handling
    error: str | None
    error_node: str | None
