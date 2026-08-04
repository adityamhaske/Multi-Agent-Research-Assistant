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
        result["citation_support_rate"] = await judge_citation_support(report, sources)
    return result


async def judge_citation_support(report: str, sources: list[dict]) -> float | None:
    """Real-mode only: ask a model whether each cited claim is actually supported by the
    snippet it cites. Returns supported / cited-claims, or None if there are none."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from research_engine.llm_factory import get_llm

    by_index = {s.get("index"): s for s in sources if isinstance(s, dict)}
    claims = [c for c in metrics.claim_lines(report) if metrics.CITE_RE.search(c)]
    if not claims:
        return None

    llm = get_llm("critic")
    supported = 0
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
        messages = [
            SystemMessage(
                content="You judge whether a claim is supported by the cited evidence. "
                "Answer with exactly YES or NO."
            ),
            HumanMessage(content=f"Claim: {claim}\n\nCited evidence:\n{snippets}\n\nSupported?"),
        ]
        try:
            resp = await llm.ainvoke(messages)
            text = resp.content if isinstance(resp.content, str) else ""
            if text.strip().upper().startswith("YES"):
                supported += 1
        except Exception:  # noqa: BLE001
            pass
    return round(supported / len(claims), 4)


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
    parser.add_argument("--limit", type=int, default=None, help="run only the first N queries")
    parser.add_argument(
        "--out", type=str, default=None, help="output path (default results/eval-<date>.json)"
    )
    parser.add_argument("--date", type=str, default=None, help="override the run date (YYYY-MM-DD)")
    args = parser.parse_args()

    queries = json.loads((EVALS_DIR / "queries.json").read_text())["queries"]
    if args.limit:
        queries = queries[: args.limit]

    print(f"Running {len(queries)} queries in LLM_MODE={RUN_CONFIG.llm_mode}…")
    rows = []
    for q in queries:
        row = await run_one(q)
        rows.append(row)
        flag = "✓" if row.get("completed") else "✗"
        print(
            f"  {flag} {q['id']:24s} sources={row.get('source_count')} "
            f"uncited={row.get('uncited_claim_count')} cost=${row.get('cost_usd')}"
        )

    agg = aggregate(rows)
    run_date = args.date or datetime.now(UTC).strftime("%Y-%m-%d")
    payload = {
        "date": run_date,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "llm_mode": RUN_CONFIG.llm_mode,
        "models": {
            "planner": RUN_CONFIG.models["planner"],
            "executor": RUN_CONFIG.models["executor"],
            "critic": RUN_CONFIG.models["critic"],
            "synthesizer": RUN_CONFIG.models["synthesizer"],
        },
        # Enough context to reproduce the run and to know what the numbers mean. A
        # published figure is only meaningful alongside its method: which metric
        # definitions produced it (see metrics.METRICS_VERSION — v2 numbers are not
        # comparable to v1), which retriever supplied the evidence, and how the
        # citation-support rate was judged.
        "method": {
            "metrics_version": metrics.METRICS_VERSION,
            "retriever": _retriever_in_use(),
            "citation_support_judge": (
                f"LLM-judged per sentence by the 'critic' role "
                f"({RUN_CONFIG.models['critic']}); each cited sentence is shown only the "
                f"snippets it cites and answered YES/NO. Self-judged, not human-rated."
            ),
            "query_set": "evals/queries.json",
        },
        "aggregate": agg,
        "release_criteria": check_release_criteria(agg),
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
