"""
The engine's ports (docs/13 §4, docs/12 M6 step 3).

Protocols only — every implementation lives in a host. The server supplies Postgres/
Redis-backed versions (`app/adapters.py`); the desktop build (docs/12 M9) supplies
SQLite and in-process ones. `research_engine` depends on these shapes and nothing else,
which is what lets one graph run in both places.

Three ports. Two came from docs/13 (EventSink, Cache); Embeddings arrived with project
memory (docs/14 §4) and is a port for the same reason — the server embeds through Ollama
or a hosted provider, the desktop build through a local model, and the engine should not
know which.

The two candidates that were dropped were interfaces where data was sufficient:

- **KeyProvider** — provider keys are resolved by the host *before* a run (the server
  decrypts them from `users.api_key_encrypted`) and handed over as a plain
  `{provider: key}` mapping. Wrapping that in a callable would add a lookup indirection
  the engine never exercises, so `runner.run(provider_keys=…)` takes the data instead.
- **RunLock** — guarding against two workers running the same session is host
  scheduling, not pipeline behaviour: the server needs a Redis token lock because
  Celery can redeliver, and a single-process desktop app needs at most an
  `asyncio.Lock`. It stays in the host, wrapped around the runner call.

Checkpointing needs no port either — LangGraph's saver interface *is* the port
(`AsyncPostgresSaver` on the server, `AsyncSqliteSaver` locally). The host constructs
and `setup()`s the saver, then passes it in; schema creation is a host concern.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EventSink(Protocol):
    """Receives one pipeline event. Installed via `events.set_emitter`.

    The server implementation writes an `agent_logs` row (durable SSE replay) and then
    publishes to Redis (live fan-out); a desktop one pushes onto an in-process queue.
    """

    async def __call__(self, session_id: str, event: dict) -> None: ...


@runtime_checkable
class Cache(Protocol):
    """Best-effort key/value cache for search results. Installed via `cache.set_cache`.

    Implementations may fail or no-op freely: `retrievers.search` treats every cache
    operation as advisory and never lets one break a search.
    """

    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, ttl: int) -> None: ...


@runtime_checkable
class Embeddings(Protocol):
    """Turns text into vectors for project memory (docs/14 §4).

    A third port rather than a direct client call, for the same reason as the other two:
    the server embeds through Ollama or a hosted provider, and the desktop build embeds
    locally with no key at all. The engine states the shape; hosts supply the client.

    `model_id` and `dimensions` are part of the contract, not decoration. Vectors from
    different models are not comparable even when their dimensions match, so every stored
    chunk records the model that produced it and retrieval filters on it — mixing them
    silently would return confident nonsense (docs/14 §4).
    """

    @property
    def model_id(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


@runtime_checkable
class Corpus(Protocol):
    """A closed document corpus as a search source (docs/12 M10, docs/13 §8).

    The airgapped tier's retrieval connector. `search` returns exactly the shape
    `retrievers.search` returns — `{title, url, snippet}` — so the executor needs no
    branch and the graph does not change; `read` resolves one of those URLs back to
    the text at that exact document location, replacing `read_webpage`'s fetch.

    Installed via `corpus.set_corpus` and selected per-run by `RunConfig.corpus_mode`:
    when that flag is set, `retrievers.search` delegates here exclusively and
    `read_webpage` refuses every non-corpus URL — no network call of any kind
    (docs/12 M10 DoD).
    """

    async def search(self, query: str, max_results: int) -> list[dict]: ...

    async def read(self, url: str) -> dict: ...
