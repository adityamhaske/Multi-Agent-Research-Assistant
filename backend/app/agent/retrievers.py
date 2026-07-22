"""
Search retriever chain (docs/03_Tech_Stack.md, docs/04 §4).

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

from app.config import settings

logger = structlog.get_logger()

SearchResult = dict  # {"title": str, "url": str, "snippet": str}
_CACHE_TTL = 86_400


async def _tavily(query: str, max_results: int) -> list[SearchResult]:
    if not settings.tavily_api_key:
        return []
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": settings.tavily_api_key,
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
    if not settings.brave_api_key:
        return []
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": max_results},
            headers={"X-Subscription-Token": settings.brave_api_key},
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
    if settings.llm_mode == "fake":
        from app.agent.fakes import fake_search

        return fake_search(query, max_results)

    # Cache lookup (best-effort; cache failures never break search).
    cache_key = f"search:{max_results}:{query.strip().lower()}"
    try:
        from app.db.redis import get_redis

        cached = await get_redis().get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass

    errors: list[str] = []
    for name, fn in _CHAIN:
        try:
            results = await fn(query, max_results)
            if results:
                try:
                    from app.db.redis import get_redis

                    await get_redis().set(cache_key, json.dumps(results), ex=_CACHE_TTL)
                except Exception:
                    pass
                logger.info("retriever_hit", retriever=name, count=len(results))
                return results
        except Exception as e:  # noqa: BLE001 — try the next retriever
            errors.append(f"{name}: {e}")
            logger.warning("retriever_failed", retriever=name, error=str(e))

    raise RuntimeError(
        f"All retrievers failed or returned nothing: {'; '.join(errors) or 'no keys'}"
    )
