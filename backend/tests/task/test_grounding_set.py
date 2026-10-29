"""
The G-6 grounding set is what RFC V3.1 §17 says it must be (`evals/grounding_set.py`).

- Every snippet is a line the **shipped** extractor produces from the committed document, so
  the claims are judged against real extracted text, not against the prose they began as.
- It has at least 400 claims, a hard-negative share of at least 40%, and enough negatives
  (250) for a 2% false-accept rate to clear its Wilson bound.
- It covers every kind the format registry accepts, Tier A, B and C plus PDF.
- **It is blind.** `items.json`, the only file the labelling page reads, carries no label and
  no category. What each claim was written as lives in `authoring.json`.
"""

from __future__ import annotations

import json
from pathlib import Path

from research_engine.documents import FORMATS, extract

SET = Path(__file__).resolve().parents[2] / "evals" / "datasets" / "grounding" / "v1"
ITEMS = json.loads((SET / "items.json").read_text(encoding="utf-8"))["items"]
AUTHORING = json.loads((SET / "authoring.json").read_text(encoding="utf-8"))


def test_every_snippet_is_a_line_the_shipped_extractor_produces():
    extracted = {
        p.name: extract(p.name, p.read_bytes()).text for p in (SET / "documents").iterdir()
    }
    for item in ITEMS:
        for snippet in item["snippets"]:
            lines = {ln.strip() for ln in extracted[snippet["document"]].splitlines()}
            assert snippet["text"] in lines, (item["id"], snippet["document"])


def test_the_set_meets_the_section_17_floors():
    written = [a["written_as"] for a in AUTHORING.values()]
    negatives = sum(label != "supported" for label in written)
    assert len(ITEMS) >= 400
    assert negatives / len(ITEMS) >= 0.40
    assert negatives >= 250, "at fewer, a 2% false-accept rate cannot clear its 5% Wilson bound"
    assert {"supported", "not_supported", "contradicted"} <= set(written)


def test_every_shipped_kind_is_represented():
    kinds = {s["kind"] for item in ITEMS for s in item["snippets"]}
    assert {f.kind for f in FORMATS.values()} <= kinds


def test_the_labelling_input_is_blind():
    assert {item["id"] for item in ITEMS} == set(AUTHORING)
    for item in ITEMS:
        assert set(item) == {"id", "claim", "snippets"}, item["id"]
        for snippet in item["snippets"]:
            assert set(snippet) == {"document", "kind", "mode", "text"}
