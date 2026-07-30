"""
The research agent pipeline as a real compiled LangGraph StateGraph
(docs/04_Agent_Design.md). No hand-rolled loop, no fail-open behavior.

    planner → executor(ToolNode loop) → critic ─┐
                     ▲            (fail, retries) │
                     └────────────────────────────┘
    (pass / retries exhausted) → next task or → synthesizer → hitl_gate
    hitl_gate --interrupt--> (approve) finalizer / (reject) synthesizer
    budget/time breach anywhere → failer
"""

from __future__ import annotations

import json
import re
import time

import structlog
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agent import prompts
from app.agent.events import emit
from app.agent.llm_factory import estimate_cost, get_llm, text_of, token_counts
from app.agent.runconfig import get_run_config
from app.agent.schemas import CriticVerdict, ExecutorOutput, PlannerOutput, Source
from app.agent.state import AgentState
from app.agent.tools import EXECUTOR_TOOLS

logger = structlog.get_logger()

_TOOLS_BY_NAME = {t.name: t for t in EXECUTOR_TOOLS}
_MAX_TOOL_ROUNDS = 8


# ── Structured-output helper ──────────────────────────────────────────────────────


async def _structured(role: str, messages: list, schema):
    """Invoke a role's model and return (parsed_model_or_None, cost, in_tok, out_tok).

    Real models use with_structured_output(include_raw=True) so usage_metadata is
    available for cost; fake models return JSON content we parse directly.
    """
    model = get_llm(role)
    if get_run_config().llm_mode == "fake":
        resp = await model.ainvoke(messages)
        cost = estimate_cost(resp, role)
        i, o = token_counts(resp)
        try:
            parsed = schema.model_validate_json(resp.content)
        except Exception:
            parsed = None
        return parsed, cost, i, o

    structured = model.with_structured_output(schema, include_raw=True)
    result = await structured.ainvoke(messages)
    raw = result.get("raw")
    cost = estimate_cost(raw, role) if raw is not None else 0.0
    i, o = token_counts(raw) if raw is not None else (0, 0)
    parsed = None if result.get("parsing_error") else result.get("parsed")
    return parsed, cost, i, o


def _parse_evidence(text: str) -> list[dict]:
    """Parse ExecutorOutput from a model answer, tolerating markdown fences/prose.

    Models frequently wrap JSON in ```json fences or add a sentence around it.
    A strict model_validate_json would reject those and we'd silently lose the
    whole task's evidence, so fall back to the outermost {...} span.
    """
    candidates = [text]
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fenced:
        candidates.append(fenced.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            return [e.model_dump() for e in ExecutorOutput.model_validate_json(candidate).evidence]
        except Exception:  # noqa: BLE001 — try the next shape
            continue
    return []


def _acc(state: AgentState, cost: float, i: int, o: int) -> dict:
    return {
        "cost_usd": state.get("cost_usd", 0.0) + cost,
        "tokens_input": state.get("tokens_input", 0) + i,
        "tokens_output": state.get("tokens_output", 0) + o,
    }


# ── Nodes ─────────────────────────────────────────────────────────────────────────


async def planner_node(state: AgentState) -> dict:
    sid = state["session_id"]
    await emit(sid, "agent_log", agent="planner", message="Decomposing the query into tasks…")
    messages = [
        SystemMessage(content=prompts.PLANNER_PROMPT_V2),
        HumanMessage(
            content=f"Research query: {state['original_query']}\nDepth: {state.get('research_depth', 'balanced')}"
        ),
    ]
    parsed, cost, i, o = await _structured("planner", messages, PlannerOutput)
    if parsed is None:
        parsed2, c2, i2, o2 = await _structured("planner", messages, PlannerOutput)  # one retry
        cost, i, o = cost + c2, i + i2, o + o2
        parsed = parsed2
    if parsed is None:
        return {"error": "planner: could not produce a valid task list", **_acc(state, cost, i, o)}

    tasks = [t.model_dump() for t in parsed.tasks]
    await emit(
        sid,
        "agent_log",
        agent="planner",
        message=f"Created {len(tasks)} research tasks",
        detail={"tasks": [t["query"] for t in tasks]},
    )
    return {
        "tasks": tasks,
        "current_task_index": 0,
        "evidence": [],
        "critic_retries": 0,
        **_acc(state, cost, i, o),
    }


async def executor_node(state: AgentState) -> dict:
    sid = state["session_id"]
    idx = state["current_task_index"]
    task = state["tasks"][idx]
    await emit(
        sid,
        "agent_log",
        agent="executor",
        message=f"Researching: '{task['query']}'",
        detail={"task_id": task["id"]},
    )

    model = get_llm("executor").bind_tools(EXECUTOR_TOOLS)
    messages: list = [
        SystemMessage(content=prompts.EXECUTOR_PROMPT_V2),
        HumanMessage(content=f"Task {task['id']}: {task['query']}"),
    ]
    verdict = state.get("critic_verdict")
    if verdict and not verdict.get("passed"):
        messages.append(
            HumanMessage(
                content=f"Previous attempt insufficient. Fix: "
                f"{verdict.get('feedback_for_executor', '')}"
            )
        )

    cost = 0.0
    i_tot = o_tot = 0
    for _round in range(_MAX_TOOL_ROUNDS):
        resp = await model.ainvoke(messages)
        cost += estimate_cost(resp, "executor")
        di, do = token_counts(resp)
        i_tot += di
        o_tot += do
        messages.append(resp)
        tool_calls = getattr(resp, "tool_calls", None) or []
        if not tool_calls:
            break
        for call in tool_calls:
            tool = _TOOLS_BY_NAME.get(call["name"])
            try:
                observation = (
                    await tool.ainvoke(call["args"]) if tool else f"unknown tool {call['name']}"
                )
            except Exception as e:  # noqa: BLE001
                observation = f"tool error: {e}"
            await emit(
                sid,
                "agent_log",
                agent="executor",
                message=f"Used {call['name']}",
                detail={"task_id": task["id"]},
            )
            messages.append(
                ToolMessage(content=json.dumps(observation, default=str), tool_call_id=call["id"])
            )

    # Convert the final answer into structured evidence.
    final = messages[-1]
    evidence: list[dict] = []
    final_text = text_of(final) if isinstance(final, AIMessage) else ""
    if final_text.strip():
        evidence = _parse_evidence(final_text)

    # The tool loop can finish without a parseable answer in two ways: it exhausted
    # _MAX_TOOL_ROUNDS while still calling tools (so the last message is a
    # ToolMessage, not the model's summary), or the model wrapped its JSON in prose.
    # Either way the observations are already in hand — ask once more, with no tools
    # bound, so the model must return them as structured output. Without this the run
    # silently yields zero evidence and the report reads "no evidence was provided".
    if not evidence:
        observations = "\n\n".join(
            text_of(m)[:4000] for m in messages if isinstance(m, ToolMessage)
        )[:24000]
        if observations.strip():
            logger.info(
                "executor_wrapup", session_id=sid, task_id=task["id"], reason="no_parsable_evidence"
            )
            parsed, c2, i2, o2 = await _structured(
                "executor",
                [
                    SystemMessage(content=prompts.EXECUTOR_PROMPT_V2),
                    HumanMessage(
                        content=f"Task {task['id']}: {task['query']}\n\n"
                        "You already gathered the observations below. Return them as "
                        "structured evidence — do not call any more tools.\n\n"
                        f"<untrusted_web_content>\n{observations}\n</untrusted_web_content>"
                    ),
                ],
                ExecutorOutput,
            )
            cost += c2
            i_tot += i2
            o_tot += o2
            if parsed is not None:
                evidence = [e.model_dump() for e in parsed.evidence]

    for e in evidence:
        e["task_id"] = task["id"]

    await emit(
        sid,
        "agent_log",
        agent="executor",
        message=f"Gathered {len(evidence)} source(s) for task {task['id']}",
        detail={"task_id": task["id"], "source_count": len(evidence)},
    )
    return {"evidence": state.get("evidence", []) + evidence, **_acc(state, cost, i_tot, o_tot)}


async def critic_node(state: AgentState) -> dict:
    sid = state["session_id"]
    task = state["tasks"][state["current_task_index"]]
    await emit(
        sid, "agent_log", agent="critic", message=f"Evaluating evidence for task {task['id']}…"
    )
    task_evidence = [e for e in state.get("evidence", []) if e.get("task_id") == task["id"]]
    messages = [
        SystemMessage(content=prompts.CRITIC_PROMPT_V2),
        HumanMessage(
            content=f"Task: {task['query']}\n\n<untrusted_web_content>\n"
            f"{json.dumps(task_evidence, indent=2)}\n</untrusted_web_content>"
        ),
    ]
    parsed, cost, i, o = await _structured("critic", messages, CriticVerdict)
    if parsed is None:
        # Fail closed (docs/11 §1 rule 2): invalid critic output is a failure, not a pass.
        verdict = CriticVerdict(
            passed=False,
            confidence=0.0,
            reasons=["critic output invalid — failing closed"],
            feedback_for_executor="Re-gather clearer, well-cited evidence.",
        )
    else:
        verdict = parsed

    passed = verdict.passed
    retries = state.get("critic_retries", 0) + (0 if passed else 1)
    await emit(
        sid,
        "agent_log",
        agent="critic",
        message=("✅ PASS" if passed else f"❌ FAIL (retry {retries})"),
        detail=verdict.model_dump(),
    )
    return {
        "critic_verdict": verdict.model_dump(),
        "critic_retries": retries,
        **_acc(state, cost, i, o),
    }


async def synthesizer_node(state: AgentState) -> dict:
    sid = state["session_id"]
    await emit(sid, "agent_log", agent="synthesizer", message="Compiling the report…")

    # Build a numbered source list from unique evidence URLs; the draft cites [n].
    sources: list[dict] = []
    seen: dict[str, int] = {}
    for e in state.get("evidence", []):
        url = e.get("source_url", "")
        if url and url not in seen:
            n = len(sources) + 1
            seen[url] = n
            sources.append(
                Source(
                    index=n, url=url, title=e.get("source_title", ""), snippet=e.get("snippet", "")
                ).model_dump()
            )

    numbered_evidence = [
        {
            "n": seen.get(e.get("source_url", ""), 0),
            "key_fact": e.get("key_fact", ""),
            "snippet": e.get("snippet", ""),
            "url": e.get("source_url", ""),
        }
        for e in state.get("evidence", [])
    ]
    fb = state.get("human_feedback")
    human = f"\n\nHuman feedback to incorporate: {fb}" if fb else ""
    messages = [
        SystemMessage(content=prompts.SYNTHESIZER_PROMPT_V2),
        HumanMessage(
            content=f"Original query: {state['original_query']}\n\nNumbered evidence:\n"
            f"{json.dumps(numbered_evidence, indent=2)}{human}"
        ),
    ]
    model = get_llm("synthesizer")
    resp = await model.ainvoke(messages)
    draft = text_of(resp)
    cost = estimate_cost(resp, "synthesizer")
    i, o = token_counts(resp)

    await emit(
        sid,
        "agent_log",
        agent="synthesizer",
        message=f"Draft compiled ({len(draft.split())} words, {len(sources)} sources)",
    )
    return {
        "draft_report": draft,
        "sources": sources,
        "human_feedback": None,
        **_acc(state, cost, i, o),
    }


def hitl_gate_node(state: AgentState) -> dict:
    """Pause for human review. interrupt() persists the checkpoint and suspends."""
    decision = interrupt(
        {
            "type": "HITL_READY",
            "word_count": len((state.get("draft_report") or "").split()),
            "source_count": len(state.get("sources", [])),
            "cost_usd": round(state.get("cost_usd", 0.0), 4),
        }
    )
    # Resumed: decision = {"approved": bool, "feedback": str | None}
    if decision.get("approved"):
        return {"approved": True}
    return {
        "approved": False,
        "human_feedback": decision.get("feedback"),
        "rework_count": state.get("rework_count", 0) + 1,
    }


def finalizer_node(state: AgentState) -> dict:
    return {"final_report": state.get("draft_report")}


def failer_node(state: AgentState) -> dict:
    return {"error": state.get("error") or "budget or loop limit exceeded"}


# ── Conditional routing ────────────────────────────────────────────────────────────


def _over_budget(state: AgentState) -> bool:
    cfg = get_run_config()
    return (
        state.get("cost_usd", 0.0) >= cfg.max_cost_per_session_usd
        or state.get("tokens_input", 0) >= 1_000_000
        or (time.time() - state.get("started_at", time.time())) >= cfg.max_wallclock_seconds
    )


def route_after_planner(state: AgentState) -> str:
    if state.get("error"):
        return "failer"
    return "executor"


def route_after_critic(state: AgentState) -> str:
    if _over_budget(state):
        return "failer"
    verdict = state.get("critic_verdict") or {}
    max_retries = get_run_config().max_critic_loops
    if not verdict.get("passed") and state.get("critic_retries", 0) < max_retries:
        return "executor"
    if state["current_task_index"] + 1 < len(state["tasks"]):
        return "next_task"
    return "synthesizer"


def advance_task_node(state: AgentState) -> dict:
    return {
        "current_task_index": state["current_task_index"] + 1,
        "critic_retries": 0,
        "critic_verdict": None,
    }


def route_after_gate(state: AgentState) -> str:
    if state.get("approved"):
        return "finalizer"
    return "synthesizer"  # rework with human_feedback


# ── Build ──────────────────────────────────────────────────────────────────────────


def build_graph(checkpointer):
    g = StateGraph(AgentState)
    g.add_node("planner", planner_node)
    g.add_node("executor", executor_node)
    g.add_node("critic", critic_node)
    g.add_node("advance_task", advance_task_node)
    g.add_node("synthesizer", synthesizer_node)
    g.add_node("hitl_gate", hitl_gate_node)
    g.add_node("finalizer", finalizer_node)
    g.add_node("failer", failer_node)

    g.add_edge(START, "planner")
    g.add_conditional_edges(
        "planner", route_after_planner, {"executor": "executor", "failer": "failer"}
    )
    g.add_edge("executor", "critic")
    g.add_conditional_edges(
        "critic",
        route_after_critic,
        {
            "executor": "executor",
            "next_task": "advance_task",
            "synthesizer": "synthesizer",
            "failer": "failer",
        },
    )
    g.add_edge("advance_task", "executor")
    g.add_edge("synthesizer", "hitl_gate")
    g.add_conditional_edges(
        "hitl_gate", route_after_gate, {"finalizer": "finalizer", "synthesizer": "synthesizer"}
    )
    g.add_edge("finalizer", END)
    g.add_edge("failer", END)
    return g.compile(checkpointer=checkpointer)
