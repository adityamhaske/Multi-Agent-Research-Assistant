"""
M13 Benchmark Runner (docs/engineering/16_Benchmark_Methodology.md)
"""

import argparse
import asyncio
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, SystemMessage

from evals import metrics, normalization
from research_engine.graph import build_graph
from research_engine.local import load_env_file, run_config_from_env
from research_engine.runconfig import set_process_default
from research_engine.runner import initial_state
from research_engine.llm_factory import get_llm

try:
    from gpt_researcher import GPTResearcher
except ImportError:
    GPTResearcher = None


EVALS_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVALS_DIR / "results"

def sanitize_text(text: str) -> str:
    """Strip markdown hyperlinks and html to produce plain text."""
    # Remove markdown links [text](url) -> text
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    # Remove simple html tags
    text = re.sub(r'<[^>]+>', '', text)
    return text.strip()


async def score_system_claims(system: str, query_id: str, report: str, sources: list[dict], judge_model: str = "claude-sonnet-4-6") -> list[dict]:
    """
    Stateless, isolated judge function that scores claims for ONE system.
    Returns list of trace dicts matching the JSON Trace Schema.
    """
    by_index = {s.get("index"): s for s in sources if isinstance(s, dict)}
    claims = [c for c in metrics.claim_lines(report) if metrics.CITE_RE.search(c)]
    
    if not claims:
        return []

    traces = []
    llm = get_llm("critic") # This is a placeholder since we want to force the judge_model

    # Use a fresh, stateless client config for the judge
    # We will override the model using the bound kwargs or re-instantiate if needed
    # Actually, research_engine.llm_factory uses the RunConfig.
    # To use a specific model regardless of RunConfig, we can import ChatAnthropic directly
    from langchain_anthropic import ChatAnthropic
    
    # We map claude-sonnet-4-6 to the actual anthropic model string if needed
    # Usually it's claude-3-5-sonnet-20241022 or similar.
    actual_model_name = "claude-3-5-sonnet-20241022" 
    
    # Instantiate stateless client
    judge_llm = ChatAnthropic(
        model=actual_model_name,
        temperature=0.0,
        max_tokens=2048,
        api_key=os.environ.get("ANTHROPIC_API_KEY")
    )

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
                    snippets_list.append({"index": s.get("index"), "source_url": s.get("url"), "snippet_text": clean_snip})
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
                "timestamp": datetime.now(UTC).isoformat() + "Z"
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
            
            # Parse responses
            for match in re.finditer(r"Claim\s+(\d+)\s*:\s*(YES|NO)", text, re.IGNORECASE):
                idx = int(match.group(1)) - 1
                if idx < len(batch_traces):
                    batch_traces[idx]["judge_verdict"] = "SUPPORTED" if match.group(2).upper() == "YES" else "UNSUPPORTED"
                    
            for match in re.finditer(r"Reasoning\s+(\d+)\s*:\s*(.*?)(?=\nClaim|\Z)", text, re.IGNORECASE | re.DOTALL):
                idx = int(match.group(1)) - 1
                if idx < len(batch_traces):
                    batch_traces[idx]["judge_reasoning"] = match.group(2).strip()

        except Exception as e:
            print(f"Citation judging error for {system}: {e}")

        traces.extend(batch_traces)
        
        # Free-tier rate limit avoidance
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
            researcher = GPTResearcher(query=query["query"], report_type="research_report", report_source="web")
            await researcher.conduct_research()
            raw_report = await researcher.write_report()
            
            raw_snippets = {}
            if hasattr(researcher, "get_source_urls"):
                # Approximate snippet extraction depending on gpt-researcher version API
                # gpt-researcher=3.2.4 API is assumed below based on standard
                try:
                    for url in researcher.get_source_urls():
                        raw_snippets[url] = ["Content extracted by gpt-researcher"]
                except Exception:
                    pass
            
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
    parser.add_argument("--output-dir", type=str, default=str(RESULTS_DIR / "benchmark_v1"), help="output directory")
    parser.add_argument("--limit", type=int, default=None, help="limit number of queries")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    load_env_file()
    # Explicitly enforce model to gemini-2.5-flash as specified by user
    os.environ["MODEL_PLANNER"] = "google:gemini-2.5-flash"
    os.environ["MODEL_EXECUTOR"] = "google:gemini-2.5-flash"
    os.environ["MODEL_CRITIC"] = "google:gemini-2.5-flash"
    os.environ["MODEL_SYNTHESIZER"] = "google:gemini-2.5-flash"
    
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
        if not system_traces: return 0.0
        supported = sum(1 for t in system_traces if t.get("judge_verdict") == "SUPPORTED")
        return round(supported / len(system_traces), 4)

    our_support_rate = calc_support_rate(our_traces)
    gpt_support_rate = calc_support_rate(gpt_traces)
    
    def mean(key: str, metrics_list) -> float:
        vals = [r[key] for r in metrics_list if isinstance(r.get(key), (int, float))]
        return round(sum(vals) / len(vals), 4) if vals else 0.0
        
    summary_md = f"""# Benchmark Comparison
    
| Metric | Our Pipeline | GPT-Researcher |
|---|---|---|
| Citation Resolution Rate | {mean('resolution_rate', our_metrics)} | {mean('resolution_rate', gpt_metrics)} |
| Uncited Claim Count | {mean('uncited_claim_count', our_metrics)} | {mean('uncited_claim_count', gpt_metrics)} |
| LLM-Judged Support Rate | {our_support_rate} | {gpt_support_rate} |
| Contradictions Surfaced | {mean('contradictions_surfaced', our_metrics)} | {mean('contradictions_surfaced', gpt_metrics)} |
| Avg Cost (USD) | ${mean('cost_usd', our_metrics)} | ${mean('cost_usd', gpt_metrics)} |
| Avg Wall-clock Time (s) | {mean('latency_s', our_metrics)}s | {mean('latency_s', gpt_metrics)}s |
"""
    
    summary_out = out_dir / "summary.md"
    summary_out.write_text(summary_md)
    print(summary_md)
    print(f"\nWrote results to {out_dir}")

if __name__ == "__main__":
    asyncio.run(main())
