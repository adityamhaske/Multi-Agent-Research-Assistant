"""
Corpus endpoints (docs/12 M10).

Manages project-scoped airgapped corpora. Each project has its own SQLite database
for isolating documents and embeddings.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import embeddings_for
from app.api.v1.projects import resolve_project
from app.config import settings
from app.db.base import get_db
from app.dependencies import get_current_user
from app.models.user import User
from research_engine.corpus import CorpusStore

logger = structlog.get_logger()
router = APIRouter(prefix="/projects/{project_id}/corpus", tags=["Corpus"])


async def _get_corpus_store(project_id: uuid.UUID) -> CorpusStore:
    """Returns a CorpusStore instance for the given project."""
    # `corpus_path`, not `corpus_dir`: the raw setting is relative by default and resolves
    # against the working directory, so the same project got a different corpus depending
    # on where the process was started from (app/config.py).
    settings.corpus_path.mkdir(parents=True, exist_ok=True)
    db_path = settings.corpus_path / f"corpus_{project_id}.sqlite"
    # We resolve the embedder to whatever the deployment defaults to.
    embedder = await embeddings_for(None)
    return CorpusStore(db_path, embedder)


class DocumentResponse(BaseModel):
    id: str
    filename: str
    chunks: int
    created_at: str | None = None
    size_bytes: int | None = None
    # False for documents ingested before originals were retained. The UI keys its
    # Open/Download affordance off this rather than assuming every row has a file.
    downloadable: bool = False


class CorpusStatusResponse(BaseModel):
    documents: int
    chunks: int
    chunks_by_model: dict[str, int]
    current_model: str


@router.post("/documents", response_model=DocumentResponse)
async def upload_document(
    project_id: uuid.UUID,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Ingest a new document into the project's corpus."""
    # Enforce isolation: verify the user owns the project
    await resolve_project(db, current_user.id, project_id)

    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No filename provided")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")

    store = await _get_corpus_store(project_id)
    try:
        ingested = await store.ingest(file.filename, data)
        return DocumentResponse(
            id=ingested.doc_id or "skip",
            filename=ingested.filename,
            chunks=ingested.chunks_written,
        )
    except ValueError as e:
        # e.g., unsupported extension
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/documents", response_model=list[DocumentResponse])
async def list_documents(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all documents in the project's corpus."""
    await resolve_project(db, current_user.id, project_id)

    store = await _get_corpus_store(project_id)
    docs = await store.documents()
    return [
        DocumentResponse(
            id=d["id"],
            filename=d["filename"],
            chunks=d["chunk_count"],
            created_at=d["ingested_at"],
            size_bytes=d.get("size_bytes"),
            downloadable=d.get("downloadable", False),
        )
        for d in docs
    ]


@router.get("/documents/{doc_id}/download")
async def download_document(
    project_id: uuid.UUID,
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Serve the original uploaded file so it can be opened in its native application.

    `resolve_project` runs first and is the authorization boundary: document ids are
    opaque but guessable in principle, and without the project check any authenticated
    user could read another user's corpus by id.

    Content-Type is derived from the stored `kind` rather than echoed from the upload —
    a client-supplied type is attacker-controlled, and reflecting it invites content
    sniffing on a file another user uploaded. `Content-Disposition: attachment` for the
    same reason: never render an uploaded document inline in this origin.
    """
    await resolve_project(db, current_user.id, project_id)

    store = await _get_corpus_store(project_id)
    found = await store.blob(doc_id)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No stored file for this document. Documents added before file "
            "retention was enabled keep their searchable text but not the original.",
        )
    data, filename, kind = found
    media_type = {
        "pdf": "application/pdf",
        "md": "text/markdown",
        "txt": "text/plain",
    }.get(kind, "application/octet-stream")
    # Quote and strip the filename: it came from an upload, and a raw newline or quote
    # here would let a crafted name inject extra response headers.
    safe_name = filename.replace("\\", "_").replace('"', "_").replace("\n", "_").replace("\r", "_")
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    project_id: uuid.UUID,
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a document from the project's corpus."""
    await resolve_project(db, current_user.id, project_id)

    store = await _get_corpus_store(project_id)
    deleted = await store.delete(doc_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")


@router.get("/status", response_model=CorpusStatusResponse)
async def get_status(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the status of the project's corpus."""
    await resolve_project(db, current_user.id, project_id)

    store = await _get_corpus_store(project_id)
    stat = await store.status()
    stat["chunks"] = sum(stat["chunks_by_model"].values())
    return CorpusStatusResponse(**stat)
