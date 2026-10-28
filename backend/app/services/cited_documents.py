"""
Reopening a document a run or session cited, wherever that document lives now
(internal/rfcs/V3.1-corpus-scope.md §7.3, "Historical citations across projects"; AC-27).

On the desktop, every document uploaded before 3.1 moved into one project, "Documents from
before 3.1". A report in any other project that quoted one of them keeps its evidence, but
its own project's corpus no longer holds the file. So the per-project routes answer "no
longer in the corpus" for a document that still exists.

This module is the narrow way back, and it deliberately grants no access to the project
the document now lives in:
- **What may be opened** is decided by the caller's own run or session: only a version it
  recorded as a corpus source, by id. Where it recorded a hash (a 3.1 selection), the stored
  version must still match it.
- **Where to look** is decided by the host, from the row: the run's own project, then on the
  desktop the legacy project. Never from a project id the client supplies. When the run
  recorded which corpus it read, a store with any other identity is skipped.
- **What comes back** is that one version, through the store's own `extracted`/`blob`.
  There is no listing, no search and no other version.

Every refusal reads the same as a missing document, so a probe cannot tell "not yours"
from "not there". Host-agnostic: no FastAPI here, so the server and the desktop share it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from app.services.corpus_selection import document_id_of


def no_other_projects() -> list[uuid.UUID]:
    """Where else a cited document may live on the server: nowhere. Its projects were never
    pooled, so a run's corpus documents are always in its own project's store. The desktop
    passes its legacy project instead (`desktop/corpus_layout.py::legacy_project_id`)."""
    return []


def recorded_ids(urls: Iterable[str | None]) -> set[str]:
    """The document-version ids a run or session cited, from its recorded source URLs."""
    return {doc for url in urls if (doc := document_id_of(url or "")) is not None}


def recorded_hashes(selection: dict | None) -> dict[str, str]:
    """`document_id → sha256` for each version a frozen selection pinned. Empty before 3.1."""
    try:
        return {
            str(item["document_id"]): str(item["sha256"])
            for item in (selection or {}).get("resolved", [])
            if item.get("sha256")
        }
    except AttributeError, KeyError, TypeError:
        return {}


async def store_holding(
    locator,
    document_id: str,
    *,
    cited: set[str],
    hashes: dict[str, str],
    corpus_id: str | None,
    projects: list[uuid.UUID],
):
    """The store that holds `document_id` for this caller, or `None` for every refusal."""
    if document_id not in cited:
        return None
    for project_id in dict.fromkeys(projects):
        store = await locator.for_project(project_id)
        if store is None:
            continue
        if corpus_id is not None and (await store.identity())[0] != corpus_id:
            continue
        stored = await store.sha256_of(document_id)
        if stored is None:
            continue
        if document_id in hashes and stored != hashes[document_id]:
            return None
        return store
    return None
