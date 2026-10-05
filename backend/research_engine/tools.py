"""
Agent tools — each with one responsibility (docs/architecture/04-agent-architecture.md §4).

web_search   → retriever chain (Tavily → Brave → DuckDuckGo), Redis-cached
read_webpage → SSRF-guarded fetch + main-text extraction
calculate    → AST-restricted arithmetic

In corpus mode (docs/12 M10) the fetch half of that contract changes: `read_webpage`
resolves `corpus://` locations from the installed corpus and refuses every other URL,
so the executor's tool surface makes zero network calls.
"""

from __future__ import annotations

import ast
import operator
from typing import Any
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup
from langchain_core.tools import tool

from research_engine.corpus import get_corpus
from research_engine.net_guard import SSRFBlocked, validate_url
from research_engine.retrievers import search
from research_engine.runconfig import get_run_config

MAX_PAGE_CHARS = 8000
MAX_BODY_BYTES = 2 * 1024 * 1024
_MAX_REDIRECTS = 3

#: Search engines' *results pages*: (registrable domain, results paths). An empty paths tuple
#: means "any path carrying a query" — DuckDuckGo and Qwant answer searches at their root.
#: The domain matches itself and any subdomain; `google` and `yandex` match any country TLD.
_SEARCH_RESULTS_PAGES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("google", ("/search", "/scholar")),
    ("yandex", ("/search",)),
    ("bing.com", ("/search",)),
    ("duckduckgo.com", ("/html", "/lite", "")),
    ("search.yahoo.com", ("/search",)),
    ("search.brave.com", ("/search",)),
    ("ecosia.org", ("/search",)),
    ("qwant.com", ("",)),
    ("mojeek.com", ("/search",)),
    ("baidu.com", ("/s",)),
    ("startpage.com", ("/do/search", "/sp/search")),
)

SEARCH_RESULTS_PAGE_REFUSAL = (
    "not fetched: this is a search engine's results page, which returns bot checks or "
    "ranked snippets rather than a source. Search with the web_search tool — it returns "
    "titles, URLs and snippets — then read_webpage the specific pages it finds."
)


def is_search_results_page(url: str) -> bool:
    """Whether `url` asks a web search engine for results rather than naming a source.

    One home for the rule. An executor model that never calls `web_search` opens these with
    `read_webpage` instead — one real run made 64 such fetches and got Google's JavaScript
    wall, Yahoo's 500, Ecosia's 403 and Mojeek's captcha — so `read_webpage` refuses them
    with directions rather than fetching a page that is almost never quotable.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    path = parts.path.rstrip("/")
    labels = host.split(".")
    for domain, paths in _SEARCH_RESULTS_PAGES:
        if "." in domain:
            on_engine = host == domain or host.endswith("." + domain)
        else:
            on_engine = domain in labels[:-1]  # `google.co.uk`, `scholar.google.com`
        if not on_engine:
            continue
        for results_path in paths:
            if results_path and (path == results_path or path.startswith(results_path + "/")):
                return True
            if not results_path and parts.query:
                return True
    return False


@tool
async def web_search(query: str, max_results: int | None = None) -> list[dict]:
    """Search the web and return results as a list of {title, url, snippet}.

    Use this first to find relevant pages for a research task. It is the only way to
    search: a search engine's results page opened with read_webpage is refused. Include
    date ranges in the query when the topic is time-sensitive.
    """
    # The agent may specify a count; omitting it falls back to the configured
    # `retrieval_k` (internal/07 Phase 3) rather than a value baked into the schema —
    # the default here used to be the literal 5 this config's own default mirrors.
    k = max_results if max_results is not None else get_run_config().retrieval_k
    try:
        return await search(query, max_results=k)
    except Exception as e:  # noqa: BLE001 — surface a usable message to the agent
        return [{"title": "Search unavailable", "url": "", "snippet": str(e)}]


@tool
async def read_webpage(url: str) -> dict:
    """Fetch one specific source page and return {url, title, text, error}.

    Use after web_search to read a promising result. Not a search tool: a search
    engine's results page (Google, Bing, DuckDuckGo, …) is refused — call web_search to
    search. SSRF-guarded: internal, loopback, and cloud-metadata addresses are refused.
    Not for PDFs/videos. In corpus-only mode, only corpus:// locations can be read.
    """
    if url.startswith("corpus://"):
        # A corpus location is a file offset, not a fetch. Resolved before the
        # fake-mode shortcut so scripted runs exercise the real store too.
        try:
            return await get_corpus().read(url)
        except Exception as e:  # noqa: BLE001 — surface a usable message to the agent
            return {"url": url, "title": "", "text": "", "error": str(e)}

    if get_run_config().corpus_mode:
        # Fail closed: an airgapped run must not fetch anything, however plausible the
        # URL. Returning an error dict (not raising) keeps the executor able to finish
        # its task with corpus evidence instead of looping on a dead tool.
        return {
            "url": url,
            "title": "",
            "text": "",
            "error": "blocked: corpus-only mode — network access is disabled",
        }

    if is_search_results_page(url):
        # Before the fake-mode shortcut too: the rule is about which tool searches, not about
        # what a fetch would return, so scripted runs must see the same refusal real ones do.
        # An error with empty text, so nothing in it can be quoted as evidence.
        return {"url": url, "title": "", "text": "", "error": SEARCH_RESULTS_PAGE_REFUSAL}

    cfg = get_run_config()
    if cfg.llm_mode == "fake":
        if cfg.demo:
            from research_engine.demo_fixtures import demo_read_webpage

            return demo_read_webpage(url)
        from research_engine.fakes import fake_read_webpage

        return fake_read_webpage(url)

    current = url
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0), follow_redirects=False) as client:
            for _ in range(_MAX_REDIRECTS + 1):
                validate_url(current)  # re-validate every hop (docs/06 §3)
                resp = await client.get(
                    current, headers={"User-Agent": "ResearchBot/1.0 (+research-assistant)"}
                )
                if resp.is_redirect and "location" in resp.headers:
                    current = str(resp.url.join(resp.headers["location"]))
                    continue
                break
            else:
                return {"url": url, "title": "", "text": "", "error": "too many redirects"}

        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "")
        if not ("text/html" in ctype or "text/plain" in ctype):
            return {
                "url": url,
                "title": "",
                "text": "",
                "error": f"unsupported content-type: {ctype}",
            }
        body = resp.content[:MAX_BODY_BYTES]

        soup = BeautifulSoup(body, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe"]):
            tag.decompose()
        title = soup.title.string.strip() if soup.title and soup.title.string else "No title"
        text = " ".join(soup.get_text(separator=" ").split())[:MAX_PAGE_CHARS]
        return {"url": url, "title": title, "text": text, "error": None}

    except SSRFBlocked as e:
        return {"url": url, "title": "", "text": "", "error": f"blocked: {e}"}
    except httpx.TimeoutException:
        return {"url": url, "title": "", "text": "", "error": "timeout (>10s)"}
    except httpx.HTTPStatusError as e:
        return {"url": url, "title": "", "text": "", "error": f"HTTP {e.response.status_code}"}
    except Exception as e:  # noqa: BLE001
        return {"url": url, "title": "", "text": "", "error": str(e)}


_SAFE_OPERATORS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}


@tool
def calculate(expression: str) -> float:
    """Safely evaluate an arithmetic expression (+, -, *, /, **, parentheses)."""

    def _eval(node: ast.expr) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp):
            fn = _SAFE_OPERATORS.get(type(node.op))
            if not fn:
                raise ValueError(f"unsupported operator: {type(node.op).__name__}")
            return fn(_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -_eval(node.operand)
        raise ValueError(f"unsupported expression node: {type(node).__name__}")

    try:
        tree = ast.parse(expression.strip(), mode="eval")
        return _eval(tree.body)
    except ZeroDivisionError as e:
        raise ValueError("division by zero") from e
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"calculation error: {e}") from e


EXECUTOR_TOOLS = [web_search, read_webpage, calculate]
