"""
The fail-closed default for the Embeddings port (docs/14 §4).

`ports.Embeddings` states the shape; this module supplies what every host needs
regardless of which client it wraps — the error type, and a stand-in that refuses.

**Why there is no ContextVar here, unlike `cache.py` and `events.py`.** Those two are
ambient because engine *nodes* reach for them mid-graph, so there is nowhere to pass
them. Nothing in the graph embeds: ingestion happens in the host after approval
(docs/14 §2) and retrieval is a SQL query in the host (docs/14 §5). An ambient holder
for a port the engine never reads would be indirection with no reader, so hosts
construct an adapter and pass it to the two functions that use it. docs/14 §4 records
this as a deliberate departure from the "injected alongside event_sink/cache" sketch
written before the call sites existed.

**Why the absent case raises instead of no-opping.** `NullCache` caches nothing and that
is correct — every cache touch in the retriever chain is advisory, so an absent cache
costs a re-fetch. An equivalent `NullEmbeddings` returning empty vectors would be a
silent catastrophe: ingestion would write nothing, retrieval would match nothing, and
project chat would answer "not in this project's knowledge" about research the user is
looking at. That failure surfaces weeks later as "memory doesn't work", with no error
anywhere. Fail closed (docs/00 ground rules).
"""

from __future__ import annotations

import hashlib
import math

import httpx

_EMBED_TIMEOUT_SECONDS = 60.0

# Hosts that mean "this machine". `host.docker.internal` is included because
# `llm_factory.map_local_host` rewrites `localhost` to it inside a container, so a
# genuinely local Ollama presents under that name and must not read as remote.
_LOCAL_HOSTS = frozenset(
    {"localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0", "host.docker.internal"}
)


def is_local_endpoint(base_url: str) -> bool:
    """True when `base_url` points at this machine.

    Corpus-only mode claims **zero** network calls (docs/12 M10). The query embedding is
    the one model call retrieval makes, so whether that endpoint is local is the whole
    difference between an airgapped run and a run that quietly phones a provider. One
    implementation, used by every Embeddings adapter on both hosts — the alternative is
    the duplicated-predicate failure `AGENTS.md` documents.
    """
    from urllib.parse import urlsplit

    try:
        host = urlsplit(base_url).hostname or ""
    except ValueError:  # malformed URL — treat as remote, i.e. fail closed
        return False
    return host.lower() in _LOCAL_HOSTS


class EmbeddingsUnavailable(RuntimeError):
    """No embeddings provider is configured, or the configured one could not be reached.

    Raised at the call site so each caller decides what it means: ingestion logs it and
    leaves the report un-indexed — the run itself already succeeded and must not be
    failed retroactively — while chat refuses to answer rather than implying the project
    holds no matching knowledge.
    """


class NoEmbeddings:
    """The stand-in a host gets when it configured no provider. Refuses, loudly."""

    model_id = "none"
    dimensions = 0
    # Vacuously true: it raises before any I/O, so it can never egress. Saying so
    # explicitly keeps the airgap guard from having to special-case the absent provider.
    is_local = True

    async def embed(self, texts: list[str]) -> list[list[float]]:  # noqa: ARG002
        raise EmbeddingsUnavailable(
            "No embeddings provider is configured, so project memory cannot be read or "
            "written. Install Ollama and pull an embedding model "
            "(`ollama pull nomic-embed-text`), or set EMBEDDINGS_PROVIDER together with "
            "that provider's API key."
        )


class FakeEmbeddings:
    """Deterministic in-process embeddings for `llm_mode="fake"` (docs/17 §6.2).

    Fake mode promises a keyless, offline demo, and every model call in the engine is
    gated on it. Corpus ingestion escaped that gate because embeddings are built by a
    *host* adapter, so `./start.sh --fake` embedded against whatever provider key was in
    `.env` — billing a run advertised as free, and dying on a provider 404 when the key
    was stale. This is the stand-in that closes it.

    **Deterministic, not random.** The corpus is a retrieval store: the same text must
    land in the same place across a restart, or a demo's search results shift between
    launches for no reason a user can see. A seeded hash gives that for free and needs no
    state on disk.

    The vectors are meaningless as *semantics* — nothing here understands language. What
    they preserve is the shape retrieval depends on: stable, unit-length, uniform width,
    and distinct per distinct input. A demo therefore exercises the real ingest→search
    path rather than a mock of it, while proving nothing about relevance, which is
    exactly the honest scope for fixture content.
    """

    #: `local:` because `pipeline_runner` admits corpus mode only for `ollama:`/`local:`
    #: ids, and this genuinely is in-process. `fake` is in the name because a model id is
    #: recorded as the thing that actually ran, and this one must never read as real.
    model_id = "local:fake-deterministic"
    #: 768 to match `memory_chunks.embedding`, which is a `vector(768)` column. A narrower
    #: vector would work fine for the corpus (SQLite blobs, any width) and then fail at
    #: project-memory ingestion — inside the handler that deliberately never raises, so a
    #: demo would log a warning nobody reads and quietly index nothing.
    dimensions = 768
    #: No I/O at all, so nothing can egress. The airgap guard defaults to *remote* for
    #: anything that does not declare itself (AGENTS.md), and refusing an embedder that
    #: cannot reach the network would be the guard firing at the wrong target.
    is_local = True

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def _vector(self, text: str) -> list[float]:
        # blake2b over the text, expanded to `dimensions` floats. Hashing per-index
        # rather than slicing one digest keeps the width independent of the digest size.
        raw = [
            int.from_bytes(hashlib.blake2b(f"{i}:{text}".encode(), digest_size=4).digest(), "big")
            for i in range(self.dimensions)
        ]
        # Centre on zero so vectors can oppose as well as agree; an all-positive space
        # makes every pair look similar under cosine.
        centred = [v / 2**31 - 1.0 for v in raw]
        norm = math.sqrt(sum(x * x for x in centred)) or 1.0
        return [x / norm for x in centred]


class LocalEmbeddings:
    """Embeddings from a local OpenAI-compatible server — the airgapped tier's client.

    The desktop host cannot use the server's `app/adapters.py` implementations (they
    import `app.config`, and the PyInstaller bundle excludes the redis they drag in),
    so the engine ships this keyless equivalent: same wire protocol, same ordering
    guarantee, no host imports. Plain httpx, because the wire format is two fields
    and this path must not drag a model client into the frozen bundle.
    """

    def __init__(self, model: str, base_url: str, dimensions: int = 768) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._dimensions = dimensions

    @property
    def is_local(self) -> bool:
        # Named "Local" but pointed by config: OLLAMA_BASE_URL can be set to a remote
        # host, and then this class is a network client wearing a local name.
        return is_local_endpoint(self._base_url)

    @property
    def model_id(self) -> str:
        # Same id scheme as the server's OllamaEmbeddings, so a corpus indexed on one
        # host reads as "same model" on the other.
        return f"ollama:{self._model}"

    @property
    def dimensions(self) -> int:
        return self._dimensions

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
        for vector in vectors:
            if len(vector) != self._dimensions:
                raise EmbeddingsUnavailable(
                    f"Embedding model '{self._model}' returned {len(vector)}-dimensional "
                    f"vectors, but this store is configured for {self._dimensions}."
                )
        return vectors
