"""
Eval harness (docs/08 §5). Runs the fixed query set through the compiled graph up to
the review gate and records per-report quality metrics to a dated JSON file, so report
quality is diffable over time.

Per-commit CI uses fake models; evals measure real-model quality. Run:

    make eval                       # fake mode (deterministic, no keys) — smoke/baseline
    LLM_MODE=real GOOGLE_API_KEY=… make eval

The committed baseline in results/ is a fake-mode run: it exercises the metric plumbing
and pins structural numbers. Real-model runs additionally compute an LLM-judged citation
support rate and are what the release criteria gate on.
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
from research_engine.runconfig import reset_run_config, set_process_default, set_run_config
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

    from research_engine.llm_factory import get_llm

    by_index = {s.get("index"): s for s in sources if isinstance(s, dict)}
    claims = [c for c in metrics.claim_lines(report) if metrics.CITE_RE.search(c)]
    if not claims:
        return None, []

    llm = get_llm("critic")

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
            # Parse each "Claim N: YES/NO" line from the response.
            for match in _re.finditer(r"Claim\s+(\d+)\s*:\s*(YES|NO)", text, _re.IGNORECASE):
                idx = batch_start + int(match.group(1)) - 1
                verdict_by_claim[idx] = match.group(2).upper() == "YES"
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
    args = parser.parse_args()

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
