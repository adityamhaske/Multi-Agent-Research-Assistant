"""Gate G-6: the shipped claim checker against a person's labels (RFC V3.1 §17, D-23, D-24).

Each claim in `datasets/grounding/v1/items.json` goes through `grounding.validate`, the
function a selected-files run calls: decomposition into atomic claims, the mechanical
number check, the three-way verdict, and the per-citation relevance pass. Each claim is a
one-sentence draft citing its snippets as `[1]`/`[1, 2]`. A claim's verdict is
**contradicted** if any atomic claim is, **unmeasured** if any is, **supported** only if all
are, and otherwise **not supported**. That verdict is scored against `labels.json`, which a
person made on the labelling page without seeing any verdict.

Measured, as §17 defines them:
- the 3×3 confusion matrix, rows the person's label, columns the checker's verdict;
- **false-accept**: of the claims the person labelled `not_supported` or `contradicted`, the
  share the checker called supported, with the upper bound of its 95% Wilson interval;
- **false-reject**: of the claims labelled `supported`, the share it did not call supported;
- `contradicted` recall;
- the unmeasured share, reported apart and outside every denominator above.

Thresholds (D-23): false-accept ≤ 2% with a Wilson upper bound ≤ 5%, false-reject ≤ 15%,
unmeasured ≤ 5%. Above 5% unmeasured, the run is **invalid**: it is re-run, never reported
as a result. A routing that misses is labelled below threshold, not blocked (D-24); the
default routing must meet the threshold for 3.1.0 to ship.

    python -m evals.grounding_benchmark            # every claim, on the routing in the env
    python -m evals.grounding_benchmark --limit 20 # a preflight; never written
    python -m evals.grounding_benchmark --write    # record a write-once result

Real models only: under `LLM_MODE=fake` the verdicts are scripted, and scoring them would
measure the script.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from datetime import UTC, datetime
from pathlib import Path

from research_engine import grounding
from research_engine.runconfig import get_run_config, reset_run_config, set_run_config

SET = Path(__file__).resolve().parent / "datasets" / "grounding" / "v1"
RESULTS = Path(__file__).resolve().parent / "results"
LABELS = ("supported", "not_supported", "contradicted")
VERDICTS = (*LABELS, "unmeasured")
THRESHOLDS = {"false_accept": 0.02, "false_accept_wilson_upper": 0.05,
              "false_reject": 0.15, "unmeasured": 0.05}  # fmt: skip
QUESTION = "What do the cited documents say?"


#: Who made the reference labels, from `labels.json`. Since amendment A-1 (2026-10-29) an LLM
#: judge, which makes G-6 agreement with that judge rather than accuracy against a person.
LABELLER: dict = {}


class Unmeasurable(RuntimeError):
    """No honest measurement is possible. Never turned into a number."""


def load_items() -> list[dict]:
    return json.loads((SET / "items.json").read_text(encoding="utf-8"))["items"]


def load() -> tuple[list[dict], dict[str, str]]:
    items = load_items()
    path = SET / "labels.json"
    if not path.exists():
        raise Unmeasurable("no labels.json: the reference labels have not been made yet")
    record = json.loads(path.read_text(encoding="utf-8"))
    labels = record["labels"]
    global LABELLER
    LABELLER = record.get("labeller") or {"kind": "person"}
    missing = [i["id"] for i in items if i["id"] not in labels]
    if missing:
        raise Unmeasurable(f"{len(missing)} claims have no reference label, e.g. {missing[:5]}")
    bad = {k: v for k, v in labels.items() if v not in LABELS}
    if bad:
        raise Unmeasurable(f"labels outside {LABELS}: {dict(list(bad.items())[:5])}")
    return items, labels


def as_draft(item: dict) -> tuple[str, list[dict]]:
    """The claim as a one-sentence report citing every snippet it was given."""
    marks = ", ".join(str(n) for n in range(1, len(item["snippets"]) + 1))
    draft = f"{item['claim'].rstrip('.')} [{marks}].\n"
    sources = [
        {
            "index": n,
            "url": f"corpus://g6-{item['id']}-{n}#chars=0-{len(s['text'])}",
            "snippets": [s["text"]],
        }  # fmt: skip
        for n, s in enumerate(item["snippets"], start=1)
    ]
    return draft, sources


def claim_verdict(validation) -> tuple[str, list[dict]]:
    states = [c.state for c in validation.claims]
    if validation.unparsed_lines or not states:
        return "unmeasured", []
    detail = [{"text": c.text, "state": c.state, "cause": c.cause} for c in validation.claims]
    if grounding.CONTRADICTED in states:
        return "contradicted", detail
    if grounding.UNMEASURED in states:
        return "unmeasured", detail
    if all(s == grounding.SUPPORTED for s in states):
        return "supported", detail
    return "not_supported", detail


async def judge(item: dict) -> dict:
    draft, sources = as_draft(item)
    budget = grounding.Budget(spent_usd=0.0, tokens_in=0, started_at=None)
    validation = await grounding.validate(
        draft, sources, question=QUESTION, admissible=lambda _url: True, budget=budget
    )
    verdict, atomic = claim_verdict(validation)
    return {
        "id": item["id"],
        "verdict": verdict,
        "atomic": atomic,
        "calls": validation.calls,
        "tokens_in": validation.tokens_in,
        "tokens_out": validation.tokens_out,
    }


def wilson_upper(k: int, n: int, z: float = 1.96) -> float | None:
    if n == 0:
        return None
    p = k / n
    centre = p + z * z / (2 * n)
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre + spread) / (1 + z * z / n)


def score(rows: list[dict], labels: dict[str, str]) -> dict:
    matrix = {lab: {v: 0 for v in VERDICTS} for lab in LABELS}
    for r in rows:
        matrix[labels[r["id"]]][r["verdict"]] += 1
    measured = [r for r in rows if r["verdict"] != "unmeasured"]
    negatives = [r for r in measured if labels[r["id"]] != "supported"]
    positives = [r for r in measured if labels[r["id"]] == "supported"]
    contradicted = [r for r in measured if labels[r["id"]] == "contradicted"]
    fa = sum(r["verdict"] == "supported" for r in negatives)
    fr = sum(r["verdict"] != "supported" for r in positives)

    def share(k, n):
        return k / n if n else None

    out = {
        "claims": len(rows),
        "unmeasured": sum(r["verdict"] == "unmeasured" for r in rows),
        "unmeasured_share": share(len(rows) - len(measured), len(rows)),
        "confusion": matrix,
        "false_accept": share(fa, len(negatives)),
        "false_accept_counts": {"accepted": fa, "negatives_measured": len(negatives)},
        "false_accept_wilson_upper": wilson_upper(fa, len(negatives)),
        "false_reject": share(fr, len(positives)),
        "false_reject_counts": {"rejected": fr, "positives_measured": len(positives)},
        "contradicted_recall": share(
            sum(r["verdict"] == "contradicted" for r in contradicted), len(contradicted)
        ),
    }
    if out["unmeasured_share"] is not None and out["unmeasured_share"] > THRESHOLDS["unmeasured"]:
        out["status"] = "invalid"
        out["meets_threshold"] = None
        return out
    checks = {
        "false_accept": out["false_accept"] is not None
        and out["false_accept"] <= THRESHOLDS["false_accept"],
        "false_accept_wilson_upper": out["false_accept_wilson_upper"] is not None
        and out["false_accept_wilson_upper"] <= THRESHOLDS["false_accept_wilson_upper"],
        "false_reject": out["false_reject"] is not None
        and out["false_reject"] <= THRESHOLDS["false_reject"],
    }
    out["status"] = "measured"
    out["threshold_checks"] = checks
    out["meets_threshold"] = all(checks.values())
    return out


def _slug(route: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in route).strip("-").lower() or "unknown"


async def run(limit: int | None = None) -> dict:
    from research_engine.local import run_config_from_env

    items, labels = load()
    config = run_config_from_env(fake=False)
    if config.llm_mode == "fake":
        raise Unmeasurable("LLM_MODE is fake: scripted verdicts would measure the script")
    if LABELLER.get("route") and LABELLER["route"] == config.model_for("critic"):
        raise Unmeasurable(
            f"the checker runs on {LABELLER['route']}, the model that made the reference "
            "labels: a checker scored against itself is not evidence"
        )
    token = set_run_config(config)
    try:
        chosen = items[:limit] if limit else items
        rows = []
        for item in chosen:  # one at a time: OmniRoute's providers throttle bursts
            rows.append(await judge(item))
        route = get_run_config().model_for("critic")
    finally:
        reset_run_config(token)
    return {
        "eval": "grounding-benchmark",
        "gate": "G-6",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "set_version": 1,
        "critic_routing": route,
        # A router alias resolves differently per call (AGENTS.md); this names what was
        # asked for, and says so, rather than presenting it as a pinned model.
        "routing_is_alias": "/auto" in route or ":auto/" in route,
        "preflight": bool(limit),
        "reference_labels": LABELLER,
        "thresholds": THRESHOLDS,
        "result": score(rows, labels),
        "calls": sum(r["calls"] for r in rows),
        "tokens_in": sum(r["tokens_in"] for r in rows),
        "tokens_out": sum(r["tokens_out"] for r in rows),
        "claims": rows,
    }


def _result_path(run_date: str, route: str) -> Path:
    n = 1
    while True:
        path = RESULTS / f"eval-{run_date}-{_slug(route)}-grounding-run{n}.json"
        if not path.exists():
            return path
        n += 1


def _pct(v):
    return "n/a (unmeasured)" if v is None else f"{100 * v:.1f}%"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--limit", type=int, help="a preflight over the first N claims")
    parser.add_argument("--write", action="store_true", help="record a write-once result")
    args = parser.parse_args()
    if args.write and args.limit:
        parser.error("a preflight is never recorded as a result")
    try:
        result = await run(args.limit)
    except Unmeasurable as exc:
        print(f"UNMEASURED: {exc}")
        return 2
    r = result["result"]
    print(f"critic routing     {result['critic_routing']}"
          + ("  (router alias)" if result["routing_is_alias"] else ""))  # fmt: skip
    print(
        f"claims             {r['claims']}  unmeasured {r['unmeasured']} ({_pct(r['unmeasured_share'])})"
    )
    print(f"status             {r['status']}")
    print(
        f"false-accept       {_pct(r['false_accept'])}  Wilson upper {_pct(r['false_accept_wilson_upper'])}"
    )
    print(f"false-reject       {_pct(r['false_reject'])}")
    print(f"contradicted recall {_pct(r['contradicted_recall'])}")
    print(f"meets threshold    {r.get('meets_threshold')}")
    if args.write:
        path = _result_path(datetime.now(UTC).date().isoformat(), result["critic_routing"])
        path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path.relative_to(RESULTS.parent.parent)}")
    return 0 if r["status"] == "measured" else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
