"""Gate G-5: what the §9 claim check costs a selected-files run (RFC V3.1 §14.1, §14.3).

Real Fast selection runs through the engine (`runner.run`, the same graph both hosts drive)
over the §17 documents: the G-6 set's 16 files, one per shipped format, plus the
selection-retrieval corpus, embedded with the shipped local embedder. Each run stops at the
review gate, as a run does before anyone approves it.

The run's grounding report records §9's own calls, tokens, cost and wall time apart from
the research's (`validation_cost`, AC-43). So each run measures itself **with §9** (its
totals) and **without it** (its totals less that share), with no product switch to turn §9
off. §14.3 forbids one.

Measured, as G-5 asks:
- p50 and p95 wall-clock time, with and without §9;
- checking calls and tokens per run;
- checking cost per selection size (1, 3, 10 and 50 files);
- failures from budget exhaustion at three limits;
- runs where checking repaired a unit, and where a repair then failed re-verification.

**On a custom route the cost is unmeasured, never `$0.00`.** `validate_pricing` skips
`custom` and `openrouter`, so their `estimate_cost` is 0.0 (AGENTS.md) and a cost limit never
trips there. The result then reports tokens and calls as the measured quantities, marks USD
unmeasured, and runs the three budget limits as input-token limits, `max_input_tokens`,
which do hold on such a route. The owner then sets X and L (§14.3) in tokens, or against a
price table they declare.

    python -m evals.checking_cost --questions 3 --write
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import tempfile
import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver

from research_engine.corpus import CorpusStore, ScopedCorpus
from research_engine.embeddings import LocalEmbeddings
from research_engine.runner import run as run_engine

EVALS = Path(__file__).resolve().parent
RESULTS = EVALS / "results"
CORPUS = [
    *sorted((EVALS / "datasets" / "grounding" / "v1" / "documents").iterdir()),
    *sorted((EVALS / "datasets" / "retrieval" / "corpus").glob("*.md")),
    *sorted((EVALS / "datasets" / "selection-retrieval" / "corpus").glob("*.md")),
    *sorted(
        p
        for p in (EVALS.parent / "tests" / "fixtures" / "formats").iterdir()
        if p.name != "goldens.json"
    ),
]
SIZES = (1, 3, 10, 50)
#: Questions any selection can answer, whatever its files hold, so a run measures checking
#: rather than a selection that happens to say nothing. The last asks for something no file
#: states, so checking has claims to reject and repair.
QUESTIONS = [
    "What do these documents report?",
    "Which figures in these documents rose, which fell, and by how much?",
    "What reasons do these documents give for the changes they describe?",
    "Summarise these documents, including what they say about costs in 2025.",
]


class Unmeasurable(RuntimeError):
    pass


def _priced(route: str) -> bool:
    return route.split(":", 1)[0] not in ("custom", "openrouter")


async def _store(root: Path) -> tuple[CorpusStore, list[str]]:
    embedder = LocalEmbeddings(
        os.environ.get("CORPUS_EMBEDDINGS_MODEL", "nomic-embed-text"),
        os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
    )
    store = CorpusStore(root / "corpus.sqlite", embedder)
    ids = []
    for path in CORPUS:
        ids.append((await store.ingest(path.name, path.read_bytes())).doc_id)
    return store, ids


async def one_run(store, ids: list[str], size: int, question: str, config, **limits) -> dict:
    allowed = frozenset(ids[:size])
    run_config = replace(
        config, corpus_mode=True, corpus_allowed_ids=allowed, skip_plan_gate=True, **limits
    )
    saver, thread = MemorySaver(), f"g5-{uuid.uuid4().hex[:8]}"
    started = time.monotonic()
    outcome = await run_engine(
        checkpointer=saver,
        session_id=thread,
        user_id="g5",
        query=question,
        depth="fast",
        run_config=run_config,
        corpus=ScopedCorpus(store, allowed),
    )
    wall = time.monotonic() - started
    state = (await saver.aget({"configurable": {"thread_id": thread}}) or {}).get(
        "channel_values", {}
    )
    report = state.get("grounding_report") or {}
    vc = report.get("validation_cost") or {}
    return {
        "size": size,
        "question": question,
        "limits": limits,
        "status": outcome.status,
        "error": outcome.error,
        "budget_failure": bool(outcome.error and "budget_" in outcome.error),
        "wall_seconds": round(wall, 3),
        "check_seconds": vc.get("seconds"),
        "tokens_in": outcome.tokens_input,
        "tokens_out": outcome.tokens_output,
        "cost_usd": outcome.cost_usd,
        "check_calls": vc.get("calls"),
        "check_tokens_in": vc.get("tokens_in"),
        "check_tokens_out": vc.get("tokens_out"),
        "check_cost_usd": vc.get("actual_usd"),
        "check_retries": vc.get("retries"),
        "units_repaired": report.get("units_repaired"),
        "units_dropped": report.get("units_dropped"),
        "grounding_status": report.get("status"),
    }


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[int(q) - 1]


def summarise(rows: list[dict], priced: bool) -> dict:
    measured = [r for r in rows if r["check_seconds"] is not None and not r["limits"]]
    with_check = [r["wall_seconds"] for r in measured]
    without = [r["wall_seconds"] - r["check_seconds"] for r in measured]
    by_size = {}
    for size in SIZES:
        rs = [r for r in measured if r["size"] == size]
        by_size[str(size)] = {
            "runs": len(rs),
            "check_calls_median": statistics.median([r["check_calls"] for r in rs]) if rs else None,
            "check_tokens_in_median": statistics.median([r["check_tokens_in"] for r in rs])
            if rs
            else None,
            "check_cost_usd_median": statistics.median([r["check_cost_usd"] for r in rs])
            if rs and priced
            else None,
        }
    budget = {}
    for r in rows:
        if r["limits"]:
            key = json.dumps(r["limits"], sort_keys=True)
            b = budget.setdefault(key, {"limits": r["limits"], "runs": 0, "budget_failures": 0})
            b["runs"] += 1
            b["budget_failures"] += int(r["budget_failure"])
    return {
        "cost_measured": priced,
        "latency_p50": {"with_check": _pct(with_check, 50), "without_check": _pct(without, 50)},
        "latency_p95": {"with_check": _pct(with_check, 95), "without_check": _pct(without, 95)},
        "p95_ratio": (_pct(with_check, 95) / _pct(without, 95))
        if with_check and _pct(without, 95)
        else None,
        "by_selection_size": by_size,
        "budget": list(budget.values()),
        "runs_with_a_repair": sum(1 for r in rows if (r["units_repaired"] or 0) > 0),
        # Retried checking calls (429s, timeouts, outages), apart from repairs: a provider
        # that throttles adds latency without adding a single rewrite.
        "check_retries_total": sum(r["check_retries"] or 0 for r in rows),
        "runs_with_a_retry": sum(1 for r in rows if (r["check_retries"] or 0) > 0),
        "runs_with_a_failed_reverification": sum(1 for r in rows if (r["units_dropped"] or 0) > 0),
    }


async def run(questions: int, token_limits: list[int], cost_limits: list[float]) -> dict:
    from research_engine.local import run_config_from_env

    config = run_config_from_env(fake=False)
    if config.llm_mode == "fake":
        raise Unmeasurable("LLM_MODE is fake: a scripted run's cost and time measure nothing")
    route = config.model_for("critic")
    priced = all(
        _priced(config.model_for(r)) for r in ("planner", "executor", "critic", "synthesizer")
    )
    rows = []
    with tempfile.TemporaryDirectory(prefix="g5-") as tmp:
        store, ids = await _store(Path(tmp))
        if len(ids) < max(SIZES):
            raise Unmeasurable(f"only {len(ids)} documents for a {max(SIZES)}-file selection")
        for size in SIZES:
            for q in QUESTIONS[:questions]:
                rows.append(await one_run(store, ids, size, q, config))
        limits = (
            [{"max_cost_per_session_usd": c} for c in cost_limits]
            if priced
            else [{"max_input_tokens": t} for t in token_limits]
        )
        for limit in limits:
            for size in (1, 3, 10):
                rows.append(await one_run(store, ids, size, QUESTIONS[0], config, **limit))
    return {
        "eval": "checking-cost",
        "gate": "G-5",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "routing": {
            r: config.model_for(r) for r in ("planner", "executor", "critic", "synthesizer")
        },
        "critic_routing": route,
        "documents": len(CORPUS),
        "summary": summarise(rows, priced),
        "runs": rows,
    }


def _slug(route: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in route).strip("-").lower() or "unknown"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--questions", type=int, default=3)
    parser.add_argument("--token-limits", default="60000,120000,240000")
    parser.add_argument("--cost-limits", default="0.05,0.10,0.25")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    try:
        result = await run(
            args.questions,
            [int(x) for x in args.token_limits.split(",")],
            [float(x) for x in args.cost_limits.split(",")],
        )
    except Unmeasurable as exc:
        print(f"UNMEASURED: {exc}")
        return 2
    print(json.dumps(result["summary"], indent=2))
    if args.write:
        n, stem = (
            1,
            f"eval-{datetime.now(UTC).date().isoformat()}-{_slug(result['critic_routing'])}-checking-cost",
        )
        while (RESULTS / f"{stem}-run{n}.json").exists():
            n += 1
        path = RESULTS / f"{stem}-run{n}.json"
        path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path.relative_to(RESULTS.parent.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
