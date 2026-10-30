"""
The G-6 LLM judge (`evals/grounding_judge.py`, amendment A-1) labels blind and never invents
a label, and the benchmark refuses to score the checker against itself.
"""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage

from evals import grounding_benchmark as gb
from evals import grounding_judge as gj

ITEMS = json.loads((gj.SET / "items.json").read_text(encoding="utf-8"))["items"]


class _Scripted:
    def __init__(self, replies):
        self.replies, self.seen = list(replies), []

    async def ainvoke(self, messages):
        self.seen.append(messages)
        return AIMessage(content=self.replies.pop(0))


def test_the_judge_sees_the_claim_and_snippets_and_nothing_else():
    item = ITEMS[0]
    text = gj.prompt(item)
    assert item["claim"] in text
    assert all(s["text"] in text for s in item["snippets"])
    authoring = json.loads((gj.SET / "authoring.json").read_text(encoding="utf-8"))[item["id"]]
    assert authoring["category"] not in text and "written_as" not in text


async def test_a_reply_without_a_label_is_retried_then_left_unlabelled(monkeypatch):
    monkeypatch.setattr(gj.asyncio, "sleep", lambda _s: _noop())
    llm = _Scripted(["I think it is fine.", "Probably supported."])
    result = await gj.label_one(llm, ITEMS[0])
    assert result["label"] is None and "no LABEL line" in result["error"]
    assert len(llm.seen) == 2


async def test_a_well_formed_reply_is_parsed():
    llm = _Scripted(["LABEL: contradicted\nREASON: the snippet gives 6.1%, not 16.1%."])
    result = await gj.label_one(llm, ITEMS[0])
    assert result["label"] == "contradicted"
    assert result["reason"].startswith("the snippet gives")


async def _noop():
    return None


def test_the_benchmark_refuses_a_checker_that_made_the_labels(tmp_path, monkeypatch):
    monkeypatch.setattr(gb, "SET", tmp_path)
    (tmp_path / "items.json").write_text(json.dumps({"items": ITEMS[:1]}), encoding="utf-8")
    (tmp_path / "labels.json").write_text(
        json.dumps(
            {
                "labels": {ITEMS[0]["id"]: "supported"},
                "labeller": {"kind": "llm_judge", "route": "custom:auto/best-fast"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LLM_MODE", "real")
    monkeypatch.setenv("MODEL_CRITIC", "custom:auto/best-fast")
    # The other agents' default routes need a key to build a config at all; the refusal
    # fires before any call, so a placeholder is never sent anywhere.
    monkeypatch.setenv("GOOGLE_API_KEY", "placeholder")
    monkeypatch.setenv("CUSTOM_API_KEY", "placeholder")
    with pytest.raises(gb.Unmeasurable, match="scored against itself"):
        import asyncio

        asyncio.run(gb.run())
