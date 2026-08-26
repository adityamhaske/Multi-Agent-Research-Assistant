"""The executor must not depend on a model *volunteering* `submit_evidence`.

The scar this pins (run `96a16137`, 2026-08-25): a real run routed to an OpenAI-compatible
gateway searched the web successfully — DuckDuckGo returned ten hits per query and seven
pages fetched 200 OK — and then produced **zero** evidence, twice, and the run failed.

Nothing was broken in retrieval. `_research_one` handed the model `web_search`,
`read_webpage`, `calculate` and `submit_evidence` and *hoped* it would choose to stop
searching and submit. It never did: it burned all `_MAX_TOOL_ROUNDS` issuing more searches,
the loop fell out of the bottom with `evidence == []`, and the only trace was
"Gathered 0 source(s)". Reproduced deterministically against that gateway, whose router
alias resolved to a different model on nearly every call.

Two properties follow, and neither is visible from a passing golden journey, because the
scripted fake executor submits evidence on the first turn every time:

1. **The engine asks directly when the model does not offer.** Text we actually fetched is
   not allowed to evaporate because a model preferred to keep searching.
2. **A rejected `submit_evidence` is reported.** That branch swallowed the validation error
   into a tool observation and emitted nothing, so a model calling the tool with bad
   arguments on every round was indistinguishable from one never calling it at all —
   the "never swallow" rule in AGENTS.md, in the one place it most costs a run.

Fabrication protection is unchanged and deliberately re-asserted here: the forced pass is
handed only `seen_text`, and `verify_evidence_snippets` still runs over its output, so this
cannot become a route by which a model's memory reaches a citation.
"""

from __future__ import annotations

import time

import pytest
from langchain_core.messages import AIMessage

from research_engine import graph as graph_mod
from research_engine.runconfig import RunConfig, reset_run_config, set_run_config

PAGE = (
    "Emergent abilities of large language models are abilities that are not present in "
    "smaller models but are present in larger models."
)
URL = "https://arxiv.org/abs/2206.07682"
TASK = {"id": 1, "query": "What are emergent abilities in large language models?"}


class _FakeBound:
    """One `bind_tools(...)` result: replays a scripted turn per `ainvoke`."""

    def __init__(self, owner: _FakeLLM, tool_choice):
        self.owner = owner
        self.tool_choice = tool_choice

    async def ainvoke(self, messages):
        self.owner.calls.append(self.tool_choice)
        if self.tool_choice is not None:
            # The forced pass. Quote the page verbatim so verification passes.
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "submit_evidence",
                        "args": {
                            "evidence": [
                                {
                                    "source_url": URL,
                                    "source_title": "Emergence",
                                    "snippet": PAGE,
                                    "key_fact": "Emergent abilities appear only in larger models.",
                                }
                            ]
                        },
                        "id": "forced-1",
                    }
                ],
            )
        return self.owner.next_unforced()


class _FakeLLM:
    def __init__(self, turns):
        self.turns = list(turns)
        self.calls: list = []

    def bind_tools(self, tools, tool_choice=None):
        return _FakeBound(self, tool_choice)

    def next_unforced(self) -> AIMessage:
        return self.turns.pop(0) if self.turns else AIMessage(content="done", tool_calls=[])


def _search_turn(query: str, call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": "web_search", "args": {"query": query}, "id": call_id}],
    )


def _read_turn(url: str, call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": "read_webpage", "args": {"url": url}, "id": call_id}],
    )


def _install(monkeypatch, llm: _FakeLLM) -> None:
    monkeypatch.setattr(graph_mod, "get_llm", lambda role: llm)

    async def fake_read(args):
        return {"url": args["url"], "text": PAGE, "error": None}

    async def fake_search(args):
        # The full sentence, so a quotation of it is text the executor genuinely saw. A
        # shorter hit would be blanked by `verify_evidence_snippets` — correctly, and it
        # would be testing that guard rather than this one.
        return [{"title": "Emergence", "url": URL, "snippet": PAGE}]

    class _Tool:
        def __init__(self, fn):
            self.ainvoke = fn

    monkeypatch.setattr(
        graph_mod,
        "_TOOLS_BY_NAME",
        {"read_webpage": _Tool(fake_read), "web_search": _Tool(fake_search)},
    )


def _state() -> dict:
    return {
        "session_id": "forced-submit-test",
        "tasks": [TASK],
        "evidence": [],
        "verdicts": {},
        "retries": {},
        "cost_usd": 0.0,
        "tokens_input": 0,
        "tokens_output": 0,
        "started_at": time.time(),
    }


async def _research(monkeypatch, llm: _FakeLLM, **cfg_overrides):
    _install(monkeypatch, llm)
    token = set_run_config(RunConfig(llm_mode="real", **cfg_overrides))
    try:
        guard = graph_mod._BudgetGuard(0.0, 0.0)
        return await graph_mod._research_one(_state(), TASK, guard)
    finally:
        reset_run_config(token)


# ── 1. The engine asks directly when the model never offers ────────────────────────


@pytest.mark.asyncio
async def test_a_model_that_only_ever_searches_still_yields_evidence(monkeypatch):
    """The exact reproduction: every turn is another search, forever.

    Before the fix this returned `{"evidence": []}` and the run failed with a message
    telling the user to check their search provider — which was working perfectly.
    """
    llm = _FakeLLM([_search_turn(f"query {i}", f"s{i}") for i in range(20)])

    out = await _research(monkeypatch, llm)

    assert out["evidence"], "text we actually fetched must not evaporate"
    assert out["evidence"][0]["source_url"] == URL
    assert out["evidence"][0]["snippet"] == PAGE, "the verbatim quote must survive"
    assert any(c is not None for c in llm.calls), "the forced pass must be a forced call"


@pytest.mark.asyncio
async def test_the_forced_pass_is_skipped_when_the_model_submits_on_its_own(monkeypatch):
    """A well-behaved model must cost exactly what it did before — no extra call."""
    llm = _FakeLLM(
        [
            _read_turn(URL, "r1"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "submit_evidence",
                        "args": {
                            "evidence": [
                                {
                                    "source_url": URL,
                                    "source_title": "Emergence",
                                    "snippet": PAGE,
                                    "key_fact": "k",
                                }
                            ]
                        },
                        "id": "own-1",
                    }
                ],
            ),
        ]
    )

    out = await _research(monkeypatch, llm)

    assert len(out["evidence"]) == 1
    assert all(c is None for c in llm.calls), "no forced call may be made when one is not needed"


@pytest.mark.asyncio
async def test_nothing_fetched_means_nothing_invented(monkeypatch):
    """The negative control, and the whole reason the forced pass reads `seen_text`.

    A task whose tools returned nothing has no text to quote. The forced pass must not run
    at all — asking a model for evidence with no sources in hand is asking it to make some
    up, which is the failure this product exists to prevent.
    """
    llm = _FakeLLM([AIMessage(content="I have no idea where to look.", tool_calls=[])])

    out = await _research(monkeypatch, llm)

    assert out["evidence"] == []
    assert all(c is None for c in llm.calls), "no forced call without fetched text"


@pytest.mark.asyncio
async def test_a_forced_snippet_that_was_never_fetched_is_still_blanked(monkeypatch):
    """The forced pass is not a bypass of `verify_evidence_snippets`."""

    class _Fabricator(_FakeLLM):
        def bind_tools(self, tools, tool_choice=None):
            bound = _FakeBound(self, tool_choice)
            if tool_choice is not None:
                original = bound.ainvoke

                async def invented(messages):
                    await original(messages)
                    return AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "submit_evidence",
                                "args": {
                                    "evidence": [
                                        {
                                            "source_url": URL,
                                            "source_title": "Emergence",
                                            "snippet": "A sentence this page never con"
                                            "tained at all.",
                                            "key_fact": "k",
                                        }
                                    ]
                                },
                                "id": "bad-1",
                            }
                        ],
                    )

                bound.ainvoke = invented
            return bound

    llm = _Fabricator([_read_turn(URL, "r1")] + [_search_turn("more", f"s{i}") for i in range(20)])

    out = await _research(monkeypatch, llm)

    assert out["evidence"], "the chunk is kept — only the invented quotation is removed"
    assert out["evidence"][0]["snippet"] == "", "an invented quote must not reach the renderer"
    assert out["evidence"][0]["snippet_unverified"] is True


# ── 2. A rejected submission is reported, not swallowed ────────────────────────────


@pytest.mark.asyncio
async def test_a_rejected_submit_evidence_is_logged(monkeypatch, capsys):
    """Bad arguments on every round used to look exactly like never calling the tool.

    Read from stdout rather than `caplog`: this package logs through structlog's own
    renderer, which never reaches the stdlib handler pytest captures.
    """
    bad = AIMessage(
        content="",
        tool_calls=[
            {"name": "submit_evidence", "args": {"evidence": [{"no_source_url": 1}]}, "id": "b1"}
        ],
    )
    llm = _FakeLLM([_read_turn(URL, "r1"), bad, bad, bad])

    await _research(monkeypatch, llm)

    out = capsys.readouterr().out
    assert "submit_evidence_rejected" in out, (
        "a model calling submit_evidence with bad arguments must be distinguishable "
        "from one that never called it"
    )
    assert "source_url" in out, "the log must name what the model got wrong"


# ── 3. Bounded reading, so a task converges instead of grazing ─────────────────────


@pytest.mark.asyncio
async def test_reading_is_bounded_so_a_task_converges(monkeypatch):
    """A model that keeps opening pages is cut off and asked to submit what it has.

    Not a cost control — a termination control. The observed run spent every round on
    another fetch and never reached a conclusion.
    """
    llm = _FakeLLM([_read_turn(f"{URL}?p={i}", f"r{i}") for i in range(30)])

    out = await _research(monkeypatch, llm)

    reads = sum(1 for c in llm.calls if c is None)
    assert reads <= graph_mod._MAX_PAGES_PER_TASK + 1, (
        f"the executor took {reads} turns; reading must stop and submit"
    )
    assert out["evidence"], "what was read must still be turned into evidence"


@pytest.mark.asyncio
async def test_the_same_url_is_not_fetched_twice(monkeypatch):
    """The observed run re-read one arXiv page five times inside a single task."""
    fetched: list[str] = []

    llm = _FakeLLM([_read_turn(URL, f"r{i}") for i in range(10)])
    _install(monkeypatch, llm)

    async def counting_read(args):
        fetched.append(args["url"])
        return {"url": args["url"], "text": PAGE, "error": None}

    graph_mod._TOOLS_BY_NAME["read_webpage"].ainvoke = counting_read

    token = set_run_config(RunConfig(llm_mode="real"))
    try:
        await graph_mod._research_one(_state(), TASK, graph_mod._BudgetGuard(0.0, 0.0))
    finally:
        reset_run_config(token)

    assert fetched.count(URL) == 1, f"fetched the same URL {fetched.count(URL)} times"


# ── 4. One forcing mechanism is not enough on a rotating router ────────────────────


@pytest.mark.asyncio
async def test_a_model_that_ignores_tool_choice_falls_back_to_structured_output(monkeypatch):
    """`custom:auto/best-fast` is a router alias, not a pinned model.

    Observed live: one task's turns were served by `big-pickle`, then `hy3-free`, then
    `gemini-3.6-flash-high` — a different model on nearly every call. A named `tool_choice`
    is honoured by most and silently ignored by some, which returned an assistant message
    with no tool call at all and cost the task its evidence even though the engine had the
    text in hand. So the forced pass tries a second, differently-shaped request rather than
    giving up on the first refusal (AGENTS.md: router aliases resolve differently per call).
    """
    seen: list[str] = []

    class _Refuser(_FakeLLM):
        """Never emits a tool call, whatever `tool_choice` says."""

        def bind_tools(self, tools, tool_choice=None):
            bound = _FakeBound(self, tool_choice)
            if tool_choice is None:
                # The ordinary tool loop still runs, so the task really does fetch a page —
                # otherwise there would be no `seen_text` and no forced pass to test.
                return bound
            seen.append("tool_choice")

            async def refuse(messages):
                return AIMessage(content="I could not find anything.", tool_calls=[])

            bound.ainvoke = refuse
            return bound

        def with_structured_output(self, schema, include_raw=False):
            seen.append("structured")

            class _Structured:
                async def ainvoke(_self, messages):
                    parsed = schema.model_validate(
                        {
                            "evidence": [
                                {
                                    "source_url": URL,
                                    "source_title": "Emergence",
                                    "snippet": PAGE,
                                    "key_fact": "Emergent abilities appear only in larger models.",
                                }
                            ]
                        }
                    )
                    return {"raw": AIMessage(content=""), "parsed": parsed, "parsing_error": None}

            return _Structured()

    llm = _Refuser([_read_turn(URL, "r1")] + [_search_turn("more", f"s{i}") for i in range(20)])

    out = await _research(monkeypatch, llm)

    assert "structured" in seen, "a refused tool call must be retried a different way"
    assert out["evidence"], "the fallback must recover the evidence"
    assert out["evidence"][0]["snippet"] == PAGE, "and it is still checked against seen text"
