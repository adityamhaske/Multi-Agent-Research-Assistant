"""
The pgvector query is behind a port; the rules around it are not (Phase 5, port P12).

Revision 2 of the plan reversed a decision over this module. Revision 1 said project memory
was "a capability, not a port" — `memory.is_available(db)` is the one home for the check,
and the query stays put. That was wrong: `app/services/memory.py` calls
`MemoryChunk.embedding.cosine_distance(...)`, a **pgvector operator**, inline, in a module
both hosts import and which the plan classifies as domain. A layer that may not contain
dialect-specific SQL contained the most dialect-specific expression in the codebase.

**What moves and what does not.** Only the nearest-neighbour query. Everything else in
`memory.py` — how an approved report is chunked, which reports count as indexed, the
`status` accounting — is ordinary SQL that runs on either dialect, and it is *product* rule:
memory is fed only by the human approval gate, which is what makes it trustworthy in a way
"remember everything" features are not. Moving that behind a port would hide the rule, not
isolate a dependency.

**Two predicates survive the move, and they are the load-bearing ones.** `project_id` is
the isolation boundary. `embedding_model` is filtered because vectors from different models
are not comparable even at equal width — ranking them together produces confident nonsense
rather than an obvious error. A port that dropped either would look like it worked.
"""

from __future__ import annotations

import uuid

import pytest

from app.errors import CapabilityUnavailable
from app.ports import MemoryIndex


def test_the_server_index_satisfies_the_port():
    from app.adapters import PgVectorMemoryIndex

    assert isinstance(PgVectorMemoryIndex(), MemoryIndex)


def test_the_desktop_index_satisfies_the_same_port():
    from desktop.sidecar import UnavailableMemoryIndex

    assert isinstance(UnavailableMemoryIndex(), MemoryIndex)


def test_the_two_hosts_disagree_about_availability_and_say_so():
    """The capability difference, read off the port rather than re-derived by each caller.

    `memory.is_available(db)` tests the SQL dialect, which is a fact about storage standing
    in for a fact about the product. A caller that writes its own dialect test is a caller
    that will disagree with it.
    """
    from app.adapters import PgVectorMemoryIndex
    from desktop.sidecar import UnavailableMemoryIndex

    assert PgVectorMemoryIndex().available is True
    assert UnavailableMemoryIndex().available is False


async def test_the_desktop_index_refuses_with_a_named_capability():
    """Not a crash and not an empty result. An empty list would say "this project has
    nothing indexed", which is a different and false claim."""
    from desktop.sidecar import UnavailableMemoryIndex

    with pytest.raises(CapabilityUnavailable) as raised:
        await UnavailableMemoryIndex().nearest(
            None, project_id=uuid.uuid4(), query_vector=[0.0], embedding_model="m", limit=5
        )
    assert raised.value.capability == "project_memory"


def test_the_domain_layer_no_longer_contains_the_pgvector_operator():
    """The reversal, made checkable.

    `cosine_distance` is pgvector's. Its presence in `app/services/memory.py` is what
    invalidated revision 1's "capability, not a port", so its absence is what the fix has
    to mean.
    """
    import inspect

    from app.services import memory

    source = inspect.getsource(memory)
    assert "cosine_distance" not in source, (
        "app/services/memory.py still writes the pgvector distance operator — it belongs "
        "to the index adapter"
    )


def test_retrieve_asks_the_index_rather_than_writing_the_query():
    """And passes both isolation predicates through."""
    import inspect

    from app.services import memory

    signature = inspect.signature(memory.retrieve)
    assert "index" in signature.parameters, "retrieve must take the index it queries"

    source = inspect.getsource(memory.retrieve)
    assert "index.nearest" in source
    for predicate in ("project_id", "embedding_model"):
        assert predicate in source, f"{predicate} is an isolation boundary and must reach the index"
