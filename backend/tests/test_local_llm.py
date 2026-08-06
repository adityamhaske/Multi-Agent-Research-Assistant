"""Local LLM probe (docs/12 M15).

The point of the probe is that it tells the truth when nothing is running — the previous
behaviour reported Ollama "available" unconditionally, so a user could select a local
model and only discover the problem minutes into a run.
"""

import httpx
import pytest

from app.services import local_llm


def _mock_client(handler):
    """Patch httpx.AsyncClient with a MockTransport-backed client."""

    class _Client(httpx.AsyncClient):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    return _Client


def test_api_root_strips_the_openai_suffix():
    # Config holds the OpenAI-compatible URL; discovery lives at the REST root.
    assert local_llm._api_root("http://localhost:11434/v1") == "http://localhost:11434"
    assert local_llm._api_root("http://host.docker.internal:11434/v1/") == (
        "http://host.docker.internal:11434"
    )
    assert local_llm._api_root("http://localhost:11434") == "http://localhost:11434"


def test_catalog_route_matches_on_family_not_exact_tag():
    # A user who pulled qwen2.5:7b should still get the catalog's routable entry.
    route, in_catalog = local_llm._match_catalog_route("qwen2.5:7b")
    assert route == "ollama:qwen2.5"
    assert in_catalog is True


def test_unknown_model_still_gets_a_usable_route():
    route, in_catalog = local_llm._match_catalog_route("some-finetune:latest")
    assert route == "ollama:some-finetune:latest"  # factory splits on the first colon
    assert in_catalog is False


@pytest.mark.parametrize(
    ("name", "params", "small"),
    [
        ("qwen2.5:7b", 7.0, True),
        ("deepseek-r1:1.5b", 1.5, True),
        # Regression (caught in live testing): a substring search for "4b" matches inside
        # "14b" and mislabels a capable model as underpowered.
        ("deepseek-r1:14b", 14.0, False),
        ("qwen2.5-coder:14b", 14.0, False),
        ("llama3.3:70b", 70.0, False),
        # No stated size → not flagged; guessing would warn users off capable models.
        ("llama3.2:latest", None, False),
        ("phi3:mini", None, True),  # qualitative fallback
    ],
)
def test_parameter_size_classification(name, params, small):
    assert local_llm._parse_params_b(name) == params
    assert local_llm._is_underpowered(name) is small


def test_embedding_models_are_identified():
    # Regression: an embedding model cannot chat at all, so it must not be offered as a
    # research-ready agent model.
    assert local_llm._is_embedding("nomic-embed-text:latest") is True
    assert local_llm._is_embedding("qwen2.5:14b") is False


@pytest.mark.asyncio
async def test_probe_reports_not_reachable_when_nothing_is_listening(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr(httpx, "AsyncClient", _mock_client(handler))
    status = await local_llm.probe("http://localhost:11434/v1")

    assert status.reachable is False
    assert status.usable is False
    assert status.error
    assert "ollama serve" in status.hint  # actionable, user-facing


@pytest.mark.asyncio
async def test_probe_lists_models_and_flags_small_ones(monkeypatch):
    def handler(request):
        assert request.url.path == "/api/tags"
        return httpx.Response(
            200,
            json={
                "models": [
                    {"name": "qwen2.5:7b", "size": 4_700_000_000},
                    {"name": "llama3.3:70b", "size": 40_000_000_000},
                ]
            },
        )

    monkeypatch.setattr(httpx, "AsyncClient", _mock_client(handler))
    status = await local_llm.probe("http://localhost:11434/v1")

    assert status.reachable is True and status.usable is True
    by_name = {m.name: m for m in status.models}
    assert by_name["qwen2.5:7b"].likely_underpowered is True
    assert by_name["qwen2.5:7b"].params_b == 7.0
    assert by_name["llama3.3:70b"].likely_underpowered is False
    # A mixed install is fine — no blanket warning.
    assert status.hint is None


@pytest.mark.asyncio
async def test_probe_warns_when_every_model_is_small(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"models": [{"name": "qwen2.5:7b", "size": 1}]})

    monkeypatch.setattr(httpx, "AsyncClient", _mock_client(handler))
    status = await local_llm.probe("http://localhost:11434/v1")

    assert status.usable is True
    assert "under 14B" in status.hint


@pytest.mark.asyncio
async def test_probe_warns_when_server_has_no_models(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"models": []})

    monkeypatch.setattr(httpx, "AsyncClient", _mock_client(handler))
    status = await local_llm.probe("http://localhost:11434/v1")

    assert status.reachable is True
    assert status.usable is False  # running, but nothing to run
    assert "ollama pull" in status.hint


@pytest.mark.asyncio
async def test_probe_warns_when_only_embedding_models_are_installed(monkeypatch):
    """An embedding model powers retrieval, never an agent role."""

    def handler(request):
        return httpx.Response(
            200, json={"models": [{"name": "nomic-embed-text:latest", "size": 274_000_000}]}
        )

    monkeypatch.setattr(httpx, "AsyncClient", _mock_client(handler))
    status = await local_llm.probe("http://localhost:11434/v1")

    only = status.models[0]
    assert only.is_embedding is True
    assert only.likely_underpowered is False  # it is not weak, it is a different kind
    assert "embedding models" in status.hint
