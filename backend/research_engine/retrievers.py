"""
Search retriever chain (docs/architecture/03_Tech_Stack.md, docs/04 §4).

Ordered fallback: Tavily → Brave → DuckDuckGo. First success wins. DuckDuckGo is
the keyless last resort (endemic rate-limiting — never the sole retriever).
Results are normalized to {title, url, snippet} and cached in Redis (24h).

In LLM_MODE=fake a deterministic fixture retriever is used so tests need no network.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import structlog

from research_engine.cache import get_cache
from research_engine.runconfig import get_run_config

logger = structlog.get_logger()

SearchResult = dict  # {"title": str, "url": str, "snippet": str}
_CACHE_TTL = 86_400


async def _tavily(query: str, max_results: int) -> list[SearchResult]:
    api_key = get_run_config().tavily_api_key
    if not api_key:
        return []
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
        for r in data.get("results", [])
    ]


async def _brave(query: str, max_results: int) -> list[SearchResult]:
    api_key = get_run_config().brave_api_key
    if not api_key:
        return []
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": max_results},
            headers={"X-Subscription-Token": api_key},
        )
        resp.raise_for_status()
        data = resp.json()
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("description", "")}
        for r in data.get("web", {}).get("results", [])
    ]


async def _duckduckgo(query: str, max_results: int) -> list[SearchResult]:
    from ddgs import DDGS

    def _run() -> list[dict]:
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))

    raw = await asyncio.to_thread(_run)
    return [
        {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
        for r in raw
    ]


_CHAIN = (("tavily", _tavily), ("brave", _brave), ("duckduckgo", _duckduckgo))


async def search(query: str, max_results: int = 5) -> list[SearchResult]:
    """Run the retriever chain with Redis caching. Raises on total exhaustion."""
    if get_run_config().llm_mode == "fake":
        from research_engine.fakes import fake_search

        return fake_search(query, max_results)

    # Cache lookup (best-effort; cache failures never break search). The backend is a
    # host-supplied Cache port — Redis on the server, SQLite on the desktop, null by
    # default (docs/13 §4).
    cache = get_cache()
    cache_key = f"search:{max_results}:{query.strip().lower()}"
    try:
        cached = await cache.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:  # noqa: BLE001 — an unavailable cache is not a search failure
        pass

    errors: list[str] = []
    for name, fn in _CHAIN:
        try:
            results = await fn(query, max_results)
            if results:
                try:
                    await cache.set(cache_key, json.dumps(results), _CACHE_TTL)
                except Exception:  # noqa: BLE001 — see above
                    pass
                logger.info("retriever_hit", retriever=name, count=len(results))
                return results
        except Exception as e:  # noqa: BLE001 — try the next retriever
            errors.append(f"{name}: {e}")
            logger.warning("retriever_failed", retriever=name, error=str(e))

    raise RuntimeError(
        f"All retrievers failed or returned nothing: {'; '.join(errors) or 'no keys'}"
    )
