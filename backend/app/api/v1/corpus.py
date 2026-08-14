"""
Corpus endpoints (docs/12 M10).

Manages project-scoped airgapped corpora. Each project has its own SQLite database
for isolating documents and embeddings.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
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
    os.makedirs(settings.corpus_dir, exist_ok=True)
    db_path = Path(settings.corpus_dir) / f"corpus_{project_id}.sqlite"
    # We resolve the embedder to whatever the deployment defaults to.
    embedder = await embeddings_for(None)
    return CorpusStore(db_path, embedder)


class DocumentResponse(BaseModel):
    id: str
    filename: str
    chunks: int
    created_at: str | None = None


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
        )
        for d in docs
    ]


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
