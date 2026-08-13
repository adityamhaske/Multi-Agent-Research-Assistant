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
from datetime import UTC, datetime
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver

from evals import metrics
from research_engine.graph import build_graph
from research_engine.local import load_env_file, run_config_from_env
from research_engine.runconfig import set_process_default
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


async def run_one(query: dict) -> dict:
    """Run one query to the gate; return its report metrics + timing."""
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
    per-claim rate-limit sleeps. Returns (supported / cited-claims, per-claim rows);
    the rate is None if there are no cited claims."""
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
    supported = 0
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
                ok = match.group(2).upper() == "YES"
                verdict_by_claim[idx] = ok
                if ok:
                    supported += 1
        except Exception as e:  # noqa: BLE001
            # Failed batch counts 0 supported — same semantics as the old per-claim
            # path where an individual failure also contributed nothing.
            print(f"Citation judging error (batch {batch_start // BATCH_SIZE + 1}): {e}")

        # Free-tier rate limit avoidance (Gemini = 15 RPM). Applied once per batch
        # rather than per claim — batching 4 claims turns ~82s of sleep into ~21s.
        if RUN_CONFIG.llm_mode == "real":
            await asyncio.sleep(4.1)

    rows = [
        {
            "claim": claim,
            "supported": verdict_by_claim.get(i, False),
            "cites": metrics.extract_citations(claim),
        }
        for i, claim in enumerate(claims)
    ]
    return round(supported / len(claims), 4), rows


async def run_one_memory(query: dict) -> dict:
    import re

    from langchain_core.messages import HumanMessage, SystemMessage

    from research_engine import prompts
    from research_engine.llm_factory import get_llm

    started = time.time()
    sources_json = json.dumps(query["excerpts"], indent=2)

    system = (
        f"{prompts.PROJECT_CHAT_PROMPT}\n\n"
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
    n = len(rows)
    done = [r for r in rows if r.get("completed")]
    completion_rate = round(len(done) / n, 4) if n else 0.0

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


def check_release_criteria(agg: dict) -> dict:
    support = agg.get("citation_support_rate")
    return {
        "completion_rate_ok": agg["completion_rate"] >= MIN_COMPLETION_RATE,
        "citation_support_ok": None if support is None else support >= MIN_CITATION_SUPPORT,
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
    args = parser.parse_args()

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
            await asyncio.sleep(5)

    if args.mode == "memory":
        n = len(rows)
        passed = sum(1 for r in rows if r.get("pass_test"))
        agg = {
            "queries": n,
            "pass_rate": round(passed / n, 4) if n else 0.0,
            "avg_latency_s": round(sum(r.get("latency_s", 0) for r in rows) / n, 4) if n else 0.0,
        }
        release_criteria = {
            "pass_rate_ok": agg["pass_rate"] >= 0.90,
            "thresholds": {"min_pass_rate": 0.90},
        }
    else:
        agg = aggregate(rows)
        release_criteria = check_release_criteria(agg)

    run_date = args.date or datetime.now(UTC).strftime("%Y-%m-%d")
    payload = {
        "date": run_date,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "llm_mode": RUN_CONFIG.llm_mode,
        "mode": args.mode,
        "models": {
            "planner": RUN_CONFIG.models["planner"],
            "executor": RUN_CONFIG.models["executor"],
            "critic": RUN_CONFIG.models["critic"],
            "synthesizer": RUN_CONFIG.models["synthesizer"],
            "chat": RUN_CONFIG.models["chat"],
        },
        "method": {
            "metrics_version": metrics.METRICS_VERSION,
            "retriever": _retriever_in_use() if args.mode == "report" else "none (static memory)",
            "query_set": f"evals/{'memory_' if args.mode == 'memory' else ''}queries.json",
        },
        "aggregate": agg,
        "release_criteria": release_criteria,
        "results": rows,
    }

    RESULTS_DIR.mkdir(exist_ok=True)
    out = Path(args.out) if args.out else RESULTS_DIR / f"eval-{run_date}.json"
    out.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"\nAggregate: {json.dumps(agg)}")
    print(f"Release criteria: {json.dumps(payload['release_criteria'])}")
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
