"""
LangGraph agent pipeline — wires together all nodes and conditional edges.
"""
import json
import time
import structlog
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.state import AgentState
from app.agent.llm_factory import get_planner_llm, get_executor_llm, get_critic_llm, get_synthesizer_llm
from app.agent.tools import EXECUTOR_TOOLS
from app.config import settings
from app.db.redis import publish_event

logger = structlog.get_logger()

# ─── Prompts ─────────────────────────────────────────────────────────────────────

PLANNER_PROMPT = """You are the Orchestration Planner for a professional research assistant.
Decompose the user's research query into 3 to 5 highly specific, independently executable search tasks.
Each task must include a specific search query string, a rationale, and expected source types.
Output ONLY valid JSON matching this schema:
{"tasks": [{"id": 1, "query": "...", "rationale": "...", "status": "pending"}]}"""

EXECUTOR_PROMPT = """You are the Research Executor. You have web search and webpage reading tools.
For the given task, use your tools to gather factual evidence with explicit source URLs.
Do NOT synthesize or analyze. Only collect raw facts with their source URLs.
Output ONLY valid JSON:
{"task_id": 1, "status": "success", "context_chunks": [{"source_url": "...", "source_title": "...", "source_date": "...", "key_facts": "...", "relevance_score": 0.9}]}"""

CRITIC_PROMPT = """You are the Quality Critic. Evaluate if the gathered context adequately answers the task.
Check: completeness, citation quality (every fact needs a URL), recency, specificity, minimum 2 sources.
Output ONLY valid JSON:
{"task_id": 1, "passed": true, "confidence": 0.9, "reasons": ["..."], "feedback_for_executor": null, "flagged_uncited_claims": []}"""

SYNTHESIZER_PROMPT = """You are the Research Synthesizer. Compile the verified context into a professional Markdown report.
Required structure: # Title, ## Executive Summary, ## Key Findings (with citations), ## Detailed Analysis, ## Data & Metrics Table, ## Conclusion, ## Sources Cited.
Every factual claim MUST have an inline citation [Source](URL). Do not introduce new facts.
Return ONLY the raw Markdown text."""


# ─── Node Functions ───────────────────────────────────────────────────────────────

async def planner_node(state: AgentState) -> dict:
    """Breaks the query into 3-5 structured tasks."""
    log = logger.bind(session_id=state["session_id"], node="planner")
    log.info("node_started")

    await _publish_log(state["session_id"], "planner", f"Breaking query into tasks: '{state['original_query'][:60]}...'")

    llm = get_planner_llm()
    messages = [
        SystemMessage(content=PLANNER_PROMPT),
        HumanMessage(content=f"Research query: {state['original_query']}\nResearch depth: {state['research_depth']}"),
    ]

    response = await llm.ainvoke(messages)
    cost = _estimate_cost(response, "gemini-1.5-pro")

    try:
        parsed = json.loads(response.content)
        tasks = parsed.get("tasks", [])
        # Ensure status field is present
        for task in tasks:
            task.setdefault("status", "pending")
    except (json.JSONDecodeError, KeyError) as e:
        log.error("planner_parse_error", error=str(e), raw=response.content[:200])
        tasks = [{"id": 1, "query": state["original_query"], "rationale": "Fallback task", "status": "pending"}]

    log.info("planner_finished", task_count=len(tasks))
    await _publish_log(state["session_id"], "planner", f"Created {len(tasks)} research tasks", {"tasks": [t["query"] for t in tasks]})

    return {
        "tasks": tasks,
        "current_task_index": 0,
        "total_cost_usd": state["total_cost_usd"] + cost,
    }


async def executor_node(state: AgentState) -> dict:
    """Executes the current task using tools."""
    log = logger.bind(session_id=state["session_id"], node="executor")
    current_idx = state["current_task_index"]
    current_task = state["tasks"][current_idx]

    log.info("node_started", task_id=current_task["id"], query=current_task["query"])
    await _publish_log(
        state["session_id"], "executor",
        f"Searching: '{current_task['query']}'",
        {"task_id": current_task["id"], "loop": state["critic_loop_count"]}
    )

    # Update task status
    tasks = list(state["tasks"])
    tasks[current_idx] = {**current_task, "status": "running"}

    llm = get_executor_llm().bind_tools(EXECUTOR_TOOLS)
    messages = [
        SystemMessage(content=EXECUTOR_PROMPT),
        HumanMessage(content=f"Task ID: {current_task['id']}\nTask Query: {current_task['query']}"),
    ]

    # Add critic feedback if retrying
    if state.get("critic_feedback") and not state["critic_feedback"].get("passed"):
        messages.append(HumanMessage(
            content=f"Previous attempt failed. Critic feedback: {state['critic_feedback'].get('feedback_for_executor', '')}"
        ))

    response = await llm.ainvoke(messages)
    cost = _estimate_cost(response, "gemini-1.5-pro")

    try:
        parsed = json.loads(response.content if hasattr(response, "content") and isinstance(response.content, str) and response.content.startswith("{") else "{}")
        context_chunks = parsed.get("context_chunks", [])
    except Exception:
        context_chunks = []

    await _publish_log(
        state["session_id"], "executor",
        f"Gathered {len(context_chunks)} source(s) for task {current_task['id']}",
        {"task_id": current_task["id"], "source_count": len(context_chunks)}
    )

    return {
        "tasks": tasks,
        "raw_context": state["raw_context"] + [{"task_id": current_task["id"], **c} for c in context_chunks],
        "total_cost_usd": state["total_cost_usd"] + cost,
    }


async def critic_node(state: AgentState) -> dict:
    """Evaluates executor output and passes or fails it."""
    log = logger.bind(session_id=state["session_id"], node="critic")
    current_task = state["tasks"][state["current_task_index"]]

    log.info("node_started", task_id=current_task["id"], loop=state["critic_loop_count"])
    await _publish_log(state["session_id"], "critic", f"Evaluating context quality for task {current_task['id']}...")

    # Get context for this task
    task_context = [c for c in state["raw_context"] if c.get("task_id") == current_task["id"]]

    llm = get_critic_llm()
    messages = [
        SystemMessage(content=CRITIC_PROMPT),
        HumanMessage(content=f"Task: {current_task['query']}\n\nGathered Context:\n{json.dumps(task_context, indent=2)}"),
    ]

    response = await llm.ainvoke(messages)
    cost = _estimate_cost(response, "gemini-1.5-flash")

    try:
        critic_result = json.loads(response.content)
    except json.JSONDecodeError:
        critic_result = {"passed": True, "confidence": 0.5, "reasons": ["Parse error — defaulting to pass"], "feedback_for_executor": None}

    passed = critic_result.get("passed", True)
    new_loop_count = state["critic_loop_count"] + (0 if passed else 1)

    # Update task status
    tasks = list(state["tasks"])
    tasks[state["current_task_index"]] = {**current_task, "status": "passed" if passed else "failed_retrying"}

    status_msg = "✅ PASS" if passed else f"❌ FAIL (loop {new_loop_count}/3)"
    await _publish_log(
        state["session_id"], "critic",
        f"{status_msg} — {critic_result.get('reasons', [''])[0]}",
        critic_result
    )

    log.info("critic_result", passed=passed, confidence=critic_result.get("confidence"), loop=new_loop_count)

    return {
        "tasks": tasks,
        "critic_feedback": critic_result,
        "critic_loop_count": new_loop_count,
        "total_cost_usd": state["total_cost_usd"] + cost,
    }


async def synthesizer_node(state: AgentState) -> dict:
    """Compiles all verified context into a structured Markdown report."""
    log = logger.bind(session_id=state["session_id"], node="synthesizer")
    log.info("node_started")

    await _publish_log(state["session_id"], "synthesizer", "Compiling research into structured report...")

    human_feedback = state.get("human_feedback")
    feedback_note = f"\n\nHuman feedback to incorporate: {human_feedback}" if human_feedback else ""

    llm = get_synthesizer_llm()
    messages = [
        SystemMessage(content=SYNTHESIZER_PROMPT),
        HumanMessage(content=f"Original Query: {state['original_query']}\n\nVerified Context:\n{json.dumps(state['raw_context'], indent=2)}{feedback_note}"),
    ]

    response = await llm.ainvoke(messages)
    cost = _estimate_cost(response, "gemini-1.5-pro")
    draft = response.content

    log.info("synthesizer_finished", draft_length=len(draft))
    await _publish_log(state["session_id"], "synthesizer", f"Draft compiled ({len(draft.split())} words)")

    return {
        "synthesized_draft": draft,
        "human_feedback": None,  # Clear after use
        "total_cost_usd": state["total_cost_usd"] + cost,
    }


async def hitl_gate_node(state: AgentState, db, session) -> dict:
    """Pauses execution and awaits human approval."""
    from app.models.session import SessionStatus

    session.status = SessionStatus.AWAITING_APPROVAL
    session.draft_report = state["synthesized_draft"]
    session.checkpoint_data = dict(state)  # Save full state for resume
    await db.commit()

    await publish_event(state["session_id"], {
        "type": "HITL_READY",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "data": {
            "session_id": state["session_id"],
            "draft_word_count": len((state["synthesized_draft"] or "").split()),
            "source_count": len({c.get("source_url") for c in state["raw_context"] if c.get("source_url")}),
            "total_cost_usd": round(state["total_cost_usd"], 4),
        },
    })

    return {}


async def finalizer_node(state: AgentState, db, session) -> dict:
    """Finalizes the report and marks the session as COMPLETED."""
    from app.models.session import SessionStatus

    final_report = state["synthesized_draft"]  # Already approved
    elapsed = time.time() - state.get("start_time", time.time())

    session.status = SessionStatus.COMPLETED
    session.final_report = final_report
    session.total_cost_usd = round(state["total_cost_usd"], 6)
    session.total_tokens_input = state["total_tokens_input"]
    session.total_tokens_output = state["total_tokens_output"]
    session.elapsed_seconds = elapsed
    await db.commit()

    await publish_event(state["session_id"], {
        "type": "COMPLETED",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "data": {
            "session_id": state["session_id"],
            "elapsed_seconds": round(elapsed, 1),
            "total_cost_usd": round(state["total_cost_usd"], 4),
        },
    })

    return {"final_report": final_report}


async def error_handler_node(state: AgentState, db, session) -> dict:
    """Handles graceful fallback when budget or loop limit is exceeded."""
    from app.models.session import SessionStatus

    error_msg = state.get("error", "Budget or loop limit exceeded")
    session.status = SessionStatus.FAILED
    session.error_message = error_msg
    await db.commit()

    await publish_event(state["session_id"], {
        "type": "FAILED",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "data": {"error": error_msg},
    })

    return {}


# ─── Conditional Routing ─────────────────────────────────────────────────────────

def route_after_critic(state: AgentState) -> str:
    """Decides what happens after the Critic evaluates a task."""
    # Check cost budget
    if state["total_cost_usd"] >= settings.max_cost_per_session_usd:
        return "error"

    # Check critic result
    critic = state.get("critic_feedback", {})
    passed = critic.get("passed", True)

    if not passed and state["critic_loop_count"] < settings.max_critic_loops:
        return "executor"  # Retry

    # Move to next task
    next_idx = state["current_task_index"] + 1
    if next_idx < len(state["tasks"]):
        return "next_task"  # More tasks to do

    return "synthesizer"  # All tasks done


# ─── Main graph runner (simplified for M1) ───────────────────────────────────────

async def run_graph(initial_state: dict, db, session) -> None:
    """
    Simplified sequential graph runner for Milestone 1.
    Full LangGraph compilation with checkpointing comes in Milestone 2-3.
    """
    from app.models.session import SessionStatus

    state = AgentState(**initial_state)  # type: ignore

    try:
        # Node 1: Planner
        updates = await planner_node(state)
        state.update(updates)  # type: ignore

        # Node 2-3: Executor → Critic loop for each task
        for i, task in enumerate(state["tasks"]):
            state["current_task_index"] = i
            state["critic_loop_count"] = 0

            for loop in range(settings.max_critic_loops + 1):
                # Executor
                updates = await executor_node(state)
                state.update(updates)  # type: ignore

                # Check cost
                if state["total_cost_usd"] >= settings.max_cost_per_session_usd:
                    state["error"] = "Budget exceeded"
                    await error_handler_node(state, db, session)
                    return

                # Critic
                updates = await critic_node(state)
                state.update(updates)  # type: ignore

                if state["critic_feedback"].get("passed", False) or state["critic_loop_count"] >= settings.max_critic_loops:
                    break  # Move to next task

        # Node 4: Synthesizer
        updates = await synthesizer_node(state)
        state.update(updates)  # type: ignore

        # Node 5: HITL Gate (pause for human)
        await hitl_gate_node(state, db, session)
        # Pipeline pauses here — resumed via POST /approve

    except Exception as e:
        logger.error("graph_error", session_id=state["session_id"], error=str(e), exc_info=True)
        state["error"] = str(e)
        await error_handler_node(state, db, session)


# ─── Helpers ─────────────────────────────────────────────────────────────────────

async def _publish_log(session_id: str, agent_name: str, action: str, result: dict = None) -> None:
    """Publish an agent log event to the SSE channel."""
    await publish_event(session_id, {
        "type": "agent_log",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "data": {
            "agent_name": agent_name,
            "action": action,
            "result": result,
        },
    })


MODEL_COST_PER_1K = {
    "gemini-1.5-pro":   {"input": 0.00125, "output": 0.005},
    "gemini-1.5-flash": {"input": 0.000075, "output": 0.0003},
}

def _estimate_cost(response, model: str) -> float:
    """Estimate the cost of an LLM response from token usage."""
    try:
        usage = response.usage_metadata or {}
        in_tok  = usage.get("input_tokens", 0)
        out_tok = usage.get("output_tokens", 0)
        pricing = MODEL_COST_PER_1K.get(model, {"input": 0, "output": 0})
        return (in_tok / 1000 * pricing["input"]) + (out_tok / 1000 * pricing["output"])
    except Exception:
        return 0.0
