"""A search engine's results page is refused by `read_webpage`, with directions to `web_search`.

The defect this pins: an executor model (a Gemini route through an OpenAI-compatible router)
never called `web_search`. It opened Google, Bing, DuckDuckGo, Yahoo, Brave, Ecosia, Qwant
and Mojeek *results pages* with `read_webpage` instead — 64 fetches in one run — and got bot
walls: Google's "enable JavaScript", Yahoo's HTTP 500, Ecosia's 403, Mojeek's captcha. The
pages that did render were ranked snippets for a misspelled phrase. Nothing was quotable, so
the run failed with "no evidence was gathered", while the same question on another model
called `web_search` and succeeded.

So the refusal is an *observation*, not an exception: it names the right tool, which is the
one thing that lets the same model recover on its next turn. It carries no text, so nothing
in it can be quoted as evidence. And it is decided before any fetch, so no request leaves.
"""

from __future__ import annotations

import time

import pytest
from langchain_core.messages import AIMessage

from research_engine import graph as graph_mod
from research_engine import tools
from research_engine.events import reset_emitter, set_emitter
from research_engine.prompt_composition import system_prompt
from research_engine.runconfig import RunConfig, reset_run_config, set_run_config

SEARCH_RESULT_PAGES = [
    "https://www.google.com/search?q=Pectual.ai",
    "https://google.com/search?q=%22Pectual.ai%22+engineering+culture",
    "https://www.google.co.uk/search?q=petual",
    "https://scholar.google.com/scholar?q=retrieval+augmented+generation",
    "https://www.bing.com/search?q=Pectual.ai",
    "https://html.duckduckgo.com/html/?q=Pectual.ai",
    "https://lite.duckduckgo.com/lite/?q=%22Pectual.ai%22",
    "https://duckduckgo.com/?q=petual",
    "https://search.yahoo.com/search?p=Pectual.ai",
    "https://search.brave.com/search?q=Pectual.ai+engineering+blog",
    "https://www.ecosia.org/search?q=%22Pectual.ai%22",
    "https://lite.qwant.com/?q=%22Pectual.ai%22",
    "https://www.qwant.com/?q=petual",
    "https://www.mojeek.com/search?q=%22Pectual.ai%22",
    "https://yandex.com/search/?text=petual",
    "https://www.baidu.com/s?wd=petual",
]

# Same hosts, not a results page: a document, a help article, an about page, a news story.
ORDINARY_PAGES = [
    "https://docs.google.com/document/d/abc123/edit",
    "https://support.google.com/websearch/answer/134479",
    "https://duckduckgo.com/about",
    "https://www.bing.com/maps",
    "https://news.yahoo.com/some-article-123.html",
    "https://petual.ai/",
]


class _NoNetwork:
    def __init__(self, *args, **kwargs):
        raise AssertionError("read_webpage opened a connection for a refused URL")


class _OnePage:
    """An httpx client that answers every GET with one small HTML page."""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None):
        import httpx

        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html><title>A page</title><body><p>Real page text.</p></body></html>",
            request=httpx.Request("GET", url),
        )


@pytest.fixture
def real_mode():
    token = set_run_config(RunConfig(llm_mode="real", enforce_ssrf_guards=False))
    yield
    reset_run_config(token)


@pytest.mark.usefixtures("real_mode")
@pytest.mark.parametrize("url", SEARCH_RESULT_PAGES)
async def test_a_search_results_page_is_refused_with_directions_and_never_fetched(url, monkeypatch):
    monkeypatch.setattr(tools.httpx, "AsyncClient", _NoNetwork)

    observation = await tools.read_webpage.ainvoke({"url": url})

    assert observation["text"] == "", "a refusal must carry nothing quotable"
    assert "web_search" in (observation["error"] or ""), observation


@pytest.mark.usefixtures("real_mode")
@pytest.mark.parametrize("url", ORDINARY_PAGES)
async def test_other_pages_on_the_same_hosts_are_still_read(url, monkeypatch):
    monkeypatch.setattr(tools.httpx, "AsyncClient", _OnePage)
    monkeypatch.setattr(tools, "validate_url", lambda u: None)  # the guard is not under test

    observation = await tools.read_webpage.ainvoke({"url": url})

    assert observation["error"] is None, observation
    assert "Real page text." in observation["text"]


def test_the_model_is_told_which_tool_searches_before_it_chooses():
    """The refusal recovers a model that guessed wrong; these keep it from guessing."""
    assert "web_search" in tools.read_webpage.description
    assert "results page" in tools.read_webpage.description
    assert "web_search" in system_prompt("executor.main").split("\n2.")[0], (
        "the executor's first step must name the tool it searches with"
    )


async def test_a_refusal_in_the_executor_loop_cannot_become_evidence(monkeypatch):
    """Through the real executor loop: the model opens a results page, then submits a snippet
    from it. The refusal reaches the model as an observation naming `web_search`, and the
    snippet is struck, because nothing was ever read from that URL."""
    url = SEARCH_RESULT_PAGES[0]
    turns = [
        AIMessage(
            content="", tool_calls=[{"name": "read_webpage", "args": {"url": url}, "id": "r"}]
        ),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "submit_evidence",
                    "args": {
                        "evidence": [
                            {
                                "source_url": url,
                                "source_title": "Google Search",
                                "snippet": "Search with the web_search tool",
                                "key_fact": "nothing",
                            }
                        ]
                    },
                    "id": "s",
                }
            ],
        ),
    ]

    class _Scripted:
        def bind_tools(self, *_args, **_kwargs):
            return self

        async def ainvoke(self, _messages):
            return turns.pop(0) if turns else AIMessage(content="done", tool_calls=[])

    monkeypatch.setattr(graph_mod, "get_llm", lambda role: _Scripted())
    monkeypatch.setattr(tools.httpx, "AsyncClient", _NoNetwork)
    events: list[dict] = []

    async def collect(_sid, event):
        events.append(event)

    config = set_run_config(RunConfig(llm_mode="real", enforce_ssrf_guards=False))
    emitter = set_emitter(collect)
    try:
        out = await graph_mod.executor_node(
            {
                "session_id": "steer-test",
                "tasks": [{"id": 1, "query": "Explain software development at Petual"}],
                "evidence": [],
                "verdicts": {},
                "retries": {},
                "research_round": 0,
                "cost_usd": 0.0,
                "tokens_input": 0,
                "tokens_output": 0,
                "started_at": time.time(),
            }
        )
    finally:
        reset_emitter(emitter)
        reset_run_config(config)

    read = [e for e in events if (e.get("detail") or {}).get("tool") == "read_webpage"]
    assert read and "web_search" in read[0]["detail"]["observation"]
    # Blanked, not dropped: `verify_evidence_snippets` keeps the chunk but strikes a quote
    # that occurs in nothing a tool returned, and an empty snippet is never numbered.
    assert [e["snippet"] for e in out["evidence"]] == [""] * len(out["evidence"]), (
        "a quotation from a refused page survived verification"
    )


async def test_after_a_refusal_the_model_searches_reads_a_real_page_and_its_quote_is_kept(
    monkeypatch,
):
    """The recovery a live run showed: the model tried results pages, was refused, called
    `web_search`, read a real page and quoted it. The refusal must cost only the turn — the
    evidence path that follows is the ordinary one, and a verbatim quote from a page that was
    really fetched survives verification with its own URL."""
    search_url = SEARCH_RESULT_PAGES[5]  # html.duckduckgo.com, as in the live run
    page_url = "https://petual.ai/about"
    page_text = "Petual brings agentic AI to internal audit and SOX testing."
    turns = [
        AIMessage(
            content="",
            tool_calls=[{"name": "read_webpage", "args": {"url": search_url}, "id": "r1"}],
        ),
        AIMessage(
            content="",
            tool_calls=[{"name": "web_search", "args": {"query": "Petual AI"}, "id": "w1"}],
        ),
        AIMessage(
            content="",
            tool_calls=[{"name": "read_webpage", "args": {"url": page_url}, "id": "r2"}],
        ),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "submit_evidence",
                    "args": {
                        "evidence": [
                            {
                                "source_url": page_url,
                                "source_title": "About Petual",
                                "snippet": page_text,
                                "key_fact": "Petual applies agentic AI to SOX testing.",
                            }
                        ]
                    },
                    "id": "s1",
                }
            ],
        ),
    ]

    class _Scripted:
        def bind_tools(self, *_args, **_kwargs):
            return self

        async def ainvoke(self, _messages):
            return turns.pop(0) if turns else AIMessage(content="done", tool_calls=[])

    class _Search:
        async def ainvoke(self, args):
            return [{"title": "Petual", "url": page_url, "snippet": "Petual — agentic AI."}]

    monkeypatch.setattr(graph_mod, "get_llm", lambda role: _Scripted())
    # Only search is stood in for; read_webpage is the real tool, fetching through a stub
    # transport — so the refusal and the real read go down the shipped code path.
    monkeypatch.setattr(
        graph_mod, "_TOOLS_BY_NAME", {**graph_mod._TOOLS_BY_NAME, "web_search": _Search()}
    )

    class _Page(_OnePage):
        async def get(self, url, headers=None):
            import httpx

            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text=f"<html><title>About</title><body><p>{page_text}</p></body></html>",
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(tools.httpx, "AsyncClient", _Page)
    monkeypatch.setattr(tools, "validate_url", lambda u: None)
    events: list[dict] = []

    async def collect(_sid, event):
        events.append(event)

    config = set_run_config(RunConfig(llm_mode="real", enforce_ssrf_guards=False))
    emitter = set_emitter(collect)
    try:
        out = await graph_mod.executor_node(
            {
                "session_id": "recover-test",
                "tasks": [{"id": 1, "query": "Explain software development at Petual"}],
                "evidence": [],
                "verdicts": {},
                "retries": {},
                "research_round": 0,
                "cost_usd": 0.0,
                "tokens_input": 0,
                "tokens_output": 0,
                "started_at": time.time(),
            }
        )
    finally:
        reset_emitter(emitter)
        reset_run_config(config)

    used = [
        (e["detail"]["tool"], e["detail"]["args"].get("url"))
        for e in events
        if (e.get("detail") or {}).get("tool")
    ]
    assert used == [
        ("read_webpage", search_url),
        ("web_search", None),
        ("read_webpage", page_url),
    ], used
    refusal = next(e for e in events if (e.get("detail") or {}).get("tool") == "read_webpage")
    assert "web_search" in refusal["detail"]["observation"], "the search page was fetched"
    assert [(e["source_url"], e["snippet"]) for e in out["evidence"]] == [(page_url, page_text)]
