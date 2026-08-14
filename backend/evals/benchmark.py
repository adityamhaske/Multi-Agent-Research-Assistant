"""
M13 Benchmark Runner (docs/engineering/16_Benchmark_Methodology.md)
"""

import argparse
import asyncio
import json
import os
import re
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver

from evals import metrics, normalization
from research_engine.graph import build_graph
from research_engine.llm_factory import get_llm
from research_engine.local import load_env_file, run_config_from_env
from research_engine.runconfig import (
    get_run_config,
    reset_run_config,
    set_process_default,
    set_run_config,
)
from research_engine.runner import initial_state

try:
    from gpt_researcher import GPTResearcher
except ImportError:
    GPTResearcher = None


EVALS_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVALS_DIR / "results"

DEFAULT_JUDGE_MODEL = "anthropic:claude-sonnet-4-6"


def _build_judge(judge_model: str) -> tuple[Any, str]:
    """Build the citation judge, returning it with the model id actually used.

    `BENCHMARK_JUDGE_MODEL` wins over the caller's default so a run can be redirected at a
    local judge (`ollama:qwen2.5:7b`) when a hosted quota is exhausted, which is the only
    thing that kept this harness from running at all. Routing goes through the engine's
    factory rather than a direct provider import, so every provider the product supports —
    OpenRouter and Ollama included — is available here for free.

    Returning the resolved id is the point: the previous version advertised one model in
    the trace and instantiated another, which silently falsified the run's provenance.
    """
    resolved = os.environ.get("BENCHMARK_JUDGE_MODEL") or judge_model or DEFAULT_JUDGE_MODEL
    # Only the model half is validated here; the provider half is the factory's business,
    # and it already raises with the full list of known providers if it is wrong.
    name = resolved.partition(":")[2]
    if not name:
        raise SystemExit(
            f"BENCHMARK_JUDGE_MODEL must be 'provider:model' (got {resolved!r}). "
            f"Examples: anthropic:claude-sonnet-4-6, openrouter:anthropic/claude-3.5-sonnet, "
            f"ollama:qwen2.5:7b"
        )
    # `critic` is the zero-temperature role, which is what a binary judge wants. The
    # override is scoped to building the client: the returned model carries its own
    # provider and endpoint, so the pipeline's routing is restored immediately after.
    base = get_run_config()
    token = set_run_config(replace(base, models={**base.models, "critic": resolved}))
    try:
        return get_llm("critic"), resolved
    finally:
        reset_run_config(token)


def sanitize_text(text: str) -> str:
    """Strip markdown hyperlinks and html to produce plain text."""
    # Remove markdown links [text](url) -> text
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    # Remove simple html tags
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


async def score_system_claims(
    system: str,
    query_id: str,
    report: str,
    sources: list[dict],
    judge_model: str = DEFAULT_JUDGE_MODEL,
) -> list[dict]:
    """
    Stateless, isolated judge function that scores claims for ONE system.
    Returns list of trace dicts matching the JSON Trace Schema.
    """
    by_index = {s.get("index"): s for s in sources if isinstance(s, dict)}
    claims = [c for c in metrics.claim_lines(report) if metrics.CITE_RE.search(c)]

    if not claims:
        return []

    traces = []

    # The judge is deliberately independent of the RunConfig that produced the reports:
    # scoring a Gemini-written report with a Gemini judge is same-vendor bias (docs/16 §3.2).
    # It is resolved from BENCHMARK_JUDGE_MODEL as "provider:model" so the documented knob
    # actually works, and so a run can fall back to a local judge when a hosted quota is
    # spent. The model that is *used* is what gets recorded — never a hardcoded label.
    judge_llm, judge_model = _build_judge(judge_model)

    BATCH_SIZE = 4

    for batch_start in range(0, len(claims), BATCH_SIZE):
        batch = claims[batch_start : batch_start + BATCH_SIZE]
        claim_blocks = []
        batch_traces = []

        for i, claim_text in enumerate(batch, start=1):
            cited_indices = metrics.extract_citations(claim_text)
            cited_sources = [by_index.get(n) for n in cited_indices]

            snippets_list = []
            plain_text_snippets = []
            for s in cited_sources:
                if not s:
                    continue
                snips = s.get("snippets") or ([s["snippet"]] if s.get("snippet") else [])
                for snip in snips:
                    clean_snip = sanitize_text(snip)
                    snippets_list.append(
                        {
                            "index": s.get("index"),
                            "source_url": s.get("url"),
                            "snippet_text": clean_snip,
                        }
                    )
                    plain_text_snippets.append(f"- {clean_snip}")

            snippets_str = "\n".join(plain_text_snippets)
            claim_text_clean = sanitize_text(claim_text)
            claim_blocks.append(f"Claim {i}: {claim_text_clean}\nEvidence {i}:\n{snippets_str}")

            trace = {
                "query_id": query_id,
                "system": system,
                "claim_text": claim_text_clean,
                "cited_indices": cited_indices,
                "cited_snippets": snippets_list,
                "judge_verdict": None,
                "judge_reasoning": None,
                "judge_model": judge_model,
                # isoformat() on an aware datetime already carries "+00:00"; appending "Z"
                # produced "…+00:00Z", which is not valid ISO 8601 and fails strict parsers.
                "timestamp": datetime.now(UTC).isoformat(),
            }
            batch_traces.append(trace)

        human_content = (
            "For each claim below, determine if it is supported by its cited evidence.\n"
            'Answer with one line per claim in format: "Claim N: YES" or "Claim N: NO". '
            'Then, provide a brief reasoning on the next line starting with "Reasoning N: "\n\n'
            + "\n\n".join(claim_blocks)
        )

        messages = [
            SystemMessage(
                content="You judge whether claims are supported by their cited evidence. "
                "For each numbered claim, respond with exactly two lines: "
                '"Claim N: YES" if the evidence supports the claim, or '
                '"Claim N: NO" if it does not. '
                'Then "Reasoning N: <short reason>". Answer for every claim.'
            ),
            HumanMessage(content=human_content),
        ]

        try:
            resp = await judge_llm.ainvoke(messages)
            text = resp.content if isinstance(resp.content, str) else ""

            # A router (OmniRoute, OpenRouter) resolves an `auto/*` alias to a different
            # concrete model per call, and the alias can disagree with what actually
            # served the request — `auto/claude-sonnet` answering as gpt-4o. Record what
            # replied, not what we asked for. Misreporting the judge is precisely the
            # defect this file already shipped once; an alias makes it easy to ship again.
            meta = getattr(resp, "response_metadata", None) or {}
            served = meta.get("model_name") or meta.get("model")
            if served:
                for trace in batch_traces:
                    trace["judge_model_served"] = served

            # Parse responses
            for match in re.finditer(r"Claim\s+(\d+)\s*:\s*(YES|NO)", text, re.IGNORECASE):
                idx = int(match.group(1)) - 1
                if idx < len(batch_traces):
                    batch_traces[idx]["judge_verdict"] = (
                        "SUPPORTED" if match.group(2).upper() == "YES" else "UNSUPPORTED"
                    )

            for match in re.finditer(
                r"Reasoning\s+(\d+)\s*:\s*(.*?)(?=\nClaim|\Z)", text, re.IGNORECASE | re.DOTALL
            ):
                idx = int(match.group(1)) - 1
                if idx < len(batch_traces):
                    batch_traces[idx]["judge_reasoning"] = match.group(2).strip()

        except Exception as e:
            # Recorded on the trace, not just printed. A provider 429 used to leave
            # `judge_verdict` at None, and None counts as "not SUPPORTED" in the support
            # rate — so an exhausted quota was indistinguishable from a pipeline that
            # cites badly. Unjudged claims are now excluded from the denominator instead.
            print(f"Citation judging error for {system}: {e}")
            for trace in batch_traces:
                trace["judge_error"] = str(e)

        traces.extend(batch_traces)

        # Free-tier rate-limit courtesy; skipped after the final batch, and skipped
        # entirely for a local judge, which has no quota to respect.
        if batch_start + BATCH_SIZE < len(claims) and not judge_model.startswith("ollama:"):
            await asyncio.sleep(15)

    return traces


async def run_our_pipeline(query: dict) -> tuple[str, list[dict], float, float]:
    """Run our pipeline, returning (report, sources, cost_usd, latency_s)."""
    graph = build_graph(MemorySaver())
    thread_id = f"eval-{query['id']}-ours"
    config = {"configurable": {"thread_id": thread_id}}
    initial = initial_state(
        session_id=thread_id,
        user_id="eval",
        query=query["query"],
        depth=query.get("depth", "balanced"),
    )

    started = time.time()
    await graph.ainvoke(initial, config)
    state = (await graph.aget_state(config)).values

    latency = round(time.time() - started, 2)
    report = state.get("draft_report") or ""
    sources = state.get("sources") or []
    cost = round(state.get("cost_usd", 0.0), 6)

    return report, sources, cost, latency


async def run_gpt_researcher_pipeline(query: dict) -> tuple[str, list[dict], float, float]:
    """Run GPT-Researcher, returning (normalized_report, sources, cost_usd, latency_s)."""
    started = time.time()
    report = ""
    sources = []
    cost = 0.0

    if GPTResearcher:
        try:
            researcher = GPTResearcher(
                query=query["query"], report_type="research_report", report_source="web"
            )
            await researcher.conduct_research()
            raw_report = await researcher.write_report()

            # Snippets must be the baseline's *real* retrieved text. The previous version
            # stored the literal string "Content extracted by gpt-researcher" for every
            # URL, which no claim can ever be supported by — that silently drove the
            # baseline's judged support rate to zero and made the comparison meaningless.
            # If the installed version exposes no real source text, we take none and the
            # baseline is reported as unmeasurable rather than as a loss.
            raw_snippets = {}
            for attr in ("get_research_sources", "get_source_urls"):
                getter = getattr(researcher, attr, None)
                if getter is None:
                    continue
                try:
                    entries = getter()
                except Exception:
                    continue
                for entry in entries or []:
                    if not isinstance(entry, dict):
                        continue  # a bare URL carries no text; nothing honest to record
                    url = entry.get("url") or entry.get("source")
                    body = entry.get("raw_content") or entry.get("content") or ""
                    if url and body:
                        raw_snippets.setdefault(url, []).append(body)
                if raw_snippets:
                    break
            if not raw_snippets:
                print(
                    "  WARNING: gpt-researcher exposed no source text on this version; "
                    "its citation-support score is UNMEASURABLE, not 0."
                )

            report, sources = normalization.normalize_external_report(raw_report, raw_snippets)
            # cost calculation could be added if gpt-researcher returns it
        except Exception as e:
            print(f"GPT-Researcher execution failed: {e}")
    else:
        print("GPT-Researcher not installed. Skipping execution.")
        report = "Failed to run. GPT-Researcher not installed."

    latency = round(time.time() - started, 2)
    return report, sources, cost, latency


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir", type=str, default=str(RESULTS_DIR / "benchmark_v1"), help="output directory"
    )
    parser.add_argument("--limit", type=int, default=None, help="limit number of queries")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    load_env_file()
    # Routing comes from the environment like every other entry point. This used to
    # overwrite MODEL_* with gemini-2.5-flash unconditionally, which made the harness
    # unrunnable the moment that one key hit its quota — no local or OpenRouter fallback
    # was reachable even though the engine supports both. Pin a comparison run by
    # exporting MODEL_* (docs/16 §4.1), and the summary records what was actually used.
    RUN_CONFIG = run_config_from_env(fake=False)
    set_process_default(RUN_CONFIG)

    queries_file = EVALS_DIR / "queries.json"
    queries = json.loads(queries_file.read_text())["queries"]
    if args.limit:
        queries = queries[: args.limit]

    our_traces = []
    gpt_traces = []

    our_metrics = []
    gpt_metrics = []

    print("=== 1. Executing Our Pipeline ===")
    for q in queries:
        print(f"  Running query: {q['id']}")
        report, sources, cost, latency = await run_our_pipeline(q)
        rep_metrics = metrics.report_metrics(report, sources)
        our_metrics.append({"id": q["id"], "cost_usd": cost, "latency_s": latency, **rep_metrics})

        traces = await score_system_claims("our_pipeline", q["id"], report, sources)
        our_traces.extend(traces)

        # Save raw traces individually per query per system
        query_out = out_dir / f"our_pipeline_{q['id']}_trace.json"
        query_out.write_text(json.dumps(traces, indent=2))

    print("\n=== 2. Executing GPT-Researcher ===")
    for q in queries:
        print(f"  Running query: {q['id']}")
        report, sources, cost, latency = await run_gpt_researcher_pipeline(q)
        rep_metrics = metrics.report_metrics(report, sources)
        gpt_metrics.append({"id": q["id"], "cost_usd": cost, "latency_s": latency, **rep_metrics})

        traces = await score_system_claims("gpt_researcher", q["id"], report, sources)
        gpt_traces.extend(traces)

        # Save raw traces individually per query per system
        query_out = out_dir / f"gpt_researcher_{q['id']}_trace.json"
        query_out.write_text(json.dumps(traces, indent=2))

    print("\n=== 3. Summary & Comparison Table ===")

    # Calculate LLM-Judged Citation Support Rate
    def calc_support_rate(system_traces):
        """Support rate over *judged* claims, or None when nothing could be judged.

        Claims the judge never ruled on (provider error, unparsed reply) are excluded
        rather than counted against the system. Returning None for an empty denominator
        keeps "we could not measure this" distinct from "it scored zero" — the two were
        previously reported identically as 0.0.
        """
        judged = [
            t for t in system_traces if t.get("judge_verdict") in ("SUPPORTED", "UNSUPPORTED")
        ]
        if not judged:
            return None
        supported = sum(1 for t in judged if t["judge_verdict"] == "SUPPORTED")
        return round(supported / len(judged), 4)

    def show(value, suffix: str = "") -> str:
        """Render a metric, never printing a number we did not actually measure."""
        return "n/a (unmeasured)" if value is None else f"{value}{suffix}"

    our_support_rate = calc_support_rate(our_traces)
    gpt_support_rate = calc_support_rate(gpt_traces)

    def mean(key: str, metrics_list) -> float | None:
        # None, not 0.0, for an empty sample — a run that produced no data must not
        # render as a legitimate score of zero in the published table.
        vals = [r[key] for r in metrics_list if isinstance(r.get(key), (int, float))]
        return round(sum(vals) / len(vals), 4) if vals else None

    judge_used = os.environ.get("BENCHMARK_JUDGE_MODEL") or DEFAULT_JUDGE_MODEL
    gpt_ran = GPTResearcher is not None
    summary_md = f"""# Benchmark Comparison

**Run provenance** — every number below was produced by this configuration:

- Queries: {len(queries)} (`evals/queries.json`)
- Our pipeline routing: {", ".join(f"{r}={RUN_CONFIG.model_for(r)}" for r in ("planner", "executor", "critic", "synthesizer"))}
- Citation judge: `{judge_used}`
- GPT-Researcher: {"installed" if gpt_ran else "**NOT INSTALLED — its column is not a measurement**"}

| Metric | Our Pipeline | GPT-Researcher |
|---|---|---|
| Citation Resolution Rate | {show(mean("resolution_rate", our_metrics))} | {show(mean("resolution_rate", gpt_metrics))} |
| Uncited Claim Count | {show(mean("uncited_claim_count", our_metrics))} | {show(mean("uncited_claim_count", gpt_metrics))} |
| LLM-Judged Support Rate | {show(our_support_rate)} | {show(gpt_support_rate)} |
| Contradictions Surfaced | {show(mean("contradictions_surfaced", our_metrics))} | {show(mean("contradictions_surfaced", gpt_metrics))} |
| Avg Cost (USD) | {show(mean("cost_usd", our_metrics), " USD")} | {show(mean("cost_usd", gpt_metrics), " USD")} |
| Avg Wall-clock Time (s) | {show(mean("latency_s", our_metrics), "s")} | {show(mean("latency_s", gpt_metrics), "s")} |

Claims the judge never ruled on are excluded from the support-rate denominator; a metric
reading `n/a (unmeasured)` was not measured and must not be published as a score.
"""

    summary_out = out_dir / "summary.md"
    summary_out.write_text(summary_md)
    print(summary_md)
    print(f"\nWrote results to {out_dir}")


if __name__ == "__main__":
    asyncio.run(main())
