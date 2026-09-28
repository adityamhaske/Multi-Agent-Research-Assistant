"""
Eval harness (docs/08 §5). Runs the fixed query set through the compiled graph up to
the review gate and records per-report quality metrics to a dated JSON file, so report
quality is diffable over time.

Per-commit CI uses fake models; evals measure real-model quality. Run:

    make eval                       # fake mode (deterministic, no keys) — smoke/baseline
    LLM_MODE=real make eval EVAL_ARGS="--judge anthropic:claude-sonnet-4-6"

The committed baseline in results/ is a fake-mode run: it exercises the metric plumbing
and pins structural numbers. Real-model runs additionally compute an LLM-judged citation
support rate and are what the release criteria gate on — judged by the model `--judge`
names, which must be independent of every route under evaluation (RG-5).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver

from evals import metrics
from research_engine.graph import build_graph
from research_engine.local import load_env_file, run_config_from_env
from research_engine.runconfig import (
    get_run_config,
    reset_run_config,
    set_process_default,
    set_run_config,
)
from research_engine.runner import initial_state

# The harness is a host, so it installs the engine's config (docs/13 §2) — built straight
# from the environment rather than through `app.config`. That is why an eval run now needs
# no DATABASE_URL and no JWT_SECRET_KEY: the `os.environ.setdefault` block that used to sit
# here was the clearest evidence the engine was wrongly coupled to the server, and deleting
# it is M6's acceptance test (docs/12).
# Mode is read from the *real* environment before `.env` is loaded, and `.env` supplies
# keys only. This ordering is deliberate: a developer `.env` commonly carries
# `LLM_MODE=real` for the app, and letting that reach the harness would silently turn
# `make eval` — documented and relied on as the free, deterministic default — into a run
# that spends money on every invocation. Spending is opt-in, per invocation:
#
#     make eval                    # always fake, whatever .env says
#     LLM_MODE=real make eval      # explicit, and picks up keys from .env
LLM_MODE = os.environ.get("LLM_MODE", "fake")
load_env_file()
RUN_CONFIG = run_config_from_env(fake=LLM_MODE != "real")
set_process_default(RUN_CONFIG)

EVALS_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVALS_DIR / "results"

# Release criteria (docs/08 §5).
MIN_CITATION_SUPPORT = 0.95
MIN_COMPLETION_RATE = 0.90

_ROLES = ("planner", "executor", "critic", "synthesizer", "chat")


# ── The judge (RG-5) ──────────────────────────────────────────────────────────────
#
# The citation judge used to be `get_llm("critic")` — the pipeline's own critic model grading
# the pipeline's own citations. That is a self-judged number, and RG-5 requires "a disclosed
# independent judge that actually answered" (internal/rfcs/V3.0-agentspec-scope.md §20). So
# the judge is named per invocation, checked against the routes under evaluation before a
# single query runs, and recorded beside them — never inferred, never defaulted.


class JudgeConfigError(ValueError):
    """A judge that cannot serve as the independent one, or no judge at all."""


#: The route `judge_citation_support` builds its judge from, set by `configure_judge`. None
#: until then — and judging then refuses rather than falling back to the pipeline's critic,
#: which is the self-judged measurement this exists to end.
JUDGE_ROUTE: str | None = None


def _is_router_alias(model: str) -> bool:
    """`auto`, `auto/*` and `*/auto` resolve per call (AGENTS.md: not pinned models)."""
    model = model.lower()
    return model == "auto" or model.startswith("auto/") or model.endswith("/auto")


def _model_identity(model: str) -> str:
    """The model a route names, with the provider's spelling removed.

    Catches one model reached two ways — `openrouter:google/gemini-2.5-flash` and
    `google:gemini-2.5-flash`, `ollama:qwen2.5` and `ollama:qwen2.5:latest` — which a plain
    string comparison of routes would call independent. It does not decide whether two
    *different* models are too closely related; the result names both, so a reader can.
    """
    name = model.lower().rsplit("/", 1)[-1]
    return name.removesuffix(":latest")


def validate_judge(route: str, pipeline: dict[str, str]) -> str:
    """`route` if it can judge `pipeline` independently; otherwise say exactly why not."""
    provider, _, model = route.partition(":")
    if not provider or not model:
        raise JudgeConfigError(
            f"a judge must be 'provider:model' (got {route!r}), e.g. anthropic:claude-sonnet-4-6"
        )
    if _is_router_alias(model):
        raise JudgeConfigError(
            f"{route} is a router alias, not a pinned model: it can resolve to a different "
            "model on every call, including one the pipeline uses, so it cannot be disclosed "
            "as the judge"
        )
    for role, used in sorted(pipeline.items()):
        used_model = used.partition(":")[2]
        if _is_router_alias(used_model):
            raise JudgeConfigError(
                f"the pipeline's {role} routes to the alias {used}; what it resolves to is "
                "unknown, so no judge can be shown to be independent of it. Pin the model."
            )
        if used == route or _model_identity(used_model) == _model_identity(model):
            raise JudgeConfigError(
                f"{route} is the model the pipeline's {role} runs on ({used}); the system "
                "under evaluation cannot also be its judge"
            )
    return route


def configure_judge(route: str) -> str:
    """Install the judge for this process, checked against every route the harness runs."""
    global JUDGE_ROUTE
    JUDGE_ROUTE = validate_judge(route, {role: RUN_CONFIG.models[role] for role in _ROLES})
    return JUDGE_ROUTE


def _judge_llm():
    """Build the configured judge through the engine's factory — every provider the product
    supports, no second client. `critic` is borrowed only for its zero-temperature settings;
    the route is the judge's, installed for the build and removed straight after, as
    `benchmark.py::_build_judge` does."""
    if JUDGE_ROUTE is None:
        raise JudgeConfigError(
            "no independent judge is configured (--judge provider:model). Judging never falls "
            "back to the pipeline's own critic: a self-judged rate is not evidence for RG-5."
        )
    from research_engine import llm_factory

    base = get_run_config()
    token = set_run_config(replace(base, models={**base.models, "critic": JUDGE_ROUTE}))
    try:
        llm = llm_factory.get_llm("critic")
    finally:
        reset_run_config(token)
    # A gateway reports in response headers which connection and model served a call, and the
    # OpenAI-compatible client drops them unless asked (`gateway_routing` reads them). Set on
    # this judge's own instance only — the pipeline's clients are untouched — and only where
    # the client declares the option; a native SDK client or a test double is left as built.
    if "include_response_headers" in getattr(type(llm), "model_fields", {}):
        llm.include_response_headers = True
    return llm


#: The headers OmniRoute documents for "what actually served this call". Read by name, and
#: nothing else from a response's headers is kept — so a credential, token or cookie a
#: gateway happened to send back can never reach a result file.
_ROUTING_HEADERS = {
    "provider": "x-omniroute-provider",
    "model": "x-omniroute-model",
    "decision": "x-omniroute-decision",
}


def gateway_routing(response) -> dict[str, str | None]:
    """The connection, model and routing decision a gateway reports for one judge call.

    Observational only: a header the response did not carry is None, never filled in from
    the configured route. A direct provider client sends none of them, so every field is
    None there — which says "no gateway reported this", not "served by the route".
    """
    meta = getattr(response, "response_metadata", None) or {}
    headers = {str(k).lower(): v for k, v in (meta.get("headers") or {}).items()}
    return {
        field: (str(headers[name]) if headers.get(name) else None)
        for field, name in _ROUTING_HEADERS.items()
    }


def _decision_strategy(decision: str) -> str | None:
    """`single`, a combo strategy, … — the `strategy=` field of OmniRoute's documented
    `strategy=<name>; provider=<alias>; latency_ms=<n>` decision header, or None."""
    for part in decision.split(";"):
        key, _, value = part.strip().partition("=")
        if key == "strategy" and value:
            return value
    return None


def judge_tally(rows: list[dict]) -> dict:
    """What the judge actually did across a run's reports: how many claims it ruled on, how
    many it never reached, and which model the provider says answered.

    `served_models` is read from each response (`llm_factory.served_model_id`), not copied
    from the route, so a judge that silently answered as something else shows it. Empty when
    the provider discloses nothing — never filled in from the route.
    """
    verdicts = [c for r in rows for c in r.get("claim_verdicts") or []]
    judged = [c for c in verdicts if c.get("judged")]
    routed = [c.get("judge_routing") or {} for c in judged]
    return {
        "claims_judged": len(judged),
        "claims_unjudged": len(verdicts) - len(judged),
        "served_models": sorted({c["judged_by"] for c in judged if c.get("judged_by")}),
        # What the gateway said served each ruling. `strategy` single means the pinned
        # connection answered directly — no combo, no fallback to another provider.
        "routing": {
            "providers": sorted({r["provider"] for r in routed if r.get("provider")}),
            "models": sorted({r["model"] for r in routed if r.get("model")}),
            "strategies": sorted(
                {
                    s
                    for r in routed
                    if r.get("decision")
                    for s in [_decision_strategy(r["decision"])]
                    if s
                }
            ),
            "rulings_without_routing": sum(1 for r in routed if not r.get("provider")),
        },
    }


def judge_section(route: str, rows: list[dict], candidate_rows: list[dict] | None) -> dict:
    """The result file's account of its judge, beside — never inside — `models`.

    `models` is the system under evaluation; this is what graded it. Keeping them apart is
    what lets a reader check the claim "independent" without trusting the harness's word.
    """
    section = {
        "route": route,
        "independent_of": {role: RUN_CONFIG.models[role] for role in _ROLES},
        "baseline": judge_tally(rows),
    }
    if candidate_rows is not None:
        section["candidate"] = judge_tally(candidate_rows)
    tallies = [section["baseline"], *([section["candidate"]] if candidate_rows is not None else [])]
    section["answered"] = any(t["claims_judged"] for t in tallies)
    return section


def _routing_slug() -> str:
    """Filename-safe tag for the routing a run used: the planner role's provider.

    Routing is `provider:model` split on the **first** colon (AGENTS.md), so
    `ollama:qwen2.5:7b` yields `ollama`. Used to give each result file a run identity —
    see `_result_path`.
    """
    provider = RUN_CONFIG.models["planner"].split(":", 1)[0]
    cleaned = "".join(c if c.isalnum() else "-" for c in provider).strip("-").lower()
    return cleaned or "unknown"


def _result_path(run_date: str, *, custom_spec: bool = False) -> Path:
    """Where this run's result goes — never onto an existing file.

    A date is not a run identity. The old default was `eval-<date>.json`, so two runs on
    one day collided, and that is exactly how a real 10/10 ollama measurement was
    destroyed: `cbde168` overwrote `eval-2026-08-13.json` with a failed Gemini run and
    nothing warned. Results are write-once (AGENTS.md; CI job `eval-artifacts`), so carry
    the routing and take the next free run number rather than clobbering.

    A custom-spec run (RFC §14.2) takes a `-custom` stem as well. It holds a baseline *and* a
    candidate, so it is a different kind of evidence; sharing the numbering with plain runs
    would let the two be mistaken for each other, and a distinct stem means neither can ever
    resolve to the other's file.
    """
    routing = "fake" if RUN_CONFIG.llm_mode == "fake" else _routing_slug()
    stem = f"eval-{run_date}-{routing}" + ("-custom" if custom_spec else "")
    path = RESULTS_DIR / f"{stem}.json"
    n = 2
    while path.exists():
        path = RESULTS_DIR / f"{stem}-run{n}.json"
        n += 1
    return path


@contextmanager
def _pipeline_scope(prompt_overrides: dict[str, str] | None) -> Iterator[None]:
    """The config the pipeline runs under — baseline or candidate — for this block only.

    **Both runs derive from `RUN_CONFIG` here, by construction.** The baseline used to read
    the process default while a candidate would be built from `RUN_CONFIG`. Those are the
    same object in production, but only because of an unstated coupling at import; if they
    ever diverged, a "prompt comparison" would silently compare two routings. Building both
    from one reference makes "differs only in the prompts" true by construction.

    **Scoped, never process-wide.** `set_process_default` would outlive the query and still
    be live when the judge runs. A context-local config exists only inside the `with`, so the
    sequence is fixed: install, run the pipeline, reset, *then* judge (RFC §14.1: a user's
    prompt may change what the pipeline produces, never what the harness measures).
    Synchronous by design — entered with `with`, not `async with`, around an awaited call.
    """
    token = set_run_config(replace(RUN_CONFIG, prompt_overrides=prompt_overrides or {}))
    try:
        yield
    finally:
        reset_run_config(token)


class CandidateSpecError(ValueError):
    """A `--candidate` file that cannot be evaluated as written."""


def load_candidate(path: Path) -> dict[str, str]:
    """Read a candidate spec — `{role: prompt}` — and validate it as production would.

    **From an explicit file, never from a user's stored preferences** (RFC §14.1): the eval
    measures a spec someone hands it, and must not reach into a database for one.

    Validated through `usable_overrides`, the same all-or-nothing rule a run's snapshot goes
    through, rather than a second copy of it. An unusable spec is refused outright instead of
    being evaluated as the shipped prompts: in production that fallback is the honest
    outcome, but here it would publish the baseline's numbers under the candidate's name.
    """
    from app.services.run_config import OVERRIDES_APPLIED, usable_overrides

    try:
        raw = json.loads(Path(path).read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise CandidateSpecError(f"cannot read candidate spec {path}: {e}") from e
    overrides, status = usable_overrides(raw)
    if status != OVERRIDES_APPLIED:
        reason = (
            "it replaces no prompt, so it would measure the shipped prompts twice"
            if not raw
            else "it names an unknown role or carries a prompt that is not non-empty text"
        )
        raise CandidateSpecError(f"candidate spec {path} cannot be evaluated: {reason}")
    return overrides


def candidate_section(overrides: dict[str, str], rows: list[dict]) -> dict:
    """The candidate's half of a custom-spec result, judged against the same thresholds.

    Beside the baseline rather than instead of it (RFC §14.2), and never gating the run: a
    spec below `MIN_CITATION_SUPPORT` is reported, because the user chose it and the eval's
    job is to measure honestly, not to refuse. The digest identifies exactly which text was
    measured without anyone having to diff prompts by eye.
    """
    import hashlib

    agg = aggregate(rows)
    return {
        "prompt_overrides": dict(overrides),
        "prompt_sha256": {
            role: hashlib.sha256(text.encode("utf-8")).hexdigest()
            for role, text in sorted(overrides.items())
        },
        "aggregate": agg,
        "release_criteria": check_release_criteria(agg),
        "results": rows,
    }


async def run_one(query: dict, *, prompt_overrides: dict[str, str] | None = None) -> dict:
    """Run one query to the gate; return its report metrics + timing.

    `prompt_overrides` is a candidate spec (RFC §14.2), already validated by the caller. It
    reaches the pipeline and is gone before the judge runs — see `_pipeline_scope`.
    """
    graph = build_graph(MemorySaver())
    thread_id = f"eval-{query['id']}"
    config = {"configurable": {"thread_id": thread_id}}
    initial = initial_state(
        session_id=thread_id,
        user_id="eval",
        query=query["query"],
        depth=query.get("depth", "balanced"),
    )

    started = time.time()
    error = None
    try:
        # The candidate is live for the pipeline alone. Reading the state back composes no
        # prompt, so it runs after the reset; so does everything below, the judge included.
        with _pipeline_scope(prompt_overrides):
            await graph.ainvoke(initial, config)
        state = (await graph.aget_state(config)).values
    except Exception as e:  # noqa: BLE001
        return {
            "id": query["id"],
            "domain": query.get("domain"),
            "completed": False,
            "error": str(e)[:300],
            "latency_s": round(time.time() - started, 2),
        }

    latency = round(time.time() - started, 2)
    if state.get("error"):
        error = str(state["error"])[:300]

    report = state.get("draft_report") or ""
    sources = state.get("sources") or []
    completed = bool(report) and error is None

    result = {
        "id": query["id"],
        "domain": query.get("domain"),
        "completed": completed,
        "error": error,
        "latency_s": latency,
        "cost_usd": round(state.get("cost_usd", 0.0), 6),
        "tokens": state.get("tokens_input", 0) + state.get("tokens_output", 0),
        **metrics.report_metrics(report, sources),
    }

    if completed and RUN_CONFIG.llm_mode == "real":
        rate, claim_rows = await judge_citation_support(report, sources)
        result["citation_support_rate"] = rate
        # The per-claim ruling — not just the aggregate — is what makes a miss
        # publishable and debuggable (docs/12 M5: "including the misses"). It is also
        # the only way to diff the judge against the graph's own citation-fidelity pass.
        result["claim_verdicts"] = claim_rows
        result["report"] = report
    return result


async def judge_citation_support(
    report: str, sources: list[dict]
) -> tuple[float | None, list[dict]]:
    """Real-mode only: ask a model whether each cited claim is actually supported by the
    snippet it cites. Batches up to 4 claims per LLM call to reduce latency from
    per-claim rate-limit sleeps.

    Returns `(supported / *judged* claims, per-claim rows)`. The denominator counts only
    claims the judge actually ruled on: a provider error, a partial reply, or an
    unparseable answer leaves a claim unjudged, and unjudged is **excluded** rather than
    scored as unsupported. The rate is None when nothing could be judged — "we could not
    measure this" has to stay distinct from "it scored zero" (docs/16 §6), and it did not
    until M18. `benchmark.py::calc_support_rate` implements the same rule; these are two
    homes for one contract, so change both (AGENTS.md).
    """
    import re as _re

    from langchain_core.messages import HumanMessage, SystemMessage

    from research_engine.llm_factory import served_model_id

    by_index = {s.get("index"): s for s in sources if isinstance(s, dict)}
    claims = [c for c in metrics.claim_lines(report) if metrics.CITE_RE.search(c)]
    if not claims:
        return None, []

    # The configured independent judge, or a refusal — never the pipeline's critic (RG-5).
    llm = _judge_llm()

    # Build per-claim evidence blocks once, then batch.
    claim_evidence: list[tuple[str, str]] = []
    for claim in claims:
        cited = [by_index.get(n) for n in metrics.extract_citations(claim)]
        # Show every snippet extracted from each cited source, not just the first
        # (docs/12 M5, D3). A source backs ~8 claims per report; judging each against a
        # single stored snippet measured a snippet-retention bug rather than the model's
        # citation quality.
        snippets = "\n".join(
            f"- {text}"
            for s in cited
            if s
            for text in (s.get("snippets") or ([s["snippet"]] if s.get("snippet") else []))
        )
        claim_evidence.append((claim, snippets))

    BATCH_SIZE = 4
    # Only claims the judge actually ruled on enter this map, and every number below is
    # derived from it — so an unjudged claim cannot reach the rate as a miss.
    verdict_by_claim: dict[int, bool] = {}
    # What the provider says served each ruling — the disclosure half of "a judge that
    # actually answered". None when the response names no model.
    served_by_claim: dict[int, str | None] = {}
    # And, through a gateway, which connection served it (`gateway_routing`).
    routing_by_claim: dict[int, dict[str, str | None]] = {}
    for batch_start in range(0, len(claim_evidence), BATCH_SIZE):
        batch = claim_evidence[batch_start : batch_start + BATCH_SIZE]

        # Build a single prompt covering all claims in this batch.
        claim_blocks = []
        for i, (claim, snippets) in enumerate(batch, start=1):
            claim_blocks.append(f"Claim {i}: {claim}\nEvidence {i}:\n{snippets}")
        human_content = (
            "For each claim below, determine if it is supported by its cited evidence.\n"
            'Answer with one line per claim in format: "Claim N: YES" or "Claim N: NO"\n\n'
            + "\n\n".join(claim_blocks)
        )

        messages = [
            SystemMessage(
                content="You judge whether claims are supported by their cited evidence. "
                "For each numbered claim, respond with exactly one line: "
                '"Claim N: YES" if the evidence supports the claim, or '
                '"Claim N: NO" if it does not. Answer for every claim.'
            ),
            HumanMessage(content=human_content),
        ]

        try:
            resp = await llm.ainvoke(messages)
            text = resp.content if isinstance(resp.content, str) else ""
            served = served_model_id(resp)
            routing = gateway_routing(resp)
            # Parse each "Claim N: YES/NO" line from the response.
            for match in _re.finditer(r"Claim\s+(\d+)\s*:\s*(YES|NO)", text, _re.IGNORECASE):
                idx = batch_start + int(match.group(1)) - 1
                verdict_by_claim[idx] = match.group(2).upper() == "YES"
                served_by_claim[idx] = served
                routing_by_claim[idx] = routing
        except Exception as e:  # noqa: BLE001 — one failed batch must not sink the run
            # The batch's claims stay UNJUDGED and are excluded from the denominator
            # below. Counting them as unsupported — which this did until M18 — is what
            # made an exhausted quota indistinguishable from a quality collapse, and it
            # is the same defect `benchmark.py::calc_support_rate` was written to fix.
            print(f"Citation judging error (batch {batch_start // BATCH_SIZE + 1}): {e}")

        # Free-tier rate limit avoidance (Gemini = 15 RPM). Applied once per batch
        # rather than per claim — batching 4 claims turns ~82s of sleep into ~21s.
        if RUN_CONFIG.llm_mode == "real":
            await asyncio.sleep(15)

    rows = [
        {
            "claim": claim,
            # None means the judge never ruled on this claim. Distinct from False, and
            # the two must never be collapsed by a downstream truthiness check.
            "supported": verdict_by_claim.get(i),
            "judged": i in verdict_by_claim,
            "judged_by": served_by_claim.get(i),
            # None for a claim nothing ruled on; a dict of Nones when a ruling came back
            # through no gateway that reports routing.
            "judge_routing": routing_by_claim.get(i),
            "cites": metrics.extract_citations(claim),
        }
        for i, claim in enumerate(claims)
    ]
    if not verdict_by_claim:
        # Nothing was measured. Returning 0.0 here would publish an unmeasured run as a
        # total quality failure — the unmeasured-vs-zero conflation AGENTS.md calls a P0.
        return None, rows
    supported = sum(1 for ok in verdict_by_claim.values() if ok)
    return round(supported / len(verdict_by_claim), 4), rows


async def run_one_memory(query: dict) -> dict:
    import re

    from langchain_core.messages import HumanMessage, SystemMessage

    from research_engine.llm_factory import get_llm
    from research_engine.prompt_composition import system_prompt

    started = time.time()
    sources_json = json.dumps(query["excerpts"], indent=2)

    system = (
        f"{system_prompt('chat.project')}\n\n"
        f"--- EXCERPTS ---\n<untrusted_web_content>\n{sources_json}\n</untrusted_web_content>"
    )

    messages = [SystemMessage(content=system), HumanMessage(content=query["query"])]

    llm = get_llm("chat")
    error = None
    response_text = ""
    try:
        resp = await llm.ainvoke(messages)
        response_text = resp.content if isinstance(resp.content, str) else ""
    except Exception as e:
        error = str(e)[:300]

    latency = round(time.time() - started, 2)

    cite_re = re.compile(r"\[R\d+\]")
    has_citations = bool(cite_re.search(response_text))

    is_refusal = not has_citations and (
        "not cover" in response_text.lower()
        or "doesn't cover" in response_text.lower()
        or "does not cover" in response_text.lower()
        or "not answer" in response_text.lower()
        or "does not mention" in response_text.lower()
        or "no excerpts" in response_text.lower()
        or "not found" in response_text.lower()
        or "cannot answer" in response_text.lower()
        or "not explicitly mentioned" in response_text.lower()
        or "do not contain" in response_text.lower()
    )

    if query["type"] == "supported":
        pass_test = has_citations
    else:
        pass_test = is_refusal

    return {
        "id": query["id"],
        "type": query["type"],
        "completed": error is None,
        "error": error,
        "latency_s": latency,
        "response": response_text,
        "has_citations": has_citations,
        "is_refusal": is_refusal,
        "pass_test": pass_test,
    }


def aggregate(rows: list[dict]) -> dict:
    """The run's summary. Every rate over nothing is `None`, never `0.0` (RFC §14.3, AC-13).

    A completion rate over zero queries is not a rate of zero: `0.0` reads as "every query
    failed", and against `MIN_COMPLETION_RATE` it reports a failure that never happened.
    `citation_support_rate` and the averages already returned `None` on an empty input; the
    completion rate was the one that did not.
    """
    n = len(rows)
    done = [r for r in rows if r.get("completed")]
    completion_rate = round(len(done) / n, 4) if n else None

    def mean(key: str, source=done) -> float | None:
        vals = [r[key] for r in source if isinstance(r.get(key), (int, float))]
        return round(sum(vals) / len(vals), 4) if vals else None

    support_vals = [
        r["citation_support_rate"] for r in done if r.get("citation_support_rate") is not None
    ]
    citation_support = round(sum(support_vals) / len(support_vals), 4) if support_vals else None

    return {
        "queries": n,
        "completion_rate": completion_rate,
        "avg_source_count": mean("source_count"),
        "avg_uncited_claims": mean("uncited_claim_count"),
        "avg_resolution_rate": mean("resolution_rate"),
        "avg_cost_usd": mean("cost_usd"),
        "avg_latency_s": mean("latency_s"),
        "citation_support_rate": citation_support,
    }


#: How an unmeasured value is shown to a person — the same words `benchmark.py` and
#: `retrieval.py` already use. The result file stores `null`; this is only the console's
#: rendering, so a reader of the terminal never sees a bare `null` and wonders whether it
#: meant zero (RFC §14.3: an unmeasured result is reported as `n/a (unmeasured)`).
UNMEASURED = "n/a (unmeasured)"


def _for_display(summary: dict) -> dict:
    """`summary` with every unmeasured value spelled out, for the console only."""
    return {k: (UNMEASURED if v is None else v) for k, v in summary.items()}


#: The memory eval's pass threshold. Named rather than left inline in `main()`, where it
#: was untestable; the value is unchanged.
MIN_MEMORY_PASS_RATE = 0.90


def aggregate_memory(rows: list[dict]) -> dict:
    """The memory eval's summary, with the same rule as `aggregate`: nothing measured is
    `None`. This was inline in `main()` and published `0.0` for both fields on an empty run."""
    n = len(rows)
    passed = sum(1 for r in rows if r.get("pass_test"))
    return {
        "queries": n,
        "pass_rate": round(passed / n, 4) if n else None,
        "avg_latency_s": round(sum(r.get("latency_s", 0) for r in rows) / n, 4) if n else None,
    }


def check_memory_criteria(agg: dict) -> dict:
    return {
        "pass_rate_ok": _meets(agg["pass_rate"], MIN_MEMORY_PASS_RATE),
        "thresholds": {"min_pass_rate": MIN_MEMORY_PASS_RATE},
    }


def _retriever_in_use() -> str:
    """Which search backend this run actually had available.

    Recorded because it materially changes the evidence a report is built from, and the
    keyless DuckDuckGo fallback is rate-limited enough to depress quality on its own — a
    published number without this is not reproducible.
    """
    if RUN_CONFIG.llm_mode == "fake":
        return "fixtures (no network)"
    if RUN_CONFIG.tavily_api_key:
        return "tavily (→ brave → duckduckgo fallback)"
    if RUN_CONFIG.brave_api_key:
        return "brave (→ duckduckgo fallback)"
    return "duckduckgo (keyless fallback — rate-limited)"


def _meets(value: float | None, threshold: float) -> bool | None:
    """`True`/`False` against an inclusive threshold, or `None` when nothing was measured.

    `None` is a third answer, not a failure: "could not tell" must never be reported as
    "fell short", or an empty run becomes indistinguishable from a regression.
    """
    return None if value is None else value >= threshold


def check_release_criteria(agg: dict) -> dict:
    return {
        "completion_rate_ok": _meets(agg["completion_rate"], MIN_COMPLETION_RATE),
        "citation_support_ok": _meets(agg.get("citation_support_rate"), MIN_CITATION_SUPPORT),
        "thresholds": {
            "min_completion_rate": MIN_COMPLETION_RATE,
            "min_citation_support": MIN_CITATION_SUPPORT,
        },
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run the report-quality eval suite.")
    parser.add_argument(
        "--mode",
        choices=["report", "memory"],
        default="report",
        help="Which eval to run (report or memory)",
    )
    parser.add_argument("--limit", type=int, default=None, help="run only the first N queries")
    parser.add_argument(
        "--out", type=str, default=None, help="output path (default results/eval-<date>.json)"
    )
    parser.add_argument("--date", type=str, default=None, help="override the run date (YYYY-MM-DD)")
    parser.add_argument(
        "--candidate",
        type=str,
        default=None,
        help="JSON file of {role: prompt}. Runs the query set twice — shipped prompts, then "
        "this spec — and reports both against the same thresholds (report mode only)",
    )
    parser.add_argument(
        "--judge",
        type=str,
        default=None,
        help="provider:model of the citation judge. Required for a real-mode report eval, and "
        "refused if it is a router alias or any model the pipeline runs on (RG-5)",
    )
    args = parser.parse_args()

    # Before any query runs: a run that would be self-judged must cost nothing.
    judging = args.mode == "report" and RUN_CONFIG.llm_mode == "real"
    if judging:
        if not args.judge:
            parser.error(
                "a real-mode report eval needs --judge provider:model, a pinned model "
                "independent of the pipeline's routes (RG-5); nothing was run"
            )
        try:
            configure_judge(args.judge)
        except JudgeConfigError as e:
            parser.error(f"{e}; nothing was run")
    elif args.judge:
        parser.error("--judge applies to a real-mode report eval; this run judges nothing")

    candidate = None
    if args.candidate:
        if args.mode != "report":
            parser.error("--candidate applies to the report eval (RFC §14.2), not --mode memory")
        try:
            candidate = load_candidate(Path(args.candidate))
        except CandidateSpecError as e:
            parser.error(str(e))

    if args.mode == "memory":
        queries_file = EVALS_DIR / "memory_queries.json"
    else:
        queries_file = EVALS_DIR / "queries.json"

    queries = json.loads(queries_file.read_text())["queries"]
    if args.limit:
        queries = queries[: args.limit]

    print(f"Running {len(queries)} queries in LLM_MODE={RUN_CONFIG.llm_mode} mode={args.mode}…")
    rows = []
    for q in queries:
        if args.mode == "memory":
            row = await run_one_memory(q)
            rows.append(row)
            flag = "✓" if row.get("pass_test") else "✗"
            print(f"  {flag} {q['id']:24s} type={q['type']} latency={row.get('latency_s')}s")
        else:
            row = await run_one(q)
            rows.append(row)
            flag = "✓" if row.get("completed") else "✗"
            print(
                f"  {flag} {q['id']:24s} sources={row.get('source_count')} "
                f"uncited={row.get('uncited_claim_count')} cost=${row.get('cost_usd')}"
            )

        if RUN_CONFIG.llm_mode == "real":
            await asyncio.sleep(60)

    candidate_rows: list[dict] = []
    if candidate is not None:
        roles = ", ".join(sorted(candidate))
        print(f"\nCandidate spec ({roles}) — the same {len(queries)} queries, the same thresholds…")
        for q in queries:
            row = await run_one(q, prompt_overrides=candidate)
            candidate_rows.append(row)
            flag = "✓" if row.get("completed") else "✗"
            print(
                f"  {flag} {q['id']:24s} sources={row.get('source_count')} "
                f"uncited={row.get('uncited_claim_count')} cost=${row.get('cost_usd')}"
            )
            if RUN_CONFIG.llm_mode == "real":
                await asyncio.sleep(60)

    if args.mode == "memory":
        agg = aggregate_memory(rows)
        release_criteria = check_memory_criteria(agg)
    else:
        agg = aggregate(rows)
        release_criteria = check_release_criteria(agg)

    run_date = args.date or datetime.now(UTC).strftime("%Y-%m-%d")
    payload = {
        "date": run_date,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "llm_mode": RUN_CONFIG.llm_mode,
        "mode": args.mode,
        # In fake mode `llm_factory` returns `fake_model(role)` and no provider is contacted,
        # so writing five real-looking ids here would record models we never called —
        # the exact rule in AGENTS.md ("never record a model id you did not actually
        # call"). eval-2026-07-23.json is the artifact that did it.
        "models": (
            {"_note": "fake mode — no provider was called"}
            if RUN_CONFIG.llm_mode == "fake"
            else {role: RUN_CONFIG.models[role] for role in _ROLES}
        ),
        "method": {
            "metrics_version": metrics.METRICS_VERSION,
            "retriever": _retriever_in_use() if args.mode == "report" else "none (static memory)",
            "query_set": f"evals/{'memory_' if args.mode == 'memory' else ''}queries.json",
        },
        "aggregate": agg,
        "release_criteria": release_criteria,
        "results": rows,
    }
    if candidate is not None:
        # The top-level `aggregate`/`release_criteria`/`results` stay the shipped baseline,
        # exactly as in a plain run, so a reader of the existing schema reads it unchanged.
        payload["candidate"] = candidate_section(candidate, candidate_rows)
    if judging:
        # Only where a judge ran. A scripted run calls no judge, and naming one it never
        # called is the "model id you did not call" rule the `models` note above follows.
        payload["judge"] = judge_section(
            JUDGE_ROUTE, rows, candidate_rows if candidate is not None else None
        )

    RESULTS_DIR.mkdir(exist_ok=True)
    out = Path(args.out) if args.out else _result_path(run_date, custom_spec=candidate is not None)
    if out.exists():
        # Only reachable via an explicit --out; `_result_path` never returns a live path.
        # Refuse rather than overwrite: a committed result is evidence (AGENTS.md).
        raise SystemExit(
            f"{out} already exists and eval results are write-once. "
            f"Pass a new --out, or omit --out to get an auto-numbered filename."
        )
    out.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"\nAggregate: {json.dumps(_for_display(agg))}")
    if judging:
        judge = payload["judge"]
        served = sorted(
            {
                m
                for part in ("baseline", "candidate")
                for m in judge.get(part, {}).get("served_models", [])
            }
        )
        print(f"Judge: {judge['route']} (answered as: {', '.join(served) or 'undisclosed'})")
    print(f"Release criteria: {json.dumps(_for_display(payload['release_criteria']))}")
    if candidate is not None:
        section = payload["candidate"]
        print(f"Candidate aggregate: {json.dumps(_for_display(section['aggregate']))}")
        print(f"Candidate criteria: {json.dumps(_for_display(section['release_criteria']))}")
    # Show a repo-relative path when the output is inside the repo, and the plain path
    # when it isn't — `relative_to` raises on an outside path, which used to crash the
    # run *after* the results file had already been written.
    try:
        shown = out.relative_to(EVALS_DIR.parent)
    except ValueError:
        shown = out
    print(f"Wrote {shown}")


if __name__ == "__main__":
    asyncio.run(main())
