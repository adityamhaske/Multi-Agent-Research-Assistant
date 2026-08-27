"""
The one corpus upload contract, for both hosts.

**Why this is its own module.** The per-project corpus path is the canonical product
contract and both hosts serve it: the server over one SQLite file per project, the desktop
over a single `corpus.sqlite`. That storage difference is infrastructure and stays. What a
client sees must not differ — and every part of it did, because each host validated the
upload, mapped the failures and shaped the response independently.

Same relocation rule as `app/services/document_headers.py`: **stdlib, pydantic and the
domain only** — no FastAPI, and nothing that reaches `app.config` or `app.db`, or the
packaged sidecar dies at import (#50) and `tests/workflow/test_sidecar_startup.py` fails.

Refusals are stated as domain errors (`app/errors.py`); both hosts install the one handler
that turns them into a status (`app/services/error_responses.py`). This module used to
raise `HTTPException`, which was still better than two hosts choosing their own codes —
that is what produced `400` on one and `422` on the other for the same rejection — but it
made a shared module depend on one delivery mechanism.
"""

from __future__ import annotations

from pathlib import Path

from app.errors import DependencyUnavailable, Invalid, PayloadTooLarge
from app.schemas.corpus import CorpusStatusResponse, DocumentResponse
from research_engine.documents import MAX_DOCUMENT_BYTES

__all__ = [
    "MAX_DOCUMENT_BYTES",
    "clean_upload",
    "document_response",
    "ingest_document",
    "ingested_response",
    "status_response",
]

#: 404 for a document that is not in this corpus. One string, so the two hosts stop
#: differing by a full stop — a difference a client matching on the message still sees.
DOCUMENT_NOT_FOUND = "Document not found."


def clean_upload(filename: str | None, data: bytes) -> str:
    """Validate one upload and return the name to store it under.

    A size refusal is its own error rather than another `Invalid`: it tells a client the
    request was well-formed and simply too big, and it is the only one of these the server
    did not enforce at all before.
    """
    name = Path(filename or "").name  # metadata only; never a path
    if not name:
        raise Invalid("A filename is required.")
    if not data:
        raise Invalid("The document is empty.")
    if len(data) > MAX_DOCUMENT_BYTES:
        raise PayloadTooLarge(
            f"The document is {len(data)} bytes; the limit is {MAX_DOCUMENT_BYTES}."
        )
    return name


async def ingest_document(store, filename: str, data: bytes) -> DocumentResponse:
    """Validate, ingest, and answer in the shared shape.

    Both failure mappings are here rather than at the call sites. An unsupported format is
    the caller's mistake (`Invalid`); an unreachable embedding server is not
    (`DependencyUnavailable`), and telling them apart is the difference between "fix your
    file" and "try again later".
    """
    from research_engine.embeddings import EmbeddingsUnavailable

    name = clean_upload(filename, data)
    try:
        result = await store.ingest(name, data)
    except ValueError as e:  # unsupported extension, unreadable document
        raise Invalid(str(e)) from e
    except EmbeddingsUnavailable as e:
        raise DependencyUnavailable(str(e)) from e
    return ingested_response(result)


def ingested_response(result) -> DocumentResponse:
    """`Ingested` → the client shape.

    `doc_id` is `None` when the store recognised the document and skipped it; the server
    has always reported that as the literal `"skip"`, and a client distinguishes it from a
    real id by value.
    """
    return DocumentResponse(
        id=result.doc_id or "skip",
        filename=result.filename,
        chunks=result.chunks_written,
    )


def document_response(row: dict) -> DocumentResponse:
    """`CorpusStore.documents()`'s row → the client shape.

    The store's own field names are not the contract: it says `chunk_count` and
    `ingested_at` where the API says `chunks` and `created_at`. This mapping existed in
    three places — twice on the server and once on the desktop — and the desktop's copy
    also wrapped the list in `{"documents": [...]}`, which `useCorpusDocuments` types as a
    bare array, so `.length` read `undefined` and the Corpus page showed "no documents"
    for a corpus that was never empty.
    """
    return DocumentResponse(
        id=row["id"],
        filename=row["filename"],
        chunks=row["chunk_count"],
        created_at=row.get("ingested_at"),
        size_bytes=row.get("size_bytes"),
        downloadable=row.get("downloadable", False),
        origin=row.get("origin", "uploaded"),
    )


def status_response(stat: dict) -> CorpusStatusResponse:
    """`CorpusStore.status()` → the client shape.

    The top-level `chunks` total is computed here because the store does not carry one,
    and the desktop's copy of this route never summed it at all.
    """
    return CorpusStatusResponse(**{**stat, "chunks": sum(stat["chunks_by_model"].values())})
