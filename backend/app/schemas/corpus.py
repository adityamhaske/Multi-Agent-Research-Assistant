"""
Response bodies for the per-project corpus surface.

**Why these live in `app/schemas/` rather than beside the routes.** The per-project corpus
path is the canonical product contract and both hosts serve it — the server over one
SQLite file per project, the desktop over its single `corpus.sqlite`. That difference is
infrastructure and stays; the *shape* the client reads must not differ, and it did: the
desktop returned `CorpusStore.documents()`'s own field names inside a `{"documents": [...]}`
wrapper, `hooks/queries.ts::useCorpusDocuments` types the response as a bare array, and the
Corpus page rendered "no documents" for a corpus that was never empty. No crash, no failing
test (AGENTS.md).

The desktop could not declare these models while they sat in `app/api/v1/corpus.py`: that
module imports `app.config`, which an installed app cannot build (#50). So the shapes moved
here and the route module re-exports them — the same relocation `download_headers` already
made, for the same reason.

Nothing in this module may import `app.config`, `app.db`, or anything reaching them.
"""

from __future__ import annotations

from pydantic import BaseModel


class DocumentResponse(BaseModel):
    id: str
    filename: str
    chunks: int
    created_at: str | None = None
    size_bytes: int | None = None
    # False for documents ingested before originals were retained. The UI keys its
    # Open/Download affordance off this rather than assuming every row has a file.
    downloadable: bool = False
    # "uploaded" or "generated" (app/services/report_corpus.py). The UI badges a
    # generated document distinctly and must not let a user believe it is a source the
    # way an upload is — retrieval already refuses to cite one (research_engine/corpus.py).
    origin: str = "uploaded"


class CorpusStatusResponse(BaseModel):
    documents: int
    chunks: int
    chunks_by_model: dict[str, int]
    current_model: str
