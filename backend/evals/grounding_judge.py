"""The G-6 reference labels, made by an LLM judge (V3.1-scope-freeze.md, amendment A-1).

RFC §17 asked for a person to label the 425 claims. The owner decided on 2026-10-29 to label
them with an LLM judge instead: Claude Sonnet 4.5, served through OmniRoute's Kiro connection,
chosen on a 30-claim trial against Haiku 4.5 (see amendment A-1). G-6 therefore measures **agreement between the
shipped checker and that judge**, not accuracy against a person. Every result built on
these labels says so (`labels.json`'s `labeller` block, copied into the benchmark result).

What keeps the judge a reference rather than a second opinion of the checker:
- **Blind input.** It reads `items.json` alone, the claim and its snippets, exactly what a
  person saw on the labelling page. Neither `authoring.json` (what a claim was written to
  be) nor any checker verdict reaches it.
- **The person's rubric.** The labelling page's instructions are its system prompt, so the
  reference means what the human reference would have meant. Two clarifications follow
  them, added after a hand review of a first labelling found a judge rejecting claims that
  merely left a clause out and miscounting a product. The reason comes before the label,
  because three first-run labels contradicted their own reasons.
- **Not the system under test.** `grounding_benchmark` refuses a run where the checker's
  route is the judge's. What actually answered is recorded from OmniRoute's routing headers
  (`evals/harness.py::gateway_routing`), never assumed from the route.
- **Unlabelled stays unlabelled.** A reply that names no label, after one retry, leaves the
  claim without a reference. The benchmark then refuses until it is labelled, so a
  judge's failure can never become a label.

    python -m evals.grounding_judge                   # every claim, on custom:kiro/claude-sonnet-4.5
    python -m evals.grounding_judge --only-missing    # re-ask only the claims still unlabelled
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from evals.harness import gateway_routing
from research_engine.runconfig import reset_run_config, set_run_config

SET = Path(__file__).resolve().parent / "datasets" / "grounding" / "v1"
DEFAULT_ROUTE = "custom:kiro/claude-sonnet-4.5"
LABELS = ("supported", "not_supported", "contradicted")
DECISION = (
    'owner, 2026-10-29: "use haiku 5.5 to do this, use LLM as judge"; no Haiku 5.5 route '
    'answered, then "Use Kiro Haiku 4.5", then "use any cheap and best model"'
)

#: The labelling page's instructions (G-6 Claim Labels), word for word, plus the answer form.
RUBRIC = """You label one claim against the snippets it cites. Judge from the snippets alone, \
not from what is probably true.

Supported: every part of the claim is stated by the snippets, by one alone or by several \
together. Simple arithmetic on stated figures, a unit conversion, or approximate wording \
("about", "nearly") that fairly describes a stated figure counts as stated.

Not supported: some part is not stated: a different subject or period, a cause or reason the \
snippets do not give, an extra clause, a description in brackets, or a figure that no snippet \
gives.

Contradicted: the snippets state something incompatible with the claim about the same thing: \
a different figure for the same measure, or the opposite direction.

Spreadsheet rows read "Row 2 — Column: value; …", the way the app extracts them.

Two clarifications of the above:
- A claim may leave out part of what a snippet says and still be supported. Judge only what \
the claim asserts.
- Check every figure, and any arithmetic the claim relies on, against the snippets before \
deciding.

Answer in exactly two lines, the reason first:
REASON: one sentence naming the part of the claim that decides it.
LABEL: supported | not_supported | contradicted"""

RUBRIC_SHA256 = hashlib.sha256(RUBRIC.encode("utf-8")).hexdigest()
_LABEL = re.compile(r"^\s*LABEL:\s*(supported|not_supported|contradicted)\s*$", re.I | re.M)
_REASON = re.compile(r"^\s*REASON:\s*(.+)$", re.I | re.M)


def _judge_llm(route: str):
    """The judge through the engine's own factory, with gateway headers kept (as the
    harness's judge is built), so what served each call can be read off the response."""
    from research_engine import llm_factory
    from research_engine.local import run_config_from_env

    base = run_config_from_env(fake=False)
    token = set_run_config(replace(base, models={**base.models, "critic": route}))
    try:
        llm = llm_factory.get_llm("critic")
    finally:
        reset_run_config(token)
    if "include_response_headers" in getattr(type(llm), "model_fields", {}):
        llm.include_response_headers = True
    return llm


def prompt(item: dict) -> str:
    snippets = "\n".join(
        f"[{n}] ({s['document']}, {s['kind']}) {s['text']}"
        for n, s in enumerate(item["snippets"], start=1)
    )
    return f"Claim: {item['claim']}\n\nCited snippets:\n{snippets}"


async def label_one(llm, item: dict) -> dict:
    from langchain_core.messages import HumanMessage, SystemMessage

    from research_engine.llm_factory import served_model_id

    messages = [SystemMessage(content=RUBRIC), HumanMessage(content=prompt(item))]
    last_error = None
    for _attempt in range(2):
        try:
            resp = await llm.ainvoke(messages)
        except Exception as exc:  # noqa: BLE001 — recorded, and the claim stays unlabelled
            last_error = f"{type(exc).__name__}: {exc}"
            await asyncio.sleep(5)
            continue
        text = resp.content if isinstance(resp.content, str) else ""
        found = _LABEL.search(text)
        if found:
            reason = _REASON.search(text)
            return {
                "label": found.group(1).lower(),
                "reason": reason.group(1).strip() if reason else None,
                "served_model": served_model_id(resp),
                "routing": gateway_routing(resp),
            }
        last_error = f"no LABEL line in the reply: {text[:200]!r}"
    return {"label": None, "error": last_error}


async def run(route: str, only_missing: bool, concurrency: int) -> dict:
    items = json.loads((SET / "items.json").read_text(encoding="utf-8"))["items"]
    previous = {}
    if only_missing and (SET / "judge-reasons.json").exists():
        previous = json.loads((SET / "judge-reasons.json").read_text(encoding="utf-8"))
    todo = [i for i in items if not (previous.get(i["id"]) or {}).get("label")]

    llm = _judge_llm(route)
    gate = asyncio.Semaphore(concurrency)
    done = 0

    async def one(item):
        nonlocal done
        async with gate:
            result = await label_one(llm, item)
        done += 1
        if done % 25 == 0:
            print(f"  {done}/{len(todo)} labelled")
        return item["id"], result

    results = dict(previous)
    results.update(dict(await asyncio.gather(*(one(i) for i in todo))))

    labels = {k: v["label"] for k, v in results.items() if v.get("label")}
    served = sorted({v["served_model"] for v in results.values() if v.get("served_model")})
    providers = sorted(
        {(v.get("routing") or {}).get("provider") for v in results.values()} - {None}
    )
    record = {
        "set_version": 1,
        "labeller": {
            "kind": "llm_judge",
            "route": route,
            "served_models": served,
            "served_providers": providers,
            "rubric_sha256": RUBRIC_SHA256,
            "decided_by": DECISION,
            "amendment": "internal/rfcs/V3.1-scope-freeze.md, A-1",
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        },
        "labels": dict(sorted(labels.items())),
        "unlabelled": sorted(i["id"] for i in items if i["id"] not in labels),
    }
    (SET / "labels.json").write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    (SET / "judge-reasons.json").write_text(
        json.dumps(dict(sorted(results.items())), indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--route", default=DEFAULT_ROUTE)
    parser.add_argument("--only-missing", action="store_true")
    parser.add_argument("--concurrency", type=int, default=2)
    args = parser.parse_args()
    record = asyncio.run(run(args.route, args.only_missing, args.concurrency))
    counts = {lab: list(record["labels"].values()).count(lab) for lab in LABELS}
    print(f"labelled {len(record['labels'])}, unlabelled {len(record['unlabelled'])}: {counts}")
    print(f"served by {record['labeller']['served_models'] or 'no model reported'}")
    return 0 if not record["unlabelled"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
