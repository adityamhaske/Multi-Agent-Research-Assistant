"""
Freezing a selected-files run's selection (internal/rfcs/V3.1-corpus-scope.md §8.2).

A selection is control-plane data, resolved once — when the run is created — into the exact
document *versions* the run may read, and stored on the row. Every later step reads the row:
the plan gate, a resume, the persist check, the bundle. Nothing re-resolves it, so a document
superseded, deleted or moved after creation can never widen or shift what the run may read.

Shared by both hosts: the server's `runs.create_run` and the desktop sidecar's delegated
route call the same handler, which calls this. It imports nothing host-specific (no
`app.config`, no database), so the packaged sidecar can import it (`test_sidecar_startup`).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urlsplit


class SelectionError(ValueError):
    """A selection that cannot be frozen. `code` is the stable, named reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


#: Folders arrive with the folder model (PR-14). Until then no folder id resolves, and a
#: request naming one is refused as not found rather than silently ignored.
_NO_FOLDERS: dict[str, list[str]] = {}


async def freeze_selection(
    store: Any,
    *,
    folder_ids: list[str] | None,
    doc_keys: list[str] | None,
    whole_corpus: bool,
) -> dict:
    """Resolve a selection request to its frozen record, or raise `SelectionError`.

    `whole_corpus` is a corpus-only run with no explicit selection: today's meaning (the
    project's whole corpus), frozen like any selection so the run reads a fixed set.
    `store` is the project's corpus, or `None` when the project has none yet.
    """
    folder_ids = list(folder_ids or [])
    doc_keys = list(doc_keys or [])
    if not whole_corpus and not folder_ids and not doc_keys:
        raise SelectionError("selection_empty", "Select at least one file or folder.")

    unknown_folders = [f for f in folder_ids if f not in _NO_FOLDERS]
    if unknown_folders:
        # Says how many, never which: an id that exists in another project and one that
        # exists nowhere must look the same from here.
        raise SelectionError(
            "selection_not_found", "Some selected files or folders are not in this project."
        )

    requested_keys = sorted(set(doc_keys))
    if store is None:
        resolved: list[dict] = []
    else:
        resolved = await store.current_versions(None if whole_corpus else requested_keys)

    if not whole_corpus:
        found = {item["doc_key"] for item in resolved}
        if set(requested_keys) - found:
            raise SelectionError(
                "selection_not_found",
                "Some selected files are not in this project, or have no current version.",
            )

    if not resolved:
        raise SelectionError(
            "selection_resolved_empty",
            "The selection contains no documents that can be read. Upload a document, or "
            "choose files that are not auto-saved reports.",
        )

    corpus_id = corpus_version = None
    if store is not None:
        corpus_id, corpus_version = await store.identity()
    return {
        "requested": {
            "folder_ids": sorted(set(folder_ids)),
            "doc_keys": requested_keys,
            "whole_corpus": whole_corpus,
        },
        "resolved": resolved,
        "corpus_id": corpus_id,
        "corpus_version": corpus_version,
    }


def allowed_ids(selection: dict | None) -> frozenset[str] | None:
    """The document-version ids a frozen selection admits, or `None` for no selection.

    An unreadable record yields an empty set, never `None`: `ScopedCorpus` refuses an empty
    set loudly, whereas `None` would mean "no selection" and let the run read everything.
    """
    if selection is None:
        return None
    try:
        return frozenset(str(item["document_id"]) for item in selection["resolved"])
    except KeyError, TypeError:
        return frozenset()


def document_id_of(url: str) -> str | None:
    """The document-version id a `corpus://` URL names, or `None` for any other URL.

    Only the identity, never the span: what a selection admits is a document version, and
    `Source.corpus_document_id` stores the whole fragment beside it (audit C3), so callers
    must not compare that column to a selection directly.
    """
    parts = urlsplit(url or "")
    if parts.scheme != "corpus" or not parts.netloc:
        return None
    return unquote(parts.netloc)


def violations(selection: dict | None, urls: list[str]) -> list[str]:
    """Every URL in `urls` that a run with this selection could not legitimately cite.

    The defence in depth behind `ScopedCorpus` (internal/rfcs/V3.1-corpus-scope.md §8.5):
    the port should make a violation impossible, so finding one means a path around it
    exists. In a run with a selection, a source is admissible only if it is a corpus URL
    naming a selected version — a web URL is a violation too, since a selected-files run
    reads nothing else. A run with no selection has nothing to violate.
    """
    allowed = allowed_ids(selection)
    if allowed is None:
        return []
    bad: list[str] = []
    for url in urls:
        doc = document_id_of(url)
        if doc is None or doc not in allowed:
            bad.append(url)
    return sorted(set(bad))
