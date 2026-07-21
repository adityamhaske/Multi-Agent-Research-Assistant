"""
Agent tools — each tool has exactly one responsibility.
"""

import ast
import asyncio
import operator
from typing import Any

import httpx
from bs4 import BeautifulSoup
from ddgs import DDGS
from langchain_core.tools import tool

# ─── Tool 1: Web Search ─────────────────────────────────────────────────────────


@tool
async def web_search(query: str, max_results: int = 5) -> list[dict]:
    """
    Search the web using DuckDuckGo and return a list of results.
    Use this as the first step to find relevant pages for a research task.

    Args:
        query: Specific search query. Include date ranges when relevant (e.g., "Q3 2024").
        max_results: Max number of results to return (default: 5).

    Returns:
        List of dicts with keys: 'title', 'href' (URL), 'body' (snippet).
    """
    try:
        results = await asyncio.to_thread(lambda: list(DDGS().text(query, max_results=max_results)))
        return results or [{"title": "No results", "href": "", "body": "No results found."}]
    except Exception as e:
        return [{"title": "Search error", "href": "", "body": str(e)}]


# ─── Tool 2: Webpage Reader ──────────────────────────────────────────────────────

MAX_PAGE_CHARS = 8000  # ~2,000 tokens — prevent context overflow


@tool
async def read_webpage(url: str) -> dict:
    """
    Fetch and extract the main text content from a webpage URL.
    Use this after web_search to read full article content at a promising URL.
    Do NOT use on PDF, video, or non-HTML URLs.

    Args:
        url: Full URL of the webpage to read (must start with http:// or https://).

    Returns:
        Dict with keys: 'url', 'title', 'text' (main content), 'error' (None if success).
    """
    if not url or not url.startswith("http"):
        return {"url": url, "title": "", "text": "", "error": "Invalid URL."}

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0), follow_redirects=True) as client:
            response = await client.get(
                url,
                headers={"User-Agent": "ResearchBot/1.0 (+https://github.com/research-assistant)"},
            )
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")

        # Remove noise
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe"]):
            tag.decompose()

        title = soup.title.string.strip() if soup.title else "No title"
        text = " ".join(soup.get_text(separator=" ").split())[:MAX_PAGE_CHARS]

        return {"url": url, "title": title, "text": text, "error": None}

    except httpx.TimeoutException:
        return {"url": url, "title": "", "text": "", "error": "Timeout reading page (>10s)."}
    except httpx.HTTPStatusError as e:
        return {"url": url, "title": "", "text": "", "error": f"HTTP {e.response.status_code}"}
    except Exception as e:
        return {"url": url, "title": "", "text": "", "error": str(e)}


# ─── Tool 3: Safe Calculator ─────────────────────────────────────────────────────

_SAFE_OPERATORS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}


@tool
def calculate_metrics(expression: str) -> float:
    """
    Safely evaluate a mathematical expression and return the result as a float.
    Use this for percentage calculations, ratio analysis, and trend math.
    Only supports: +, -, *, /, ** (exponent), and parentheses.
    Does NOT support functions, variables, or any Python code.

    Args:
        expression: A math expression string. E.g., "(150 - 110) / 110 * 100"

    Returns:
        The numerical result as a float.
    """

    def _safe_eval(node: ast.expr) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        elif isinstance(node, ast.BinOp):
            op_func = _SAFE_OPERATORS.get(type(node.op))
            if not op_func:
                raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
            return op_func(_safe_eval(node.left), _safe_eval(node.right))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -_safe_eval(node.operand)
        else:
            raise ValueError(f"Unsupported node type: {type(node).__name__}")

    try:
        tree = ast.parse(expression.strip(), mode="eval")
        return _safe_eval(tree.body)
    except ZeroDivisionError as e:
        raise ValueError("Division by zero in expression.") from e
    except Exception as e:
        raise ValueError(f"Calculation error: {e}") from e


# ─── Tool Registry ───────────────────────────────────────────────────────────────

EXECUTOR_TOOLS = [web_search, read_webpage, calculate_metrics]
