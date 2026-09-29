"""A tool call with off-schema arguments is the tool's to reject, never the node's to crash on.

The defect this pins: small local models ask for several pages in one call by passing a list
as `read_webpage`'s `url`. The executor's page cache normalised the url *before* the tool saw
it, and `.strip()` on a list raised out of `_research_one`. That failed the node, and with it
the run, recorded as "'list' object has no attribute 'strip'" — a reason that names nothing
that failed. The tool's own schema rejects the same call as a validation error. The executor
already turns that into an observation the model can read and correct on its next turn.

The real `read_webpage` is kept here, not a stand-in: its validation is the behaviour under
test. It rejects these shapes before any network I/O.
"""

from __future__ import annotations

import time

import pytest
from langchain_core.messages import AIMessage

from research_engine import graph as graph_mod
from research_engine.events import reset_emitter, set_emitter
from research_engine.runconfig import RunConfig, reset_run_config, set_run_config


class _Scripted:
    """A model that makes the given tool calls, one turn each, then stops."""

    def __init__(self, turns: list[AIMessage]):
        self.turns = list(turns)

    def bind_tools(self, tools, tool_choice=None):
        return self

    async def ainvoke(self, messages):
        return self.turns.pop(0) if self.turns else AIMessage(content="done", tool_calls=[])


def _state() -> dict:
    return {
        "session_id": "tool-arguments-test",
        "tasks": [{"id": 1, "query": "What are emergent abilities in large language models?"}],
        "evidence": [],
        "verdicts": {},
        "retries": {},
        "research_round": 0,
        "cost_usd": 0.0,
        "tokens_input": 0,
        "tokens_output": 0,
        "started_at": time.time(),
    }


@pytest.mark.parametrize(
    "url",
    [["https://a.example/1", "https://a.example/2"], 42, {"href": "https://a.example/1"}],
    ids=["list", "int", "dict"],
)
async def test_an_off_schema_read_webpage_url_becomes_an_observation(url, monkeypatch):
    turn = AIMessage(
        content="", tool_calls=[{"name": "read_webpage", "args": {"url": url}, "id": "bad-1"}]
    )
    monkeypatch.setattr(graph_mod, "get_llm", lambda role: _Scripted([turn, turn]))
    events: list[dict] = []

    async def collect(_sid, event):
        events.append(event)

    config = set_run_config(RunConfig(llm_mode="real"))
    emitter = set_emitter(collect)
    try:
        await graph_mod.executor_node(_state())
    finally:
        reset_emitter(emitter)
        reset_run_config(config)

    observations = [
        (e.get("detail") or {}).get("observation")
        for e in events
        if (e.get("detail") or {}).get("tool") == "read_webpage"
    ]
    # Twice: the repeat is not mistaken for a page already read, since nothing was.
    assert len(observations) == 2
    assert all(o.startswith("tool error") and "read_webpage" in o for o in observations), (
        observations
    )
