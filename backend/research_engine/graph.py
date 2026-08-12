"""
The research agent pipeline as a real compiled LangGraph StateGraph
(docs/architecture/04_Agent_Design.md). No hand-rolled loop, no fail-open behavior.

    planner → executor(all pending tasks, in parallel) → critic(all, in parallel) ─┐
                     ▲                       (any task failed, retries remain)     │
                     └─────────────────────────────────────────────────────────────┘
    (every task passed or out of retries) → synthesizer → hitl_gate
    hitl_gate --interrupt--> (approve) finalizer / (reject) synthesizer
    budget/time breach anywhere → failer

Research runs in *rounds* rather than per-task pipelines (docs/12 M7): a round researches
every pending task concurrently, grades them all, and the failures retry together in the
next round. A per-task pipeline would let a fast task start its retry while a slow one is
still on its first pass, but it would also move the retry loop out of the graph and into
hand-rolled orchestration. Rounds are capped at `max_critic_loops`, so the barrier costs
little and the retry path stays a conditional edge in the compiled graph.
"""

from __future__ import annotations

import asyncio
import json
import re
import time

import structlog
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from pydantic import BaseModel, Field

from research_engine import prompts
from research_engine.events import emit
from research_engine.llm_factory import estimate_cost, get_llm, text_of, token_counts
from research_engine.runconfig import get_run_config
from research_engine.schemas import CriticVerdict, EvidenceChunk, ExecutorOutput, PlannerOutput, Source
from research_engine.state import AgentState
from research_engine.tools import EXECUTOR_TOOLS

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
    try:
        result = await structured.ainvoke(messages)
    except Exception:  # noqa: BLE001
        # with_structured_output can RAISE (not just set parsing_error) when a model
        # returns output the schema rejects — e.g. a local 7B emitting an out-of-range
        # field. Treat that as an unparseable result so the calling node fails CLOSED
        # (docs/11 §1), instead of letting the exception crash the whole pipeline.
        return None, 0.0, 0, 0
    raw = result.get("raw")
    cost = estimate_cost(raw, role) if raw is not None else 0.0
    i, o = token_counts(raw) if raw is not None else (0, 0)
    parsed = None if result.get("parsing_error") else result.get("parsed")
    return parsed, cost, i, o





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
        "evidence": [],
        "verdicts": {},
        "retries": {},
        "research_round": 0,
        **_acc(state, cost, i, o),
    }


# ── Parallel research rounds (docs/12 M7) ─────────────────────────────────────────


class _BudgetGuard:
    """Shared spend accounting for the tasks running in one round.

    Concurrency and a hard spend cap are in tension: N tasks that each check the budget
    before starting can all pass the check and then all spend. This guard narrows the
    window as far as it can be narrowed without pre-reserving budget — every task adds
    its cost the moment a model call returns, and every task re-checks before its next
    tool round or before being dispatched at all.

    So overshoot is *bounded by the calls already in flight*, not eliminated. Note the
    sequential version had the same property, just with a window of one: `_over_budget`
    was only consulted between tasks, after the spend had happened. Setting
    `max_parallel_tasks=1` restores exactly that.
    """

    def __init__(self, spent: float, limit: float) -> None:
        self._spent = spent
        self._limit = limit
        self._lock = asyncio.Lock()

    async def add(self, cost: float) -> None:
        async with self._lock:
            self._spent += cost

    def exceeded(self) -> bool:
        return self._spent >= self._limit

    @property
    def spent(self) -> float:
        return self._spent


def _task_key(task: dict) -> str:
    """Verdicts and retries are keyed by string — the checkpointer stores state as JSON."""
    return str(task.get("id"))


def _pending(state: AgentState, max_retries: int) -> list[dict]:
    """Tasks still needing work: never passed, and not yet out of retries."""
    verdicts = state.get("verdicts") or {}
    retries = state.get("retries") or {}
    out = []
    for task in state.get("tasks") or []:
        key = _task_key(task)
        if (verdicts.get(key) or {}).get("passed"):
            continue
        if retries.get(key, 0) >= max_retries:
            continue
        out.append(task)
    return out


class submit_evidence(BaseModel):
    """Submit the final gathered evidence for the task."""
    evidence: list[EvidenceChunk] = Field(default_factory=list, description="List of cited facts")

async def _research_one(state: AgentState, task: dict, guard: _BudgetGuard) -> dict:
    """Gather evidence for a single task. Returns {evidence, cost, tokens_in, tokens_out}."""
    sid = state["session_id"]
    feedback = ((state.get("verdicts") or {}).get(_task_key(task)) or {}).get(
        "feedback_for_executor"
    )

    await emit(
        sid,
        "agent_log",
        agent="executor",
        message=f"Researching: '{task['query']}'",
        detail={"task_id": task["id"]},
    )

    model = get_llm("executor").bind_tools(EXECUTOR_TOOLS + [submit_evidence])
    messages: list = [
        SystemMessage(content=prompts.EXECUTOR_PROMPT_V2),
        HumanMessage(content=f"Task {task['id']}: {task['query']}"),
    ]
    if feedback:
        messages.append(HumanMessage(content=f"Previous attempt insufficient. Fix: {feedback}"))

    cost = 0.0
    i_tot = o_tot = 0
    evidence: list[dict] = []
    for _round in range(_MAX_TOOL_ROUNDS):
        if guard.exceeded():
            logger.warning("executor_budget_stop", session_id=sid, task_id=task["id"])
            break
        resp = await model.ainvoke(messages)
        round_cost = estimate_cost(resp, "executor")
        cost += round_cost
        await guard.add(round_cost)
        di, do = token_counts(resp)
        i_tot += di
        o_tot += do
        messages.append(resp)
        tool_calls = getattr(resp, "tool_calls", None) or []
        if not tool_calls:
            break
        is_done = False
        for call in tool_calls:
            if call["name"] == "submit_evidence":
                try:
                    parsed = submit_evidence.model_validate(call["args"])
                    evidence = [e.model_dump() for e in parsed.evidence]
                    await emit(
                        sid,
                        "agent_log",
                        agent="executor",
                        message="Submitted evidence",
                        detail={"task_id": task["id"]},
                    )
                    is_done = True
                    break
                except Exception as e:
                    observation = f"submit_evidence validation error: {e}"
                    messages.append(
                        ToolMessage(content=json.dumps(observation, default=str), tool_call_id=call["id"])
                    )
                    continue

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
        if is_done:
            break

    for e in evidence:
        e["task_id"] = task["id"]

    await emit(
        sid,
        "agent_log",
        agent="executor",
        message=f"Gathered {len(evidence)} source(s) for task {task['id']}",
        detail={"task_id": task["id"], "source_count": len(evidence)},
    )
    return {"evidence": evidence, "cost": cost, "in": i_tot, "out": o_tot}


async def executor_node(state: AgentState) -> dict:
    """Research every pending task concurrently, bounded by `max_parallel_tasks`."""
    sid = state["session_id"]
    cfg = get_run_config()
    pending = _pending(state, cfg.max_critic_loops)
    round_no = state.get("research_round", 0) + 1

    if len(pending) > 1:
        await emit(
            sid,
            "agent_log",
            agent="executor",
            message=f"Round {round_no}: researching {len(pending)} tasks in parallel",
            detail={
                "round": round_no,
                "task_ids": [t["id"] for t in pending],
                "max_parallel": cfg.max_parallel_tasks,
            },
        )

    guard = _BudgetGuard(state.get("cost_usd", 0.0), cfg.max_cost_per_session_usd)
    semaphore = asyncio.Semaphore(max(1, cfg.max_parallel_tasks))

    async def bounded(task: dict) -> dict:
        async with semaphore:
            if guard.exceeded():
                logger.warning("executor_not_dispatched", session_id=sid, task_id=task["id"])
                return {"evidence": [], "cost": 0.0, "in": 0, "out": 0}
            return await _research_one(state, task, guard)

    # gather preserves argument order regardless of completion order, which is what keeps
    # the merge below deterministic.
    results = await asyncio.gather(*(bounded(t) for t in pending))

    fresh = {_task_key(t): r["evidence"] for t, r in zip(pending, results, strict=True)}
    previous = state.get("evidence") or []

    # Rebuild the whole evidence list in task-definition order: a task researched this
    # round contributes its new evidence, any other task keeps what it already had. Order
    # must not depend on which task finished first or the synthesizer would renumber
    # citations between otherwise identical runs.
    merged: list[dict] = []
    for task in state.get("tasks") or []:
        key = _task_key(task)
        if key in fresh:
            merged.extend(fresh[key])
        else:
            merged.extend(e for e in previous if str(e.get("task_id")) == key)

    cost = sum(r["cost"] for r in results)
    i_tot = sum(r["in"] for r in results)
    o_tot = sum(r["out"] for r in results)
    return {
        "evidence": merged,
        "research_round": round_no,
        **_acc(state, cost, i_tot, o_tot),
    }


async def _criticize_one(
    state: AgentState, task: dict
) -> tuple[str, CriticVerdict, float, int, int]:
    task_evidence = [
        e for e in state.get("evidence", []) if str(e.get("task_id")) == _task_key(task)
    ]
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
        parsed = CriticVerdict(
            passed=False,
            confidence=0.0,
            reasons=["critic output invalid — failing closed"],
            feedback_for_executor="Re-gather clearer, well-cited evidence.",
        )
    return _task_key(task), parsed, cost, i, o


async def critic_node(state: AgentState) -> dict:
    """Grade every task researched this round, concurrently."""
    sid = state["session_id"]
    cfg = get_run_config()
    pending = _pending(state, cfg.max_critic_loops)

    await emit(
        sid,
        "agent_log",
        agent="critic",
        message=f"Evaluating evidence for {len(pending)} task(s)…",
        detail={"task_ids": [t["id"] for t in pending]},
    )

    semaphore = asyncio.Semaphore(max(1, cfg.max_parallel_tasks))

    async def bounded(task: dict):
        async with semaphore:
            return await _criticize_one(state, task)

    results = await asyncio.gather(*(bounded(t) for t in pending))

    verdicts = dict(state.get("verdicts") or {})
    retries = dict(state.get("retries") or {})
    cost, i_tot, o_tot = 0.0, 0, 0

    for key, verdict, c, i, o in results:
        verdicts[key] = verdict.model_dump()
        if not verdict.passed:
            retries[key] = retries.get(key, 0) + 1
        cost += c
        i_tot += i
        o_tot += o
        await emit(
            sid,
            "agent_log",
            agent="critic",
            message=(
                f"✅ PASS task {key}"
                if verdict.passed
                else f"❌ FAIL task {key} (retry {retries[key]})"
            ),
            detail={"task_id": key, **verdict.model_dump()},
        )

    return {
        "verdicts": verdicts,
        "retries": retries,
        **_acc(state, cost, i_tot, o_tot),
    }


async def synthesizer_node(state: AgentState) -> dict:
    sid = state["session_id"]
    await emit(sid, "agent_log", agent="synthesizer", message="Compiling the report…")

    # Build a numbered source list from unique evidence URLs; the draft cites [n].
    #
    # Every distinct snippet from a source is kept, not just the first (docs/12 M5, D3).
    # One page commonly backs several different facts and the executor extracts a separate
    # verbatim quote for each; retaining only one meant a citation chip could display text
    # unrelated to the claim it was attached to — the same source is cited for roughly
    # eight different claims per report.
    sources: list[dict] = []
    seen: dict[str, int] = {}
    for e in state.get("evidence", []):
        url = e.get("source_url", "")
        if not url:
            continue
        snippet = (e.get("snippet") or "").strip()
        if url not in seen:
            n = len(sources) + 1
            seen[url] = n
            sources.append(
                Source(
                    index=n,
                    url=url,
                    title=e.get("source_title", ""),
                    snippet=snippet,
                    snippets=[snippet] if snippet else [],
                ).model_dump()
            )
        elif snippet:
            existing = sources[seen[url] - 1]
            if snippet not in existing["snippets"]:
                existing["snippets"].append(snippet)
            if not existing["snippet"]:
                existing["snippet"] = snippet

    numbered_evidence = [
        {
            "n": seen.get(e.get("source_url", ""), 0),
            "key_fact": e.get("key_fact", ""),
            "snippet": e.get("snippet", ""),
            "url": e.get("source_url", ""),
        }
        for e in state.get("evidence", [])
    ]

    evidence_lines: list[str] = []
    for ev in numbered_evidence:
        evidence_lines.append(
            f"[{ev['n']}] Fact: \"{ev['key_fact']}\""
        )
        evidence_lines.append(
            f"    Source: {ev['url']}"
        )
        evidence_lines.append(
            f"    Snippet: \"{ev['snippet']}...\""
        )
        evidence_lines.append("")  # blank separator
    evidence_text = "Evidence for citation:\n" + "\n".join(evidence_lines)

    fb = state.get("human_feedback")
    human = f"\n\nHuman feedback to incorporate: {fb}" if fb else ""
    messages = [
        SystemMessage(content=prompts.SYNTHESIZER_PROMPT_V2),
        HumanMessage(
            content=f"Original query: {state['original_query']}\n\n{evidence_text}{human}"
        ),
    ]
    model = get_llm("synthesizer")
    resp = await model.ainvoke(messages)
    draft = text_of(resp)
    cost = estimate_cost(resp, "synthesizer")
    i, o = token_counts(resp)

    # Citation repair pass: fix uncited claims if any exist.
    # Inline uncited-count to avoid a cross-package dependency on evals.metrics:
    # count sentences that contain assertive text but carry no [n] marker.
    _claim_re = re.compile(r"\[\d+\]")
    uncited = 0
    for _sentence in re.split(r"(?<=[.!?])\s+", draft):
        s = _sentence.strip()
        if len(s) < 15 or not re.search(r"[A-Za-z]", s):
            continue
        if not _claim_re.search(s):
            uncited += 1
    if uncited > 0:
        repair_messages = [
            SystemMessage(content=prompts.SYNTHESIZER_REPAIR_PROMPT),
            HumanMessage(
                content=f"Draft report with {uncited} uncited sentences:\n\n{draft}\n\n"
                f"Numbered evidence:\n{evidence_text}"
            ),
        ]
        repair_resp = await model.ainvoke(repair_messages)
        draft = text_of(repair_resp)
        repair_cost = estimate_cost(repair_resp, "synthesizer")
        ri, ro = token_counts(repair_resp)
        cost += repair_cost
        i += ri
        o += ro
        await emit(
            sid,
            "agent_log",
            agent="synthesizer",
            message=f"Citation repair: fixed {uncited} uncited claims",
        )

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
    """Another research round, or synthesize.

    A task leaves the pending set when it passes *or* runs out of retries — so a task
    whose evidence never satisfies the critic still contributes what it found, exactly as
    it did when tasks ran one at a time.
    """
    if _over_budget(state):
        return "failer"
    if _pending(state, get_run_config().max_critic_loops):
        return "executor"
    return "synthesizer"


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
            "synthesizer": "synthesizer",
            "failer": "failer",
        },
    )
    g.add_edge("synthesizer", "hitl_gate")
    g.add_conditional_edges(
        "hitl_gate", route_after_gate, {"finalizer": "finalizer", "synthesizer": "synthesizer"}
    )
    g.add_edge("finalizer", END)
    g.add_edge("failer", END)
    return g.compile(checkpointer=checkpointer)
