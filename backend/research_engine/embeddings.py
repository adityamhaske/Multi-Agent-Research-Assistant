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
