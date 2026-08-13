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

import httpx

_EMBED_TIMEOUT_SECONDS = 60.0


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

    async def embed(self, texts: list[str]) -> list[list[float]]:  # noqa: ARG002
        raise EmbeddingsUnavailable(
            "No embeddings provider is configured, so project memory cannot be read or "
            "written. Install Ollama and pull an embedding model "
            "(`ollama pull nomic-embed-text`), or set EMBEDDINGS_PROVIDER together with "
            "that provider's API key."
        )


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
