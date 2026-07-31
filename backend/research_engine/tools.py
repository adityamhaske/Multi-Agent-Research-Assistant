"""
Agent tools — each with one responsibility (docs/04_Agent_Design.md §4).

web_search   → retriever chain (Tavily → Brave → DuckDuckGo), Redis-cached
read_webpage → SSRF-guarded fetch + main-text extraction
calculate    → AST-restricted arithmetic
"""

from __future__ import annotations

import ast
import operator
from typing import Any

import httpx
from bs4 import BeautifulSoup
from langchain_core.tools import tool

from app.agent.net_guard import SSRFBlocked, validate_url
from app.agent.retrievers import search
from app.agent.runconfig import get_run_config

MAX_PAGE_CHARS = 8000
MAX_BODY_BYTES = 2 * 1024 * 1024
_MAX_REDIRECTS = 3


@tool
async def web_search(query: str, max_results: int = 5) -> list[dict]:
    """Search the web and return results as a list of {title, url, snippet}.

    Use this first to find relevant pages for a research task. Include date ranges
    in the query when the topic is time-sensitive.
    """
    try:
        return await search(query, max_results=max_results)
    except Exception as e:  # noqa: BLE001 — surface a usable message to the agent
        return [{"title": "Search unavailable", "url": "", "snippet": str(e)}]


@tool
async def read_webpage(url: str) -> dict:
    """Fetch a webpage and return {url, title, text, error}.

    Use after web_search to read a promising page. SSRF-guarded: internal,
    loopback, and cloud-metadata addresses are refused. Not for PDFs/videos.
    """
    if get_run_config().llm_mode == "fake":
        from app.agent.fakes import fake_read_webpage

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
