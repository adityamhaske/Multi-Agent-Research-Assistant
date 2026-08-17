"""
The server host's implementations of the engine's ports (docs/13 §4).

`research_engine` declares shapes in `research_engine/ports.py`; this module supplies the
Postgres/Redis-backed versions of them, plus the embeddings provider project memory runs
on (docs/14 §4). The desktop host (docs/12 M9) will have its own counterpart supplying
SQLite and in-process equivalents, and the engine will not know the difference.

Conformance is structural, not by inheritance — `tests/test_engine_runner.py` asserts it
with `isinstance` against the runtime-checkable Protocols.

Kept separate from `app/runtime.py`, which maps settings → RunConfig and nothing else.
"""

from __future__ import annotations

import asyncio
import time
import uuid

import httpx
import structlog

from app.config import settings
from app.db.redis import publish_event
from app.models.agent_log import AgentLog
from research_engine.embeddings import (
    EmbeddingsUnavailable,
    FakeEmbeddings,
    NoEmbeddings,
    is_local_endpoint,
)
from research_engine.llm_factory import map_local_host
from research_engine.ports import Embeddings, EventSink

logger = structlog.get_logger()


class RedisCache:
    """Search-result cache backed by the shared Redis pool.

    Deliberately not defensive: `retrievers.search` treats every cache operation as
    advisory and swallows failures, which is why an unreachable Redis degrades a run to
    "uncached" instead of failing it.
    """

    async def get(self, key: str) -> str | None:
        from app.db.redis import get_redis

        return await get_redis().get(key)

    async def set(self, key: str, value: str, ttl: int) -> None:
        from app.db.redis import get_redis

        await get_redis().set(key, value, ex=ttl)


def agent_log_sink(db, session_id: str) -> EventSink:
    """Event sink that persists to `agent_logs`, then publishes to Redis.

    The row is written and committed *before* the publish, and the row id is attached to
    the published payload — that is what makes SSE replay with `Last-Event-ID` work
    (docs/05 §4): a client reconnecting mid-run resumes from a durable id rather than
    losing whatever was in flight.

    Bound to a caller-supplied DB session so the whole run shares one session scope; the
    detached-object writes that caused the July 2026 worker bug came from not doing this.

    Serialised by a per-run lock, because an `AsyncSession` is *not* safe for concurrent
    use. Once M7 gave the executor parallel tasks, two of them could reach `flush()` on
    this shared session at the same time and the run died with "Session is already
    flushing" — reliably, on every parallel run, in fake mode as much as real. The lock
    spans the publish as well as the write so that events reach Redis in the same order
    they were committed; `Last-Event-ID` replay hands clients a monotonic cursor, and
    publishing out of order would let a reconnecting client skip an event whose id is
    lower than one it has already seen.
    """
    session_uuid = uuid.UUID(session_id)
    write_lock = asyncio.Lock()

    async def sink(sid: str, event: dict) -> None:  # noqa: ARG001 - port shape
        row = AgentLog(
            session_id=session_uuid,
            event_type=event.get("type", "agent_log"),
            agent_name=event.get("agent"),
            payload=event,
        )
        async with write_lock:
            db.add(row)
            await db.flush()
            event["id"] = row.id
            await db.commit()
            await publish_event(session_id, event)

    return sink


# ── Embeddings (docs/14 §4) ────────────────────────────────────────────────────────
#
# The width of `memory_chunks.embedding`. Every supported provider is configured to
# produce exactly this, which keeps switching providers a re-index rather than a
# migration. It does NOT make their vectors interchangeable — equal width is not equal
# meaning, which is why each chunk records the model that produced it.
EMBEDDING_DIMENSIONS = 768

_DEFAULT_EMBEDDING_MODELS = {
    "ollama": "nomic-embed-text",
    "google": "text-embedding-004",
    "openai": "text-embedding-3-small",
}

# A local embedding pass is fast, but the first call after a cold start pays for loading
# the model into memory, which is slow enough to look like a hang at a chat timeout.
_EMBED_TIMEOUT_SECONDS = 60.0

# How long an "is Ollama there?" answer is reused. Without this, every chat message on a
# deployment with no local server pays the probe timeout before falling back.
_PROBE_CACHE_SECONDS = 300.0
_probe_cache: tuple[float, str | None] | None = None


def _check_width(vectors: list[list[float]], model_id: str) -> list[list[float]]:
    """Reject vectors the memory column cannot store, with a message that says why.

    Postgres would reject them anyway — `vector(768)` is enforced — but as an opaque
    write error at ingestion time, long after the misconfiguration. Checking here names
    the model and both widths.
    """
    for vector in vectors:
        if len(vector) != EMBEDDING_DIMENSIONS:
            raise EmbeddingsUnavailable(
                f"Embedding model '{model_id}' returned {len(vector)}-dimensional "
                f"vectors, but project memory stores {EMBEDDING_DIMENSIONS}. Configure "
                f"EMBEDDINGS_MODEL to a {EMBEDDING_DIMENSIONS}-dimensional model, or "
                f"migrate the column and re-index everything."
            )
    return vectors


class OllamaEmbeddings:
    """Local embeddings over Ollama's OpenAI-compatible endpoint.

    Plain httpx for the same reason `services/local_llm.py` uses it: this path should not
    drag in a model client, and the wire format is two fields.
    """

    def __init__(self, model: str, base_url: str) -> None:
        self._model = model
        # Same localhost→host.docker.internal rewrite the chat models get. This adapter
        # talks to Ollama with its own httpx client instead of going through
        # `llm_factory`, so it never inherited the mapping and dialled the *container*
        # for every embedding — breaking corpus upload and project-memory ingestion
        # inside Docker while chat completions worked fine.
        self._base_url = map_local_host(base_url.rstrip("/"))

    @property
    def is_local(self) -> bool:
        # OLLAMA_BASE_URL can point anywhere; only the endpoint decides (docs/12 M10).
        return is_local_endpoint(self._base_url)

    @property
    def model_id(self) -> str:
        return f"ollama:{self._model}"

    @property
    def dimensions(self) -> int:
        return EMBEDDING_DIMENSIONS

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            async with httpx.AsyncClient(timeout=_EMBED_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{self._base_url}/embeddings",
                    json={"model": self._model, "input": texts},
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:  # noqa: BLE001 — every failure means "cannot embed"
            raise EmbeddingsUnavailable(
                f"Local embedding server at {self._base_url} did not answer: {exc}. "
                f"Check that Ollama is running and `ollama pull {self._model}` has been run."
            ) from exc

        # Order is by the `index` field, not by arrival — a chunk paired with the wrong
        # vector is a silent retrieval bug, not a crash.
        rows = sorted(payload.get("data") or [], key=lambda row: row.get("index", 0))
        vectors = [row.get("embedding") or [] for row in rows]
        if len(vectors) != len(texts):
            raise EmbeddingsUnavailable(
                f"Embedding server returned {len(vectors)} vectors for {len(texts)} inputs."
            )
        return _check_width(vectors, self.model_id)


class HostedEmbeddings:
    """Embeddings from a hosted provider, on the user's key or the deployment's.

    Wraps the LangChain client rather than the REST API because the provider SDKs already
    handle batching limits and retries, and this path runs rarely enough (once per
    approved report, once per chat message) that the dependency weight is irrelevant.
    """

    def __init__(self, provider: str, model: str, api_key: str) -> None:
        self._provider = provider
        self._model = model
        self._api_key = api_key

    # A hosted provider is a network call by definition. This is the adapter that made
    # corpus-only mode's "no network calls at all" claim untrue whenever a deployment set
    # EMBEDDINGS_PROVIDER=google|openai: the query embedding at corpus.py::search left the
    # machine on every corpus search. The airgap guard now refuses it outright.
    is_local = False

    @property
    def model_id(self) -> str:
        return f"{self._provider}:{self._model}"

    @property
    def dimensions(self) -> int:
        return EMBEDDING_DIMENSIONS

    def _client(self):
        if self._provider == "google":
            from langchain_google_genai import GoogleGenerativeAIEmbeddings

            # The API names embedding models under `models/`; accept either form so the
            # setting can be written the way the provider's docs show it.
            name = self._model if self._model.startswith("models/") else f"models/{self._model}"
            return GoogleGenerativeAIEmbeddings(model=name, google_api_key=self._api_key)

        from langchain_openai import OpenAIEmbeddings

        # text-embedding-3-* support Matryoshka truncation, so one setting keeps every
        # provider at the stored width instead of forcing a wider column for one of them.
        return OpenAIEmbeddings(
            model=self._model, api_key=self._api_key, dimensions=EMBEDDING_DIMENSIONS
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            vectors = await self._client().aembed_documents(texts)
        except Exception as exc:  # noqa: BLE001
            raise EmbeddingsUnavailable(
                f"Embedding provider '{self._provider}' failed: {exc}"
            ) from exc
        return _check_width(vectors, self.model_id)


async def _local_embedding_model() -> str | None:
    """The embedding model installed on the local Ollama server, if one is.

    Cached briefly: this is called on every chat turn, and on a deployment with no local
    server the probe would otherwise spend its full timeout before every fallback.
    """
    global _probe_cache
    now = time.monotonic()
    if _probe_cache is not None and _probe_cache[0] > now:
        return _probe_cache[1]

    from app.services import local_llm

    status = await local_llm.probe()
    configured = settings.embeddings_model
    installed = [m.name for m in status.models if m.is_embedding]
    # An explicitly configured model wins if it is actually there; otherwise take the
    # first embedding model the server reports.
    chosen = None
    if status.reachable:
        if configured and any(
            name.split(":", 1)[0] == configured.split(":", 1)[0] for name in installed
        ):
            chosen = configured
        elif installed:
            chosen = installed[0]

    _probe_cache = (now + _PROBE_CACHE_SECONDS, chosen)
    return chosen


def reset_embeddings_probe_cache() -> None:
    """Forget the cached Ollama probe. For tests and for a settings change."""
    global _probe_cache
    _probe_cache = None


async def embeddings_for(provider_keys: dict[str, str] | None = None) -> Embeddings:
    """Build this deployment's embeddings provider, honouring the caller's BYOK keys.

    `provider_keys` is the same `{provider: key}` mapping the pipeline gets, so a BYOK
    user's memory is embedded on their own key exactly as their research was. Returns
    `NoEmbeddings` when nothing is configured — the caller decides whether that is fatal.
    """
    keys = provider_keys or {}
    choice = settings.embeddings_provider

    # Checked before anything else, including `embeddings_provider`: fake mode is a
    # promise about the whole run, not a provider preference (docs/17 §6.2). This branch
    # was missing entirely, so `./start.sh --fake` — "keyless demo mode, no API key
    # needed" — embedded a corpus upload against the real key in `.env`, spending money
    # on a run the product said was free and 404-ing when that key was stale.
    if settings.llm_mode == "fake":
        return FakeEmbeddings()

    if choice == "none":
        return NoEmbeddings()

    def hosted(provider: str) -> Embeddings | None:
        key = keys.get(provider) or getattr(settings, f"{provider}_api_key", "")
        if not key:
            return None
        model = settings.embeddings_model or _DEFAULT_EMBEDDING_MODELS[provider]
        return HostedEmbeddings(provider, model, key)

    if choice == "ollama":
        model = await _local_embedding_model() or (
            settings.embeddings_model or _DEFAULT_EMBEDDING_MODELS["ollama"]
        )
        return OllamaEmbeddings(model, settings.ollama_base_url)

    if choice in ("google", "openai"):
        return hosted(choice) or NoEmbeddings()

    # auto: local first — free, private, and the whole point of the local-first tier —
    # then whichever hosted provider the user or the deployment has a key for.
    local = await _local_embedding_model()
    if local:
        return OllamaEmbeddings(local, settings.ollama_base_url)
    for provider in ("google", "openai"):
        built = hosted(provider)
        if built is not None:
            return built
    return NoEmbeddings()
