"""
Provider credential health probe (docs/07 §2, Phase 2a of the researcher-workspace-
overhaul plan: "Test API / custom / OpenRouter connections on save — red/yellow/green").

Mirrors `local_llm.probe`'s contract (never raises) and its test convention: the
transport is stubbed with `httpx.MockTransport`, never `probe()` itself — stubbing the
function under test is the decorative-test trap AGENTS.md documents for
`test_corpus_egress.py`.

Amber ("degraded") is load-bearing: "the server answered but rejected the key" and
"nothing answered at all" have different fixes, and collapsing them into one red state
is what makes a status light useless.
"""

import httpx
import pytest

from app.services import provider_health


def _mock_client(handler):
    class _Client(httpx.AsyncClient):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    return _Client


@pytest.mark.asyncio
async def test_green_when_the_provider_answers_with_a_model_list(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "gpt-5"}, {"id": "gpt-5-mini"}]})

    monkeypatch.setattr(httpx, "AsyncClient", _mock_client(handler))
    verdict = await provider_health.probe("openai", "sk-real-key")

    assert verdict.state == "ok"
    assert verdict.model_count == 2


@pytest.mark.asyncio
async def test_amber_when_the_server_answers_but_rejects_the_key(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "Invalid API key"}})

    monkeypatch.setattr(httpx, "AsyncClient", _mock_client(handler))
    verdict = await provider_health.probe("openai", "sk-wrong-key")

    assert verdict.state == "degraded"
    assert "401" in verdict.reason or "rejected" in verdict.reason.lower()


@pytest.mark.asyncio
async def test_amber_when_the_key_is_out_of_quota(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    monkeypatch.setattr(httpx, "AsyncClient", _mock_client(handler))
    verdict = await provider_health.probe("anthropic", "sk-ant-real")

    assert verdict.state == "degraded"


@pytest.mark.asyncio
async def test_amber_distinguishes_key_rejected_from_server_error(monkeypatch):
    """ "Server answered, key refused" and "server answered, something's wrong on their
    end" are both amber, but for different reasons — the reason string must say which."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "internal error"})

    monkeypatch.setattr(httpx, "AsyncClient", _mock_client(handler))
    verdict = await provider_health.probe("google", "any-key")

    assert verdict.state == "degraded"
    assert "key" not in verdict.reason.lower()  # must not blame the key for a 500


@pytest.mark.asyncio
async def test_red_when_nothing_answers(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr(httpx, "AsyncClient", _mock_client(handler))
    verdict = await provider_health.probe("anthropic", "sk-ant-real")

    assert verdict.state == "failed"


@pytest.mark.asyncio
async def test_never_raises_on_a_malformed_response_body(monkeypatch):
    """A 200 with an unexpected JSON shape still means "connected" — the probe must not
    crash on a body it cannot parse (AGENTS.md, "never fake, never swallow" cuts both
    ways: don't invent a count, but don't explode either)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    monkeypatch.setattr(httpx, "AsyncClient", _mock_client(handler))
    verdict = await provider_health.probe("openai", "sk-real-key")

    assert verdict.state == "ok"
    assert verdict.model_count is None


@pytest.mark.asyncio
async def test_google_key_is_a_query_param_not_a_header(monkeypatch):
    """Google's Generative Language API authenticates via ?key=, not a header — assert
    on the real request shape, not a mocked call."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"models": [{"name": "gemini-2.5-pro"}]})

    monkeypatch.setattr(httpx, "AsyncClient", _mock_client(handler))
    verdict = await provider_health.probe("google", "AIza-real-key")

    assert "key=AIza-real-key" in seen["url"]
    assert verdict.state == "ok"
    assert verdict.model_count == 1


@pytest.mark.asyncio
async def test_openrouter_probes_the_key_specific_endpoint_not_the_public_catalog(monkeypatch):
    """OpenRouter's /models is public and unauthenticated — a garbage key would still
    get a 200 there, which is exactly the false green this probe exists to prevent."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"data": {"label": "my-key"}})

    monkeypatch.setattr(httpx, "AsyncClient", _mock_client(handler))
    verdict = await provider_health.probe("openrouter", "sk-or-real")

    assert "models" not in seen["url"]
    assert seen["auth"] == "Bearer sk-or-real"
    assert verdict.state == "ok"


@pytest.mark.asyncio
async def test_custom_endpoint_probes_the_configured_base_url(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"data": [{"id": "local-model"}]})

    monkeypatch.setattr(httpx, "AsyncClient", _mock_client(handler))
    verdict = await provider_health.probe(
        "custom", "bearer-token", base_url="https://api.together.xyz/v1"
    )

    assert seen["url"].startswith("https://api.together.xyz/v1")
    assert verdict.state == "ok"


@pytest.mark.asyncio
async def test_custom_without_a_base_url_is_amber_not_a_crash():
    verdict = await provider_health.probe("custom", "bearer-token", base_url=None)
    assert verdict.state == "degraded"


@pytest.mark.asyncio
async def test_empty_key_is_amber_not_a_network_call():
    verdict = await provider_health.probe("openai", "")
    assert verdict.state == "degraded"


@pytest.mark.asyncio
async def test_unknown_provider_fails_closed():
    verdict = await provider_health.probe("not-a-real-provider", "some-key")
    assert verdict.state == "failed"


@pytest.mark.asyncio
async def test_verdict_always_carries_a_checked_at_timestamp(monkeypatch):
    """`checked_at` is what lets the UI say "checked 2 minutes ago" instead of a stale
    green that never re-verifies itself."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    monkeypatch.setattr(httpx, "AsyncClient", _mock_client(handler))
    verdict = await provider_health.probe("openai", "sk-x")
    assert verdict.checked_at
