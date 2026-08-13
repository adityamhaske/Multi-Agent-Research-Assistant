"""
Contradiction-detection eval (docs/12 M11 DoD).

Runs the curated fixture set (evals/contradictions.json) through the REAL detector
path — `graph.contradiction_detector_node`, including its structured parse and URL
validation — and scores it against ground truth:

    recall        = detected / known-contradictory cases   (bar: >= 0.80)
    false-positive = flagged / known-consistent controls    (bar: <= 0.10)

Same boot contract as the harness: fake by default (plumbing smoke), real only when
LLM_MODE=real is set explicitly, so measuring never spends money by accident.

    LLM_MODE=real GOOGLE_API_KEY=… python -m evals.contradiction_eval
    LLM_MODE=real python -m evals.contradiction_eval      # Ollama routing from .env
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from research_engine.graph import contradiction_detector_node
from research_engine.local import load_env_file, run_config_from_env
from research_engine.runconfig import set_process_default

# Mode from the real environment BEFORE .env loads — same ordering as the harness:
# spending is opt-in per invocation, never inherited from a developer .env.
LLM_MODE = os.environ.get("LLM_MODE", "fake")
load_env_file()
RUN_CONFIG = run_config_from_env(fake=LLM_MODE != "real")
set_process_default(RUN_CONFIG)

EVALS_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVALS_DIR / "results"

MIN_RECALL = 0.80
MAX_FALSE_POSITIVE = 0.10


def evidence_for(case: dict) -> list[dict]:
    """Fixture case → evidence rows shaped like the executor's output."""
    rows = []
    for source in case["sources"]:
        for snippet in source["snippets"]:
            rows.append(
                {
                    "task_id": 1,
                    "source_url": source["url"],
                    "source_title": source["url"],
                    "snippet": snippet,
                }
            )
    return rows


async def run_case(case: dict) -> dict:
    state = {
        "session_id": case["id"],
        "original_query": case.get("topic", ""),
        "evidence": evidence_for(case),
        "cost_usd": 0.0,
        "tokens_input": 0,
        "tokens_output": 0,
    }
    started = time.time()
    try:
        out = await contradiction_detector_node(state)
        found = out.get("contradictions") or []
        error = None
    except Exception as e:  # noqa: BLE001 — a case that errors is scored, not fatal
        found, error = [], str(e)[:300]
    return {
        "id": case["id"],
        "expect": case["expect"],
        "detected": len(found) > 0,
        "pairs": len(found),
        "error": error,
        "latency_s": round(time.time() - started, 2),
    }


async def main() -> None:
    fixture = json.loads((EVALS_DIR / "contradictions.json").read_text())
    cases = fixture["cases"]
    results = [await run_case(c) for c in cases]

    contradictory = [r for r in results if r["expect"] == "contradiction"]
    consistent = [r for r in results if r["expect"] == "consistent"]
    recall = (
        round(sum(r["detected"] for r in contradictory) / len(contradictory), 4)
        if contradictory
        else None
    )
    fp_rate = (
        round(sum(r["detected"] for r in consistent) / len(consistent), 4)
        if consistent
        else None
    )
    summary = {
        "metric": "contradiction_detection",
        "mode": LLM_MODE,
        "model": dict(RUN_CONFIG.models),
        "recall": recall,
        "false_positive_rate": fp_rate,
        "min_recall": MIN_RECALL,
        "max_false_positive": MAX_FALSE_POSITIVE,
        "recall_ok": None if recall is None else recall >= MIN_RECALL,
        "fp_ok": None if fp_rate is None else fp_rate <= MAX_FALSE_POSITIVE,
        "cases": results,
        "run_at": datetime.now(UTC).isoformat(),
    }

    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / f"contradictions_{datetime.now(UTC):%Y-%m-%d_%H%M%S}.json"
    out_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "cases"}, indent=2))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
