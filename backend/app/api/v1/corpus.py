"""
Corpus endpoints (docs/12 M10).

Manages project-scoped airgapped corpora. Each project has its own SQLite database
for isolating documents and embeddings.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import embeddings_for
from app.api.v1.projects import resolve_project
from app.config import settings
from app.db.base import get_db
from app.dependencies import get_current_user
from app.models.user import User

# Re-exported, not restated — see `app/schemas/corpus.py` for why the shapes moved, and
# `app/services/corpus_ingest.py` for the validation and shaping both hosts share.
from app.schemas.corpus import CorpusStatusResponse, DocumentResponse
from app.services import corpus_ingest

# The download response policy lives in a stdlib-only module so the desktop sidecar can
# import it without dragging this route's `app.config` chain in with it (#50). Re-exported
# here because this module is where callers and tests have always found it.
from app.services.document_headers import (  # noqa: F401  (re-export)
    _MEDIA_TYPES,
    download_headers,
    media_type_for,
)
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


@router.post("/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    project_id: uuid.UUID,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Ingest a new document into the project's corpus.

    Validation, failure mapping and the response shape come from
    `app.services.corpus_ingest` — the one home for them, because the desktop serves this
    same path and each host used to choose its own status codes for the same rejection.
    """
    # Enforce isolation: verify the user owns the project
    await resolve_project(db, current_user.id, project_id)

    store = await _get_corpus_store(project_id)
    return await corpus_ingest.ingest_document(store, file.filename, await file.read())


@router.get("/documents", response_model=list[DocumentResponse])
async def list_documents(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all documents in the project's corpus."""
    await resolve_project(db, current_user.id, project_id)

    store = await _get_corpus_store(project_id)
    return [corpus_ingest.document_response(d) for d in await store.documents()]


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

    Content-Type and disposition come from `download_headers`, which is where the rule
    that an uploaded document must not render in this origin now lives — along with the
    single narrow exception (PDF) that in-place preview needs.
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
    return Response(
        content=data,
        media_type=media_type_for(kind),
        headers=download_headers(kind, filename),
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
    if not await store.delete(doc_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=corpus_ingest.DOCUMENT_NOT_FOUND
        )
    # Explicit, because returning `None` from a 204 route makes FastAPI send
    # `content-type: application/json` with an empty body — a response that does not parse.
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/status", response_model=CorpusStatusResponse)
async def get_status(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the status of the project's corpus."""
    await resolve_project(db, current_user.id, project_id)

    store = await _get_corpus_store(project_id)
    return corpus_ingest.status_response(await store.status())
