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
    # The logical document this row is a revision of, and which revision it is. `doc_key`
    # is an opaque uuid minted by the store — never derived from the filename, because two
    # unrelated papers can legitimately share one. It is returned because it is the only
    # way a caller can later say "this upload replaces that document"; nothing else in the
    # response identifies the document rather than the version.
    doc_key: str | None = None
    version: int | None = None
    # Whether retrieval can still reach this row. A superseded version stays readable, so
    # citations made against it keep resolving, but it is no longer offered as evidence.
    is_current: bool = True


class CorpusStatusResponse(BaseModel):
    documents: int
    chunks: int
    chunks_by_model: dict[str, int]
    current_model: str
    # Which corpus this is and what state it is in. A file path is host-specific (and on the
    # desktop it moved in 3.1), so a path could never name it on both hosts; identity that
    # lives in the data can.
    corpus_id: str | None = None
    corpus_version: int | None = None


class ExtractedTextResponse(BaseModel):
    """The text a document's citations are verified against, for the citation preview."""

    filename: str
    kind: str
    text: str
    segments: list[list] = []
    extraction_mode: str = "verbatim"


class FolderResponse(BaseModel):
    id: str
    parent_id: str | None = None
    name: str


class MembershipResponse(BaseModel):
    doc_key: str
    folder_id: str
    display_name: str


class CorpusTreeResponse(BaseModel):
    """Folders, documents, and which document is in which folder (RFC V3.1 §7.1).

    Flat lists rather than a nested tree, so the client builds the tree once and the shape
    stays the same on both hosts. A document with no membership sits at the root.
    """

    folders: list[FolderResponse]
    documents: list[DocumentResponse]
    memberships: list[MembershipResponse]


class FolderCreateRequest(BaseModel):
    name: str
    parent_id: str | None = None


class FolderUpdateRequest(BaseModel):
    """`name` renames; `parent_id` moves (null moves to the root). Omit a field to keep it."""

    name: str | None = None
    parent_id: str | None = None
    move: bool = False


class FolderDeleteResponse(BaseModel):
    folders_deleted: int
    documents_deleted: int
    versions_deleted: int
