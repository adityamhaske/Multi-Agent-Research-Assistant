"""
The research agent pipeline as a real compiled LangGraph StateGraph
(docs/architecture/04-agent-architecture.md). No hand-rolled loop, no fail-open behavior.

    planner → executor(all pending tasks, in parallel) → critic(all, in parallel) ─┐
                     ▲                       (any task failed, retries remain)     │
                     └─────────────────────────────────────────────────────────────┘
    (every task passed or out of retries) → contradiction_detector → synthesizer → hitl_gate
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
from contextvars import ContextVar
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel, Field, model_validator

from research_engine import claims, contradictions, outlines, prompts
from research_engine.events import emit
from research_engine.llm_factory import (
    estimate_cost,
    get_llm,
    served_model_id,
    text_of,
    token_counts,
)
from research_engine.runconfig import get_run_config
from research_engine.schemas import (
    ContradictionReport,
    CriticVerdict,
    EvidenceChunk,
    ExecutorOutput,
    PlannerOutput,
    Source,
)
from research_engine.state import AgentState
from research_engine.tools import EXECUTOR_TOOLS

logger = structlog.get_logger()

_TOOLS_BY_NAME = {t.name: t for t in EXECUTOR_TOOLS}
_MAX_TOOL_ROUNDS = 8

#: How many pages one task may open before it must stop reading and submit what it has.
#:
#: A termination control, not a cost one. A model under no obligation to conclude will
#: graze: run `96a16137` spent every round of every retry on another search or fetch and
#: submitted nothing, twice. Reading is bounded so the task always reaches the extraction
#: step with the sources it has, rather than reaching the end of its rounds with none.
_MAX_PAGES_PER_TASK = 5

#: Per-source ceiling on the text handed to the forced extraction pass.
#:
#: Truncating here is safe in the one way that matters: `verify_evidence_snippets` checks
#: quotations against the *whole* of `seen_text`, so a snippet taken from the part we sent
#: always verifies. The cap bounds one request, it does not narrow what counts as seen.
_FORCED_SUBMIT_SOURCE_CHARS = 6_000

#: How many sources the forced extraction pass is shown, richest first.
#:
#: A task accumulates far more one-line search hits than read pages, and handing a model
#: nineteen sources of which fourteen are a sentence long buries the page bodies that
#: actually carry quotable text. Bounded for focus, not for cost.
_FORCED_SUBMIT_SOURCES = 8


# ── Structured-output helper ──────────────────────────────────────────────────────

# Provider errors observed inside `_structured`. The call itself still returns a
# parse-shaped result (fail-closed, docs/11 §1), but a caller that cares WHY it got
# nothing — the planner, whose "invalid task list" message masked an exhausted API
# quota for 8 of 10 eval queries — reads this to report the real cause.
_last_api_error: ContextVar[str | None] = ContextVar("last_api_error", default=None)


def _looks_like_quota(msg: str) -> bool:
    """Whether a provider error is a spend/quota exhaustion — hopeless to retry.

    Matched on class names and message text so the engine stays provider-agnostic
    (no google/openai/anthropic import in its dependency tree, docs/12 M6).
    """
    m = msg.lower()
    return any(
        marker in m
        for marker in (
            "resource_exhausted",
            "spending cap",
            "quota",
            "rate limit",
            "ratelimit",
            "429",
            "insufficient_quota",
        )
    )


async def _structured(role: str, messages: list, schema):
    """Invoke a role's model and return (parsed_model_or_None, cost, in_tok, out_tok).

    Real models use with_structured_output(include_raw=True) so usage_metadata is
    available for cost; fake models return JSON content we parse directly.
    """
    _last_api_error.set(None)
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
    except Exception as e:  # noqa: BLE001
        # with_structured_output can RAISE (not just set parsing_error) when a model
        # returns output the schema rejects — e.g. a local 7B emitting an out-of-range
        # field — or when the PROVIDER rejects the request outright (429 quota,
        # network). Treat both as an unparseable result so the calling node fails
        # CLOSED (docs/11 §1), instead of letting the exception crash the whole
        # pipeline — but record the message so provider errors are reported as
        # provider errors, not misread as garbage output.
        _last_api_error.set(str(e)[:400])
        return None, 0.0, 0, 0
    raw = result.get("raw")
    cost = estimate_cost(raw, role) if raw is not None else 0.0
    i, o = token_counts(raw) if raw is not None else (0, 0)
    parsed = None if result.get("parsing_error") else result.get("parsed")
    if parsed is None and raw is not None and getattr(raw, "content", None):
        content = raw.content
        if isinstance(content, str) and content.strip():
            cleaned = content.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
                cleaned = re.sub(r"\s*```$", "", cleaned)
            try:
                parsed = schema.model_validate_json(cleaned)
            except Exception:
                match = re.search(r"\{.*\}", cleaned, re.DOTALL)
                if match:
                    try:
                        parsed = schema.model_validate_json(match.group(0))
                    except Exception:
                        pass
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
    cfg = get_run_config()
    await emit(
        sid,
        "agent_log",
        agent="planner",
        message="Decomposing the query into tasks…",
        detail={
            "query": state["original_query"],
            "depth": state.get("research_depth", "balanced"),
            # Requirement 1 (docs/07 §2): the full role→route mapping, disclosed at plan
            # time — before a single task or dollar is spent — not just in the finished
            # report. `model` on every node's own kickoff event (below) is this same
            # data, one role at a time, for a node emitted well after this one.
            "models": dict(cfg.models),
            "model": cfg.model_for("planner"),
        },
    )
    messages = [
        SystemMessage(content=prompts.PLANNER_PROMPT_V2),
        HumanMessage(
            content=prompts.planner_human(
                state["original_query"],
                state.get("research_depth", "balanced"),
                cfg.topic_seeds,
            )
        ),
    ]

    async def _attempt():
        _last_api_error.set(None)
        try:
            parsed, cost, i, o = await _structured("planner", messages, PlannerOutput)
        except Exception as e:  # noqa: BLE001
            # Defence in depth: `_structured` is fail-closed and normally never raises,
            # but if it ever does the planner must report the provider error, not crash.
            return None, 0.0, 0, 0, str(e)[:400]
        return parsed, cost, i, o, _last_api_error.get()

    parsed, cost, i, o, api_err = await _attempt()
    if api_err and _looks_like_quota(api_err):
        # An exhausted spend cap will not recover within this run; a retry only spends
        # time. Surface the provider's own message — the eval run that read "could not
        # produce a valid task list" eight times was actually this.
        logger.error("planner_quota_exhausted", session_id=sid, error=api_err)
        return {
            "error": f"planner: provider error — {api_err}",
            **_acc(state, cost, i, o),
        }
    if parsed is None:
        parsed2, c2, i2, o2, api_err2 = await _attempt()  # one retry
        cost, i, o = cost + c2, i + i2, o + o2
        parsed, api_err = parsed2, api_err2
    if parsed is None:
        if api_err:
            logger.error("planner_provider_error", session_id=sid, error=api_err)
            return {
                "error": f"planner: provider error — {api_err}",
                **_acc(state, cost, i, o),
            }
        return {"error": "planner: could not produce a valid task list", **_acc(state, cost, i, o)}

    tasks = [t.model_dump() for t in parsed.tasks]
    # An explicitly chosen template outranks whatever the model proposed: the researcher
    # picked a structure before the run started, and quietly replacing it with the
    # planner's own idea would make the picker decorative. With no template chosen this
    # is empty and the planner's proposal stands, which is today's behaviour.
    outline = outlines.sections_for(cfg.outline_template) or [
        s.model_dump() for s in parsed.proposed_outline
    ]
    await emit(
        sid,
        "agent_log",
        agent="planner",
        message=f"Created {len(tasks)} research tasks",
        detail={"tasks": tasks, "proposed_outline": outline},
    )
    return {
        "tasks": tasks,
        "proposed_outline": outline,
        "plan_approved": None,
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
        # 0 = unlimited, matching `_over_budget`. Without the guard on `_limit`, a zero
        # cap reads as "already exceeded" at zero spend and every task is skipped before
        # it runs — the second home of this rule, and the one easy to miss.
        return bool(self._limit) and self._spent >= self._limit

    @property
    def spent(self) -> float:
        return self._spent


# Typographic substitutions a faithful quoter still makes: re-wrapping lines, or a model
# straightening curly quotes. Folding these is not leniency about fabrication — it stops
# the check firing on quotes that ARE in the source.
_QUOTE_FOLD = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})


def _norm_text(text: str) -> str:
    """Whitespace- and case-insensitive form, with smart punctuation folded to ASCII."""
    return " ".join((text or "").translate(_QUOTE_FOLD).split()).lower()


def _norm_url(url: str) -> str:
    u = (url or "").strip().rstrip("/").lower()
    if u.startswith("https://"):
        u = u[8:]
    elif u.startswith("http://"):
        u = u[7:]
    if u.startswith("www."):
        u = u[4:]
    return u.rstrip("/")


def record_tool_output(seen: dict[str, str], tool_name: str, observation) -> None:
    """Accumulate what each tool actually returned, keyed by URL.

    This is the only record of what the executor really saw. `submit_evidence` arguments
    are model-authored end to end — `source_url`, `source_title` and `snippet` alike — and
    engine code overwrites exactly one field afterwards (`task_id`). Without this record
    there is nothing to check a quotation against.

    Keyed by the URL **as the tool reported it**, scheme and all. Matching is
    case/scheme-insensitive and happens at lookup (`_seen_get`, `verify_evidence_snippets`),
    so normalising the key here would only discard the one thing a citation needs: a URL a
    reader can open. Storing the normalised form cost exactly that — snippet repair wrote
    `a.example/paper` into `source_url` and every downstream link stopped resolving.
    """
    if tool_name == "read_webpage" and isinstance(observation, dict):
        body = observation.get("text") or ""
        for key in (observation.get("url"), observation.get("final_url")):
            if key:
                seen[key] = seen.get(key, "") + "\n" + body
    elif tool_name == "web_search" and isinstance(observation, list):
        # A snippet may legitimately be quoted from a search result rather than a fetched
        # page, so search hits count as seen text too.
        for hit in observation:
            if isinstance(hit, dict) and hit.get("url"):
                key = hit["url"]
                seen[key] = seen.get(key, "") + "\n" + (hit.get("snippet") or "")


def _seen_get(seen: dict[str, str], url: str | None) -> str:
    """Text fetched for `url`, matched without regard to scheme, case or trailing slash."""
    target = _norm_url(url or "")
    if not target:
        return ""
    return "\n".join(text for key, text in seen.items() if _norm_url(key) == target)


def verify_evidence_snippets(evidence: list[dict], seen: dict[str, str]) -> list[dict]:
    """Blank every snippet that does not occur in what the tools actually returned.

    An unresolvable citation renders a ⚠ chip and tells the reader it failed. A fabricated
    snippet renders clean, resolves to a real URL, and shows a quotation in quote marks
    that was never written — strictly worse, and precisely the failure this product exists
    to prevent.

    Not hypothetical. On 2026-08-16 a real-model run attributed "For overlap heatmaps
    prefer Morisita-Horn (abundance-weighted, depth-robust) over Jaccard (presence/absence,
    depth-biased), and normalize depth first" to PMC3543521. That paper contains no such
    sentence, and the citation rendered clean because nothing checked it.

    Blanking rather than dropping the chunk: `key_fact` and the URL may still be sound, and
    `_number_sources` already skips empty snippets, so the citation loses its quote instead
    of displaying an invented one. Returns the chunks that failed, for logging.

    Repair, not laundering: a model that quotes a page faithfully but labels it with the
    wrong URL has made a citation error, and blanking a genuine quotation over it throws
    away real evidence. So a snippet that is verbatim in exactly ONE other fetched source
    is re-pointed at that source — and the URL the model claimed is kept on the chunk under
    `snippet_reattributed`, because a repair a reader cannot see is a silent rewrite of what
    the model said. Two conditions keep this from becoming a guess:

    - **exactly one** match, or the chunk is blanked like any other unverifiable quote. A
      sentence appearing in several fetched pages has no determinable source, and taking
      whichever the dict yielded first would attribute the same run differently on a rerun.
    - the URL written back is the one the tool reported, scheme intact — see
      `record_tool_output` on why `seen` is keyed that way.
    """
    fabricated: list[dict] = []

    for chunk in evidence:
        snippet = chunk.get("snippet") or ""
        if not snippet.strip():
            continue

        claimed = chunk.get("source_url", "")
        norm_snip = _norm_text(snippet)
        if norm_snip in _norm_text(_seen_get(seen, claimed)):
            continue

        matches = [url for url, text in seen.items() if norm_snip in _norm_text(text)]
        # Several keys can be the same page (a redirect records both `url` and
        # `final_url`), which is one source, not an ambiguity.
        if len({_norm_url(u) for u in matches}) == 1:
            chunk["source_url"] = matches[0]
            chunk["snippet_reattributed"] = claimed
            continue

        chunk["snippet"] = ""
        chunk["snippet_unverified"] = True
        fabricated.append(chunk)
    return fabricated


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

    @model_validator(mode="before")
    @classmethod
    def _normalize_payload(cls, data: Any) -> Any:
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                return {"evidence": []}
        if isinstance(data, list):
            return {"evidence": data}
        if isinstance(data, dict):
            raw = data.get("evidence")
            if isinstance(raw, str):
                try:
                    data["evidence"] = json.loads(raw)
                except Exception:
                    data["evidence"] = []
        return data


def _parse_submission(args: Any) -> list[dict]:
    """Validate one `submit_evidence` payload into evidence dicts. Raises on rejection.

    Truncate to the configured cap before validation (docs/07 §2, Phase 3) — this can only
    tighten `EvidenceChunk.snippet`'s own max_length=500, never loosen it, since the
    config's default (500) equals that ceiling and nothing here raises it.
    """
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = {}
    if isinstance(args, list):
        args = {"evidence": args}
    elif not isinstance(args, dict):
        args = {}

    raw_evidence = args.get("evidence")
    if isinstance(raw_evidence, str):
        try:
            args["evidence"] = json.loads(raw_evidence)
        except Exception:
            args["evidence"] = []

    snip_cap = get_run_config().snippet_max_chars
    for item in args.get("evidence", []) or []:
        if isinstance(item, dict) and isinstance(item.get("snippet"), str):
            item["snippet"] = item["snippet"][:snip_cap]
    return [e.model_dump() for e in submit_evidence.model_validate(args).evidence]


async def _forced_submit(
    sid: str, task: dict, seen_text: dict[str, str], guard: _BudgetGuard
) -> tuple[list[dict], float, int, int]:
    """Ask for the evidence directly, when the model never offered it.

    The executor's tool loop *invites* `submit_evidence`; nothing obliges a model to
    accept. Run `96a16137` searched and fetched successfully and then simply kept
    searching until it ran out of rounds — evidence `[]`, twice, and a failed run whose
    stated reason was to go check a search provider that had answered every query. A model
    declining to call one tool must not be able to discard text the engine already holds.

    Two constraints make this an extraction step rather than a second opinion:

    - it is handed **only** `seen_text`, so there is no route by which model memory can
      become a citation, and
    - `verify_evidence_snippets` still rules on what comes back, exactly as it does for a
      voluntary submission.

    **Two mechanisms, because one is not reliable on a router alias.** `custom:auto/*`
    resolves per call — a single task was served by three different models in one observed
    run — and a named `tool_choice` that most honour, some silently ignore, returning an
    assistant message with no tool call. So a refusal is retried as structured output,
    which is a differently shaped request rather than the same one twice.

    Returns empty when nothing was fetched. A task with no sources in hand has nothing to
    quote, and asking anyway is asking a model to invent one.
    """
    sources = {url: text for url, text in seen_text.items() if (text or "").strip()}
    if not sources or guard.exceeded():
        return [], 0.0, 0, 0

    # Richest sources first. A run accumulates far more search hits than read pages, and a
    # one-line hit crowds out the page bodies that actually carry quotable text. Dropping
    # the tail costs nothing: `verify_evidence_snippets` still rules against the whole of
    # `seen_text`, so anything quoted from what we send verifies either way.
    ranked = sorted(sources.items(), key=lambda kv: len(kv[1]), reverse=True)
    digest = json.dumps(
        {url: text[:_FORCED_SUBMIT_SOURCE_CHARS] for url, text in ranked[:_FORCED_SUBMIT_SOURCES]},
        indent=1,
        default=str,
    )
    messages = [
        SystemMessage(content=prompts.EXECUTOR_PROMPT_V2),
        HumanMessage(
            content=(
                f"Task {task['id']}: {task['query']}\n\n"
                "Stop searching. Below is every source already fetched for this task, "
                "keyed by URL. Report the findings it supports now. "
                "Each snippet must be copied VERBATIM from the text of its own URL — a "
                "quotation that is not in its source is dropped. If a source supports "
                "nothing relevant, leave it out.\n\n"
                f"<untrusted_web_content>\n{digest}\n</untrusted_web_content>"
            )
        ),
    ]

    cost = 0.0
    i_tot = o_tot = 0
    evidence: list[dict] = []

    for mechanism in ("tool_choice", "structured"):
        if guard.exceeded():
            break
        try:
            if mechanism == "tool_choice":
                # Preferred: reuses the schema, validation and truncation the voluntary
                # path already goes through, so both routes into `evidence` are one code
                # path.
                model = get_llm("executor").bind_tools(
                    [submit_evidence], tool_choice="submit_evidence"
                )
                resp = await model.ainvoke(messages)
                cost += estimate_cost(resp, "executor")
                di, do = token_counts(resp)
                i_tot += di
                o_tot += do
                calls = [
                    c
                    for c in (getattr(resp, "tool_calls", None) or [])
                    if c["name"] == "submit_evidence"
                ]
                if not calls:
                    logger.warning(
                        "forced_submit_returned_nothing",
                        session_id=sid,
                        task_id=task["id"],
                        mechanism=mechanism,
                        served_model=served_model_id(resp),
                        text=(text_of(resp) or "")[:200],
                    )
                    continue
                evidence = _parse_submission(calls[0]["args"])
            else:
                parsed, c, di, do = await _structured("executor", messages, ExecutorOutput)
                cost += c
                i_tot += di
                o_tot += do
                if parsed is None:
                    logger.warning(
                        "forced_submit_returned_nothing",
                        session_id=sid,
                        task_id=task["id"],
                        mechanism=mechanism,
                        error=(_last_api_error.get() or "")[:200],
                    )
                    continue
                evidence = _parse_submission(
                    {"evidence": [e.model_dump() for e in parsed.evidence]}
                )
        except Exception as e:  # noqa: BLE001
            # Fail closed and *say so*. A provider error here costs the task its evidence,
            # so it must never be reported as "the sources supported nothing".
            logger.warning(
                "forced_submit_failed",
                session_id=sid,
                task_id=task["id"],
                mechanism=mechanism,
                error=str(e)[:400],
            )
            continue
        finally:
            await guard.add(cost)

        if evidence:
            await emit(
                sid,
                "agent_log",
                agent="executor",
                message=(
                    f"Extracted {len(evidence)} evidence item(s) for task {task['id']} from "
                    f"the {len(sources)} source(s) already fetched — the model did not "
                    f"submit on its own"
                ),
                detail={
                    "task_id": task["id"],
                    "forced": True,
                    "mechanism": mechanism,
                    "evidence": evidence,
                },
            )
            return evidence, cost, i_tot, o_tot

    return [], cost, i_tot, o_tot


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
        detail={
            "task_id": task["id"],
            "query": task["query"],
            "feedback": feedback,
            "model": get_run_config().model_for("executor"),
        },
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
    submitted = False
    # What the tools actually returned, keyed by URL — the only record of what the
    # executor really saw. See `verify_evidence_snippets`.
    seen_text: dict[str, str] = {}
    # Pages already opened this task, so a second request for one is answered from
    # `seen_text` instead of the network. The observed run re-read one arXiv page five
    # times inside a single task, spending a round and a fetch each time to learn nothing.
    fetched: set[str] = set()
    for _round in range(_MAX_TOOL_ROUNDS):
        if guard.exceeded():
            logger.warning("executor_budget_stop", session_id=sid, task_id=task["id"])
            break
        if len(fetched) >= _MAX_PAGES_PER_TASK:
            # Enough sources are in hand; the forced pass below turns them into evidence.
            logger.info("executor_read_limit", session_id=sid, task_id=task["id"])
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
                    evidence = _parse_submission(call["args"])
                    thought_snippet = text_of(resp) if resp else ""
                    await emit(
                        sid,
                        "agent_log",
                        agent="executor",
                        message=f"Submitted {len(evidence)} evidence item(s) for task {task['id']}",
                        detail={
                            "task_id": task["id"],
                            "thought": thought_snippet[:2000] if thought_snippet else None,
                            "evidence": evidence,
                        },
                    )
                    submitted = True
                    is_done = True
                    break
                except Exception as e:
                    # Report it. Swallowed into a tool observation, a model calling this
                    # with bad arguments every round was indistinguishable from one that
                    # never called it — the two have completely different remedies.
                    logger.warning(
                        "submit_evidence_rejected",
                        session_id=sid,
                        task_id=task["id"],
                        forced=False,
                        error=str(e)[:400],
                    )
                    observation = f"submit_evidence validation error: {e}"
                    messages.append(
                        ToolMessage(
                            content=json.dumps(observation, default=str), tool_call_id=call["id"]
                        )
                    )
                    continue

            url = (call.get("args") or {}).get("url")
            if call["name"] == "read_webpage" and _norm_url(url) in fetched:
                # Already open in `seen_text`; refetching cannot produce new text, and the
                # round it costs is a round not spent concluding.
                observation = {
                    "url": url,
                    "text": _seen_get(seen_text, url),
                    "error": None,
                    "note": "already read this page — quote it or move on",
                }
            else:
                tool = _TOOLS_BY_NAME.get(call["name"])
                try:
                    observation = (
                        await tool.ainvoke(call["args"]) if tool else f"unknown tool {call['name']}"
                    )
                except Exception as e:  # noqa: BLE001
                    observation = f"tool error: {e}"
                if call["name"] == "read_webpage" and url:
                    fetched.add(_norm_url(url))
            record_tool_output(seen_text, call["name"], observation)

            # Extract thought or query details
            tool_args = call.get("args") or {}
            search_query = tool_args.get("query") or tool_args.get("url") or ""
            thought_snippet = text_of(resp) if resp else ""

            detail_payload = {
                "task_id": task["id"],
                "tool": call["name"],
                "args": tool_args,
                "thought": thought_snippet[:2000] if thought_snippet else None,
                "observation": str(observation)[:4000] if observation else None,
            }

            msg_suffix = f': "{search_query}"' if search_query else ""
            await emit(
                sid,
                "agent_log",
                agent="executor",
                message=f"Used {call['name']}{msg_suffix}",
                detail=detail_payload,
            )
            messages.append(
                ToolMessage(content=json.dumps(observation, default=str), tool_call_id=call["id"])
            )
        if is_done:
            break

    # The model finished its turns without ever submitting. Ask it directly rather than
    # letting the text we already fetched fall on the floor — see `_forced_submit`.
    if not submitted:
        evidence, fcost, fi, fo = await _forced_submit(sid, task, seen_text, guard)
        cost += fcost
        i_tot += fi
        o_tot += fo

    # Before anything downstream can render these as verbatim quotations.
    #
    # Real mode only, and that is a limitation rather than a design choice. Scripted fake
    # executors submit evidence without necessarily calling a tool first, so `seen_text`
    # is empty and every fixture snippet would be blanked — which broke the corpus
    # contradiction test. The right fix is self-consistent fixtures (a fake that quotes
    # only what its fake tools returned), and until then this check does not run where CI
    # runs, so it cannot catch a regression in it. The danger it guards is real models
    # inventing quotations, so guarding real mode is where the value is.
    fabricated = (
        verify_evidence_snippets(evidence, seen_text) if get_run_config().llm_mode != "fake" else []
    )
    if fabricated:
        logger.warning(
            "evidence_snippet_unverified",
            session_id=sid,
            task_id=task["id"],
            count=len(fabricated),
            urls=[c.get("source_url", "") for c in fabricated][:5],
        )
        await emit(
            sid,
            "agent_log",
            agent="executor",
            message=(
                f"Dropped {len(fabricated)} snippet(s) that did not appear in the fetched "
                f"source — a quote we cannot find is not evidence"
            ),
            detail={"task_id": task["id"], "urls": [c.get("source_url", "") for c in fabricated]},
        )

    # A repaired citation is not a clean one. `verify_evidence_snippets` re-points a quote
    # it found in a different fetched page, and that changes what the model said its source
    # was — so it is reported here rather than left to be noticed in a diff of the bundle.
    repaired = [c for c in evidence if c.get("snippet_reattributed")]
    if repaired:
        logger.warning(
            "evidence_snippet_reattributed",
            session_id=sid,
            task_id=task["id"],
            count=len(repaired),
            moves=[(c["snippet_reattributed"], c.get("source_url", "")) for c in repaired][:5],
        )
        await emit(
            sid,
            "agent_log",
            agent="executor",
            message=(
                f"Re-attributed {len(repaired)} quotation(s) to the page they were actually "
                f"found on — the model cited a source that does not contain them"
            ),
            detail={
                "task_id": task["id"],
                "moves": [
                    {"claimed": c["snippet_reattributed"], "actual": c.get("source_url", "")}
                    for c in repaired
                ],
            },
        )

    for e in evidence:
        e["task_id"] = task["id"]

    await emit(
        sid,
        "agent_log",
        agent="executor",
        message=f"Gathered {len(evidence)} source(s) for task {task['id']}",
        detail={
            "task_id": task["id"],
            "source_count": len(evidence),
            "evidence": evidence,
        },
    )
    # `sources` is what retrieval actually delivered, which is a different question from
    # what the executor made of it. Reported so a run that gathered nothing can say which
    # of the two failed instead of guessing — see `_no_research_reason`.
    return {
        "evidence": evidence,
        "cost": cost,
        "in": i_tot,
        "out": o_tot,
        "sources": len([t for t in seen_text.values() if (t or "").strip()]),
    }


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
                "model": cfg.model_for("executor"),
            },
        )

    guard = _BudgetGuard(state.get("cost_usd", 0.0), cfg.max_cost_per_session_usd)
    semaphore = asyncio.Semaphore(max(1, cfg.max_parallel_tasks))

    async def bounded(task: dict) -> dict:
        async with semaphore:
            if guard.exceeded():
                logger.warning("executor_not_dispatched", session_id=sid, task_id=task["id"])
                return {"evidence": [], "cost": 0.0, "in": 0, "out": 0, "sources": 0}
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
    # Highest reading of the run, not this round's: a later round that searched worse must
    # not erase the evidence that retrieval did work earlier.
    sources_seen = max(state.get("sources_seen", 0), sum(r.get("sources", 0) for r in results))
    return {
        "evidence": merged,
        "research_round": round_no,
        "sources_seen": sources_seen,
        **_acc(state, cost, i_tot, o_tot),
    }


async def _criticize_one(
    state: AgentState, task: dict
) -> tuple[str, CriticVerdict, float, int, int]:
    task_evidence = [
        e for e in state.get("evidence", []) if str(e.get("task_id")) == _task_key(task)
    ]

    # A configured floor (docs/07 §2, Phase 3; 0 = no floor, today's behaviour) fails
    # closed without spending a model call — evidence that is already too thin to meet
    # the floor cannot become sufficient by asking a model to grade it.
    min_sources = get_run_config().min_sources_per_task
    if min_sources > 0 and len(task_evidence) < min_sources:
        verdict = CriticVerdict(
            passed=False,
            confidence=1.0,
            reasons=[f"only {len(task_evidence)} source(s) gathered, {min_sources} required"],
            feedback_for_executor=f"Gather at least {min_sources} sources before resubmitting.",
        )
        return _task_key(task), verdict, 0.0, 0, 0

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
        detail={"task_ids": [t["id"] for t in pending], "model": cfg.model_for("critic")},
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


# ── Citation-fidelity verification (docs/12 M5) ──────────────────────────────────
#
# The eval judge rules on a claim against the snippets of its cited sources — and the
# baseline run measured the synthesizer shipping claims its own snippets do not back
# (postgres-vs-mysql at 0.5256). The drift enters through the executor's key_fact, which
# the synthesizer follows past the verbatim snippet. So before a draft reaches the human
# gate, every cited claim gets the SAME ruling here: supported → untouched; not supported
# → its markers are stripped and the claim is flagged, because a citation the evidence
# does not back is worse than an admitted gap.

# Must END with a sentence terminator: the eval judge splits sentences on [.!?] +
# whitespace, and a note without one gets merged into the FOLLOWING sentence — measured
# as a supported claim ruled NO because it carried the previous claim's note (run #3).
_VERIFIED_NOTE = " *(citation could not be verified)*."
# The claim split MUST mirror the eval judge's `claims.split_sentences`/`claim_lines`
# exactly (lookahead on the next sentence's opener + abbreviation rejoin): this pass is
# measured by that judge, so it must rule on the same claims, not fragments of them.
#
# It now does so by *importing the same objects* rather than restating the patterns —
# four regexes were duplicated here and in `evals.metrics`, with a comment asserting they
# matched and nothing checking it. `tests/test_claim_extraction_parity.py` pins both the
# identity of these primitives and the sentence-for-sentence agreement of the two scans.
_VSPLIT_RE = claims.SENTENCE_SPLIT_RE
_VABBREV_TAIL_RE = claims.ABBREV_TAIL_RE
_VLIST_MARKER_RE = claims.LIST_MARKER_RE
# Limitations is where the synthesizer writes what the evidence does NOT cover; its
# sentences are hedging, not factual claims — the eval judge excludes them (metrics v3),
# so this pass must too.
_VLIMITATIONS_HEADING_RE = claims.LIMITATIONS_HEADING_RE
# A cited sentence opening with a deictic ("This is detailed in Article 55 [4].") is
# judged by the eval harness as a STANDALONE claim — and an anaphor with its referent
# in the previous sentence reads as unsupported. Measured as 4 of 11 NO rulings in the
# second Ollama eval. The claim split still mirrors the judge (separate sentences), and
# the verify pass strips such markers deterministically.
_VDEICTIC_RE = re.compile(r"^(?:This|These|Those|That|It|Such)\b", re.I)
# A bold label prefix ("**Cost**: ...") starts 3 of 8 NO rulings in run #3: the judge
# rules on the sentence as a whole, and no snippet contains the label — the sentence as
# written always exceeds its evidence. Stripped like deictics; prompt rule 6 forbids it.
_VLABEL_RE = re.compile(r"^\*\*[^*]+\*\*\s*:")
# Mechanical fidelity pre-check: every number-like token in a claim must appear verbatim
# in one of the cited snippets. A local 7B verifier rubber-stamps plausible prose (the
# second Ollama eval scored 0.8142 with the verifier approving 7 claims the judge later
# rejected); literal number/percentage/year matching is deterministic and catches the
# drift class the judge actually ruled NO on — invented figures and wrong magnitudes.
_VNUM_RE = re.compile(r"\d+(?:\.\d+)?%?|\b\d{4}\b")


def _claim_numbers(claim: str) -> list[str]:
    """Number-like tokens in a claim, citation markers excluded."""
    return _VNUM_RE.findall(re.sub(r"\[\d+(?:\s*,\s*\d+)*\]", "", claim))


def _numbers_grounded(claim: str, snippets: str) -> bool:
    # Word-bounded containment: "5" must not be grounded by "50%", or every short
    # number would false-positive and the check would pass nothing.
    return all(
        re.search(rf"(?<![0-9.]){re.escape(n)}(?![0-9.])", snippets) for n in _claim_numbers(claim)
    )


#: This pass's own sources-section boundary, and the one place it deliberately differs
#: from `claims.SOURCES_HEADING_RE` (`#{1,6}`): a **bare** `Sources` line with no Markdown
#: heading marker also ends the body here. Kept local rather than pushed into `claims`
#: because widening the shared pattern would change what the eval judge counts as a claim,
#: which is a metrics-definition change and needs a `METRICS_VERSION` bump to be honest.
#: `tests/test_claim_extraction_parity.py` pins the divergence so it stays deliberate.
#:
#: The two branches are not interchangeable, and collapsing them to one optional `#`
#: (`#{0,6}`) is what issue #48 was: with the marker optional the pattern also matched
#: ordinary prose that merely *starts* with the word — "Sources of error were considered
#: [1]." — so the scan broke there and every remaining claim went unchecked. Unchecked
#: means its citation markers are never stripped, so the report renders *more* verified
#: than it is, which is the one failure class this project refuses outright. The heading
#: branch therefore stays open-ended (so `## Sources and References` still ends the body,
#: exactly as it does for the judge), while the bare-label branch must consume the whole
#: line — a label is all a label line contains.
_VSOURCES_RE = re.compile(
    r"(?i)(?:"
    r"#{1,6}\s*(?:sources|references|citations|bibliography)\b"
    r"|"
    r"(?:sources|references|citations|bibliography)\s*:?\s*$"
    r")"
)


def _cited_claims(draft: str) -> list[str]:
    """Cited factual sentences in the draft body, sources section excluded.

    Sentence splitting, list-marker stripping, the length floor and the citation pattern
    all come from `research_engine.claims` — the same definitions the eval judge uses, so
    this pass rules on the same claims it is measured against rather than on fragments.

    Two scanning differences from `claims.claim_lines` remain, both deliberate:

    1. A **bare** `Sources` line ends the body here (`_VSOURCES_RE`), where the judge
       requires a `#` heading. Only a line that is *nothing but* the label counts; prose
       opening with the word is a claim like any other (issue #48).
    2. The judge also skips the engine-rendered *Conflicting evidence* block. This pass
       does not need to: the block is appended by `synthesizer_node` *after* the fidelity
       check has already run, so it is never present in the draft this function sees.
    """
    out: list[str] = []
    skipping = False
    for raw in (draft or "").splitlines():
        line = raw.strip()
        # Tested BEFORE the heading guard below. That guard `continue`s on anything
        # starting with '#', which left this break unreachable for the `## Sources`
        # heading the synthesizer actually emits — so the source list was judged as
        # claims, and each line failed `_numbers_grounded` on the digits in its own URL
        # (arXiv ids, years). Every report shipped with the unverified note appended to
        # every line of its own bibliography.
        if _VSOURCES_RE.match(line):
            break
        if not line or line.startswith("#"):
            if line:
                skipping = bool(_VLIMITATIONS_HEADING_RE.match(line))
            continue
        if skipping:
            continue
        content = _VLIST_MARKER_RE.sub("", line)
        for sentence in claims.split_sentences(content):
            s = sentence.strip()
            if not claims.is_claim_sentence(s):
                continue
            if claims.CITE_RE.search(s):
                out.append(s)
    return out


async def _verifier_verdicts(
    claim_evidence: list[tuple[str, str]],
) -> tuple[list[bool], float, int, int]:
    """Ask the critic model whether each claim is supported by its evidence.
    Returns (verdicts, cost, tokens_in, tokens_out).

    Real-mode path; fake mode answers YES for every claim (fakes.py). Mirrors the eval
    judge's prompt and line format (evals/harness.judge_citation_support) on purpose:
    the pass is measured by that judge, so the in-graph check must rule like it.
    """
    llm = get_llm("critic")
    BATCH = 4
    verdicts: list[bool] = []
    cost = i_tot = o_tot = 0
    for start in range(0, len(claim_evidence), BATCH):
        batch = claim_evidence[start : start + BATCH]
        blocks = [
            f"Claim {i}: {claim}\nEvidence {i}:\n{snippets}"
            for i, (claim, snippets) in enumerate(batch, start=1)
        ]
        resp = await llm.ainvoke(
            [
                SystemMessage(content=prompts.CITATION_VERIFY_PROMPT),
                HumanMessage(content="\n\n".join(blocks)),
            ]
        )
        cost += estimate_cost(resp, "critic")
        di, do = token_counts(resp)
        i_tot += di
        o_tot += do
        text = text_of(resp)
        ruled = {
            int(m.group(1)): m.group(2).upper() == "YES"
            for m in re.finditer(r"Claim\s+(\d+)\s*:\s*(YES|NO)", text, re.IGNORECASE)
        }
        for i in range(1, len(batch) + 1):
            # A claim the verifier failed to rule on keeps its citations: stripping is
            # only for claims explicitly judged unsupported.
            verdicts.append(ruled.get(i, True))
    return verdicts, cost, i_tot, o_tot


async def _verify_citation_fidelity(
    sid: str, draft: str, sources: list[dict]
) -> tuple[str, float, int, int]:
    """Check every cited claim against its own sources' snippets; strip markers the
    evidence does not back. Returns (draft, cost, tokens_in, tokens_out)."""
    claims = _cited_claims(draft)
    if not claims or not sources:
        return draft, 0.0, 0, 0

    by_index = {s.get("index"): s for s in sources if isinstance(s, dict)}
    claim_evidence: list[tuple[str, str]] = []
    mechanically_unsupported: set[str] = set()
    for claim in claims:
        if _VDEICTIC_RE.match(claim) or _VLABEL_RE.match(claim):
            # The judge rules on this sentence ALONE (anaphor without referent / label
            # no snippet contains), where it reads unsupported. Strip deterministically;
            # synthesizer rules 5–6 forbid both constructions upstream, so this is
            # residual defence.
            mechanically_unsupported.add(claim)
            continue
        nums: list[int] = []
        for m in re.finditer(r"\[(\d+(?:\s*,\s*\d+)*)\]", claim):
            nums.extend(int(p) for p in m.group(1).split(","))
        if any(by_index.get(n) is None for n in nums):
            # A marker pointing at no source cites nothing — judged against empty
            # evidence it can only fail (measured: resolution_rate 0.6667, run #5).
            mechanically_unsupported.add(claim)
            continue
        snippets = "\n".join(
            f"- {t}"
            for n in nums
            for s in [by_index.get(n)]
            if s
            for t in (s.get("snippets") or ([s["snippet"]] if s.get("snippet") else []))
        )
        # Deterministic pre-check before any model rules: a number the cited snippets do
        # not contain verbatim can never be "supported", whatever a small local verifier
        # says (it rubber-stamped invented figures in the second Ollama eval).
        if not _numbers_grounded(claim, snippets):
            mechanically_unsupported.add(claim)
        claim_evidence.append((claim, snippets))

    todo = [(c, s) for c, s in claim_evidence if c not in mechanically_unsupported]
    try:
        verdicts, cost, i_tot, o_tot = await _verifier_verdicts(todo)
    except Exception as e:  # noqa: BLE001
        # A verifier failure keeps every citation in place — the ⚠ chip and the eval
        # judge still rule on them — EXCEPT the mechanically unsupported ones, which no
        # model opinion can rescue.
        logger.warning("citation_verify_unavailable", session_id=sid, error=str(e)[:200])
        verdicts, cost, i_tot, o_tot = [], 0.0, 0, 0

    ok_by_claim: dict[str, bool] = {}
    if verdicts:  # empty on verifier failure — nothing was ruled, nothing is stripped
        for (claim, _), ok in zip(todo, verdicts, strict=True):
            ok_by_claim[claim] = ok

    result = draft
    stripped = 0
    for claim in claims:
        if ok_by_claim.get(claim, claim not in mechanically_unsupported):
            continue
        stripped += 1
        # The note carries its own terminator (see _VERIFIED_NOTE), so drop the claim's.
        cleaned = re.sub(r"\s*\[\d+(?:\s*,\s*\d+)*\]", "", claim).strip().rstrip(".!?")
        result = result.replace(claim, cleaned + _VERIFIED_NOTE, 1)

    if stripped:
        await emit(
            sid,
            "agent_log",
            agent="synthesizer",
            message=f"Citation check: {stripped} claim(s) not supported by their snippets — markers removed",
            detail={"stripped": stripped, "checked": len(claims)},
        )
    return result, cost, i_tot, o_tot


async def contradiction_detector_node(state: AgentState) -> dict:
    """Surface conflicting claims across evidence (docs/12 M11). Never resolves them.

    One bounded call over the capped snippet set — cost scales with the run, not with
    the square of the source count. Runs on the critic's model routing: this is a
    temperature-0 adjudication-style judgment, the same class of task the critic does,
    and adding a sixth routed role would ripple through every host's model config for
    one call per run.

    Fail-closed: an unavailable or unparseable detector surfaces NOTHING (and says so
    in the agent log) — a fabricated conflict is the worst possible error here.
    """
    sid = state["session_id"]
    by_source = contradictions.group_snippets_by_source(state.get("evidence", []))
    if len(by_source) < 2:
        return {"contradictions": []}

    await emit(
        sid,
        "agent_log",
        agent="contradiction_detector",
        message="Checking evidence for conflicting claims…",
    )
    messages = [
        SystemMessage(content=prompts.CONTRADICTION_DETECTOR_PROMPT),
        HumanMessage(
            content=f"Research query: {state['original_query']}\n\n"
            f"{contradictions.build_detector_input(by_source)}"
        ),
    ]
    parsed, cost, i, o = await _structured("critic", messages, ContradictionReport)
    if parsed is None:
        reason = _last_api_error.get() or "unparseable response"
        await emit(
            sid,
            "agent_log",
            agent="contradiction_detector",
            message=f"Contradiction check unavailable ({reason}); none surfaced",
        )
        return {"contradictions": [], **_acc(state, cost, i, o)}

    normalized = contradictions.normalize_pairs(parsed.pairs, set(by_source))
    found = contradictions.validate_pairs(normalized, by_source)
    await emit(
        sid,
        "agent_log",
        agent="contradiction_detector",
        message=(
            f"Found {len(found)} conflicting claim pair(s)"
            if found
            else "No conflicting claims found"
        ),
    )
    return {"contradictions": found, **_acc(state, cost, i, o)}


def _number_sources(evidence: list[dict]) -> tuple[list[dict], dict[str, int]]:
    """Numbered source list + url→index map, in first-appearance order.

    Shared by the synthesizer (citation numbering) and the conflict-block renderer
    (docs/12 M11), so the [n] markers in the block always match the report's source
    list — one numbering implementation, no drift.
    """
    sources: list[dict] = []
    seen: dict[str, int] = {}
    for e in evidence:
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
    return sources, seen


async def synthesizer_node(state: AgentState) -> dict:
    sid = state["session_id"]
    await emit(
        sid,
        "agent_log",
        agent="synthesizer",
        message="Compiling the report…",
        detail={"model": get_run_config().model_for("synthesizer")},
    )

    # Build a numbered source list from unique evidence URLs; the draft cites [n].
    #
    # Every distinct snippet from a source is kept, not just the first (docs/12 M5, D3).
    # One page commonly backs several different facts and the executor extracts a separate
    # verbatim quote for each; retaining only one meant a citation chip could display text
    # unrelated to the claim it was attached to — the same source is cited for roughly
    # eight different claims per report.
    sources, seen = _number_sources(state.get("evidence", []))

    numbered_evidence = [
        {
            "n": seen.get(e.get("source_url", ""), 0),
            "snippet": e.get("snippet", ""),
            "url": e.get("source_url", ""),
        }
        for e in state.get("evidence", [])
    ]

    evidence_lines: list[str] = []
    for ev in numbered_evidence:
        # Snippet only — no key_fact. The executor's key_fact is a paraphrase, and a
        # small synthesizer model that sees both writes from the paraphrase: the claim
        # drifts past the verbatim text, and both this graph's fidelity check and the
        # eval judge rule on the snippet alone (measured as the residual NO class in
        # the second Ollama eval). What can be cited is exactly what is shown.
        evidence_lines.append(f'[{ev["n"]}] Snippet: "{ev["snippet"]}"')
        evidence_lines.append(f"    Source: {ev['url']}")
        evidence_lines.append("")  # blank separator
    evidence_text = "Evidence for citation:\n" + "\n".join(evidence_lines)

    messages = [
        SystemMessage(content=prompts.SYNTHESIZER_PROMPT_V2),
        HumanMessage(
            content=prompts.synthesizer_human(
                state["original_query"],
                evidence_text,
                state.get("human_feedback"),
                # The reviewer's edited outline, not the planner's proposal — the gate
                # writes its decision back over this key (`plan_gate_node`). Empty when
                # the gate was skipped, which is the ungated report structure.
                state.get("proposed_outline"),
            )
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
        resp = repair_resp  # the repair pass's response is the last one actually served
        await emit(
            sid,
            "agent_log",
            agent="synthesizer",
            message=f"Citation repair: fixed {uncited} uncited claims",
        )

    # Citation-fidelity check (docs/12 M5): every remaining cited claim is judged against
    # the snippets of its own cited sources, exactly as the eval judge rules. Runs after
    # the repair pass so a repair-introduced drift is caught too. Unsupported claims lose
    # their markers and carry a visible note rather than shipping a hollow citation.
    draft, vcost, vi, vo = await _verify_citation_fidelity(sid, draft, sources)
    cost += vcost
    i += vi
    o += vo

    # Conflicting-evidence block (docs/12 M11): rendered deterministically from the
    # detector's validated pairs and inserted before the reference list. Appended AFTER
    # the repair and fidelity passes so those claim checkers never judge the block's
    # meta-prose — and because the LLM never authors it, it can neither omit nor
    # "resolve" a conflict. Absent contradictions, the draft is untouched.
    if state.get("contradictions"):
        block = contradictions.render_block(state["contradictions"], seen)
        draft = contradictions.insert_block(draft, block)
        await emit(
            sid,
            "agent_log",
            agent="synthesizer",
            message=f"Surfaced {len(state['contradictions'])} conflicting claim pair(s) in the report",
        )

    await emit(
        sid,
        "agent_log",
        agent="synthesizer",
        message=f"Draft compiled ({len(draft.split())} words, {len(sources)} sources)",
        detail={
            "word_count": len(draft.split()),
            "sources_count": len(sources),
            "preview": draft[:1200] + ("..." if len(draft) > 1200 else ""),
            # The model id the provider actually reported serving, when it discloses one
            # (llm_factory.served_model_id) — distinct from `model` above, which is the
            # configured route. `None` in fake mode (no `response_metadata` at all); on
            # a real call it ordinarily matches the configured model and would only
            # diverge from it once a role is routed through a router alias (AGENTS.md,
            # "auto/* are not pinned models") — no such alias exists in this codebase
            # yet, so this field is presently descriptive rather than load-bearing.
            "served_model": served_model_id(resp),
        },
    )
    return {
        "draft_report": draft,
        "sources": sources,
        "human_feedback": None,
        **_acc(state, cost, i, o),
    }


def plan_gate_node(state: AgentState) -> dict:
    """Pause after the planner for the user to edit subtopics and the outline before
    any search spends money (docs/07 §2, Phase 4). Mirrors `hitl_gate_node` exactly:
    `interrupt()` persists the checkpoint and suspends; a resume carries the decision.

    Resumed with `{"tasks": [...], "outline": [...]}` — both optional; an absent key
    means "unedited, use what the planner proposed". `include: false` on a task drops
    it from what the executor runs, which is the whole point of a *review* gate rather
    than a rubber stamp: the reviewer's edits change the run, not just what is shown.
    """
    decision = interrupt(
        {
            "type": "PLAN_READY",
            "tasks": state.get("tasks", []),
            "proposed_outline": state.get("proposed_outline", []),
        }
    )
    tasks = decision.get("tasks") if decision.get("tasks") is not None else state.get("tasks", [])
    outline = (
        decision.get("outline")
        if decision.get("outline") is not None
        else state.get("proposed_outline", [])
    )
    tasks = [t for t in tasks if t.get("include", True)]
    return {"tasks": tasks, "proposed_outline": outline, "plan_approved": True}


def route_after_plan_gate(state: AgentState) -> str:
    # An approved plan with every subtopic excluded researches nothing, and a run that
    # researched nothing must not reach the synthesizer: with no evidence in hand it
    # writes the report out of the model's own memory and the repair pass then decorates
    # it with markers that resolve to nothing. `submit_plan_review` rejects this at the
    # API first; this is the guard for a resume that reaches the graph another way — a
    # checkpoint written before that check existed, or a caller that bypassed the route.
    if not state.get("tasks"):
        return "failer"
    return "executor"


def hitl_gate_node(state: AgentState) -> dict:
    """Pause for human review. interrupt() persists the checkpoint and suspends."""
    decision = interrupt(
        {
            "type": "HITL_READY",
            "word_count": len((state.get("draft_report") or "").split()),
            "source_count": len(state.get("sources", [])),
            # M11: how many unresolved conflicts the reviewer is approving alongside the
            # draft. The report surfaces them; the gate makes the count impossible to miss.
            "contradiction_count": len(state.get("contradictions") or []),
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
    # Recomputed here because a router cannot write state: whichever guard sent us here
    # still reads the same way from the same state. A generic "budget or loop limit
    # exceeded" made the user open the source to find which limit tripped and by how much.
    return {
        "error": state.get("error")
        or _over_budget(state)
        or _no_research_reason(state)
        or "retry limit reached: every task exhausted its critic rounds"
    }


# ── Conditional routing ────────────────────────────────────────────────────────────


def _over_budget(state: AgentState) -> str | None:
    """The breach reason if a guard has tripped, else None. **0 disables a guard.**

    Every limit is opt-in (docs/04 §6). The token ceiling was hardcoded at 1_000_000 and
    reachable from no config, so on a provider whose pricing the catalog does not carry —
    `estimate_cost()` returns 0.0 for openrouter/custom, which makes the dollar cap inert
    — it was the only guard that could fire, and it killed a real run at 1,003,721 tokens.

    Returning the reason rather than a bare bool is the point: "budget or loop limit
    exceeded" made a user read the source to learn which of three numbers was crossed.
    """
    cfg = get_run_config()

    cost, cost_cap = state.get("cost_usd", 0.0), cfg.max_cost_per_session_usd
    if cost_cap and cost >= cost_cap:
        return f"cost ceiling reached: ${cost:.4f} of ${cost_cap:.2f}"

    tokens, token_cap = state.get("tokens_input", 0), cfg.max_input_tokens
    if token_cap and tokens >= token_cap:
        return f"input-token ceiling reached: {tokens:,} of {token_cap:,}"

    time_cap = cfg.max_wallclock_seconds
    elapsed = time.time() - state.get("started_at", time.time())
    if time_cap and elapsed >= time_cap:
        return f"time limit reached: {elapsed:.0f}s of {time_cap}s"

    return None


def _no_research_reason(state: AgentState) -> str | None:
    """Why this run cannot honestly produce a report, if it cannot.

    Three failures, deliberately worded apart because the remedy differs: a plan with
    nothing selected never searched; a plan that searched and found nothing did; and a
    plan that fetched sources but turned none of them into a citable quotation did neither.
    Collapsing them would send a user to check their search providers when what actually
    happened is that they unchecked every subtopic — or, as in run `96a16137`, when the
    providers had answered every query and it was the executor model that returned nothing.
    A false diagnosis is the P0 class here, not a cosmetic one.

    This is the *reason* half of the guards in `route_after_plan_gate`,
    `route_after_planner` and `route_after_critic`; the routers decide, and a router
    cannot write state, so the text is recomputed here from the same state they read.
    """
    if not state.get("tasks"):
        return (
            "no research tasks were selected — every subtopic was excluded at the design "
            "gate, so nothing was searched. Start a new run and keep at least one subtopic."
        )
    if not state.get("evidence"):
        seen = state.get("sources_seen", 0)
        if seen:
            return (
                f"no evidence was gathered — search worked and {seen} source(s) were "
                "fetched, but the executor model returned no usable quotation from any of "
                "them, so there is nothing a report could be built from. This is a model "
                "failure, not a retrieval one: try a different executor model in "
                "Settings → Models, then retry."
            )
        return (
            "no evidence was gathered — every research task finished without returning "
            "anything citable, and no source was successfully fetched, so there is nothing "
            "a report could be built from. Check that a search provider is reachable, "
            "then retry."
        )
    return None


def route_after_planner(state: AgentState) -> str:
    if state.get("error"):
        return "failer"
    # A planner that produced no tasks has nothing to gate and nothing to execute. Failing
    # here rather than at the gate keeps the two "nothing to research" paths — a planner
    # that proposed nothing, and a reviewer who excluded everything — reporting the same
    # way, instead of the skip-gate path sliding through to an evidence-free report.
    if not state.get("tasks"):
        return "failer"
    # Opt-out, not opt-in (docs/07 §2, Phase 4) — the extra pause is the default.
    if get_run_config().skip_plan_gate:
        return "executor"
    return "plan_gate"


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
    # Every task is done and none of them yielded anything citable. Stopping here is the
    # difference between "we could not answer this" and a fluent report sourced from the
    # synthesizer's training data — the latter is what the citation-repair pass turns into
    # an artifact that *looks* verified while resolving to nothing.
    if not state.get("evidence"):
        return "failer"
    return "contradiction_detector"


def route_after_gate(state: AgentState) -> str:
    if state.get("approved"):
        return "finalizer"
    return "synthesizer"  # rework with human_feedback


# ── Build ──────────────────────────────────────────────────────────────────────────


def build_graph(checkpointer):
    g = StateGraph(AgentState)
    g.add_node("planner", planner_node)
    g.add_node("plan_gate", plan_gate_node)
    g.add_node("executor", executor_node)
    g.add_node("critic", critic_node)
    g.add_node("contradiction_detector", contradiction_detector_node)
    g.add_node("synthesizer", synthesizer_node)
    g.add_node("hitl_gate", hitl_gate_node)
    g.add_node("finalizer", finalizer_node)
    g.add_node("failer", failer_node)

    g.add_edge(START, "planner")
    g.add_conditional_edges(
        "planner",
        route_after_planner,
        {"executor": "executor", "plan_gate": "plan_gate", "failer": "failer"},
    )
    g.add_conditional_edges(
        "plan_gate", route_after_plan_gate, {"executor": "executor", "failer": "failer"}
    )
    g.add_edge("executor", "critic")
    g.add_conditional_edges(
        "critic",
        route_after_critic,
        {
            "executor": "executor",
            "contradiction_detector": "contradiction_detector",
            "failer": "failer",
        },
    )
    g.add_edge("contradiction_detector", "synthesizer")
    g.add_edge("synthesizer", "hitl_gate")
    g.add_conditional_edges(
        "hitl_gate", route_after_gate, {"finalizer": "finalizer", "synthesizer": "synthesizer"}
    )
    g.add_edge("finalizer", END)
    g.add_edge("failer", END)
    return g.compile(checkpointer=checkpointer)
