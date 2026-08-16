"""
The airgapped corpus: a closed document set as the run's only evidence source
(docs/12 M10, docs/13 §8).

Two things live here:

1. **The installation seam.** A `Corpus` port held in a `ContextVar`, exactly like
   `cache.py` and `events.py` — because `retrievers.search` and `read_webpage` reach
   for it from inside tools, where no state-threading can arrive. When
   `RunConfig.corpus_mode` is set, `retrievers.search` delegates here exclusively and
   `read_webpage` refuses everything that is not a `corpus://` URL. The graph does not
   change; the executor still just searches and reads.

2. **The reference implementation.** `CorpusStore`: ingest (PDF/MD/TXT) → extract →
   chunk with exact offsets → embed through the `Embeddings` port → brute-force cosine
   over a SQLite file. SQLite + numpy rather than a vector extension because the
   desktop host has no pgvector and a laptop corpus (the M10 DoD is 500 documents)
   scans in milliseconds — an index would be complexity without a customer.

The location contract is the point of the whole milestone: every chunk stores the
verbatim span `[start, end)` of its document's extracted text, search results carry
`corpus://<doc-id>#page=N&chars=S-E` URLs, and `read` resolves one back to the text at
exactly that spot. "Every citation resolves to an exact document location" (DoD) is
therefore enforced by the schema, not by the model's behaviour.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sqlite3
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

import structlog

from research_engine.chunking import chunk_document
from research_engine.documents import extract_document
from research_engine.embeddings import EmbeddingsUnavailable
from research_engine.ports import Corpus, Embeddings
from research_engine.runconfig import get_run_config

logger = structlog.get_logger()

_CORPUS_SCHEME = "corpus"

# One document, one embedding batch: keep peak memory flat by never holding more than
# this many chunk vectors at once during ingestion (M10 DoD: no OOM at 500 documents).
_EMBED_BATCH = 32

# How much context `read` returns around the cited span — enough to see the sentence
# the quote sits in, small enough to stay a cheap tool observation.
_READ_CONTEXT_CHARS = 600
_READ_MAX_CHARS = 8000


# ── The seam ─────────────────────────────────────────────────────────────────────


class NoCorpus:
    """The default: no corpus is installed. Refuses, loudly.

    In corpus-only mode a silent empty result set would produce a report with no
    sources — the exact "confident nonsense" failure the Embeddings port documents.
    Raising lets `web_search` surface the misconfiguration to the agent and the log.
    """

    async def search(self, query: str, max_results: int) -> list[dict]:  # noqa: ARG002
        raise RuntimeError(
            "Corpus-only mode is active but no corpus is installed. Ingest documents "
            "first (POST /api/v1/corpus/documents), or disable corpus-only mode."
        )

    async def read(self, url: str) -> dict:
        return {"url": url, "title": "", "text": "", "error": "no corpus is installed"}


_NO_CORPUS: Corpus = NoCorpus()

_corpus: ContextVar[Corpus] = ContextVar("engine_corpus", default=_NO_CORPUS)


def set_corpus(corpus: Corpus):
    """Install a corpus for the current context. Returns a token for `reset_corpus`."""
    return _corpus.set(corpus)


def reset_corpus(token) -> None:
    _corpus.reset(token)


def get_corpus() -> Corpus:
    return _corpus.get()


# ── The URL scheme ───────────────────────────────────────────────────────────────
#
# corpus://<document-id>#chars=<start>-<end>[&page=<n>]
#
# The fragment is the exact location: offsets into the document's extracted text,
# plus the page when the document has pages. Deliberately NOT an http(s) URL — a
# scheme the SSRF guard and any browser would refuse keeps corpus locations from
# ever being fetched, fetched-against, or spoofed by an injected web result.


def corpus_url(doc_id: str, *, start: int, end: int, page: int | None) -> str:
    fragment = f"chars={start}-{end}"
    if page is not None:
        fragment += f"&page={page}"
    return f"{_CORPUS_SCHEME}://{doc_id}#{fragment}"


@dataclass(frozen=True)
class CorpusLocation:
    """A parsed corpus URL: which document, which span, which page (if any)."""

    doc_id: str
    start: int
    end: int
    page: int | None


def parse_corpus_url(url: str) -> CorpusLocation | None:
    """Parse a corpus URL, or None when the string is not one (fail closed)."""
    parts = urlsplit(url)
    if parts.scheme != _CORPUS_SCHEME or not parts.netloc:
        return None
    match = re.fullmatch(r"chars=(\d+)-(\d+)(?:&page=(\d+))?", parts.fragment)
    if match is None:
        return None
    start, end = int(match.group(1)), int(match.group(2))
    if end <= start:
        return None
    page = int(match.group(3)) if match.group(3) else None
    return CorpusLocation(doc_id=unquote(parts.netloc), start=start, end=end, page=page)


# ── The store ────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS corpus_documents (
    id          TEXT PRIMARY KEY,
    filename    TEXT NOT NULL,
    kind        TEXT NOT NULL,
    sha256      TEXT NOT NULL,
    text        TEXT NOT NULL,
    page_starts TEXT NOT NULL,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    ingested_at TEXT NOT NULL,
    -- The original upload, verbatim. Extracted `text` is what the agents search; this is
    -- what a human opens. Without it the UI could only offer "view extracted text", which
    -- is not the same as opening your own PDF. Nullable on purpose: documents ingested
    -- before this column existed keep working and simply cannot be downloaded.
    blob        BLOB
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_corpus_doc_dedupe
    ON corpus_documents (filename, sha256);
CREATE TABLE IF NOT EXISTS corpus_chunks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id     TEXT NOT NULL REFERENCES corpus_documents(id) ON DELETE CASCADE,
    chunk_index     INTEGER NOT NULL,
    start           INTEGER NOT NULL,
    "end"           INTEGER NOT NULL,
    page            INTEGER,
    text            TEXT NOT NULL,
    embedding       BLOB NOT NULL,
    embedding_model TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_corpus_chunks_doc ON corpus_chunks (document_id);
"""


@dataclass(frozen=True)
class Ingested:
    """What one ingestion attempt did. `skipped` is a success, not a failure."""

    doc_id: str | None = None
    filename: str = ""
    chunks_written: int = 0
    skipped: bool = False
    reason: str | None = None


class CorpusStore:
    """SQLite vector store + retrieval connector (the `Corpus` port, implemented).

    SQLite access follows `local.SqliteCache`'s pattern: stdlib `sqlite3`, a fresh
    short-lived connection per operation, blocking work on a worker thread. One file,
    WAL mode, foreign keys ON so deleting a document deletes its chunks.

    Vectors are stored as little-endian float32 blobs and compared by brute-force
    cosine. Retrieval filters on `embedding_model` for the same reason project memory
    does: vectors from different models are not comparable, and ranking them together
    would return confident nonsense rather than an obvious error.
    """

    def __init__(self, path: str | Path, embedder: Embeddings) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._embedder = embedder
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            self._migrate(conn)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Bring an existing corpus file up to the current schema.

        `CREATE TABLE IF NOT EXISTS` is a no-op on a database that already has the table,
        so a new column never reaches corpora created before it existed. Each corpus is a
        standalone SQLite file owned by one project, with no Alembic equivalent — this is
        the migration seam for them. Additive and idempotent: check, then add.
        """
        have = {row[1] for row in conn.execute("PRAGMA table_info(corpus_documents)")}
        if "blob" not in have:
            conn.execute("ALTER TABLE corpus_documents ADD COLUMN blob BLOB")

    @property
    def embedder(self) -> Embeddings:
        return self._embedder

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        # OFF by default in SQLite; the cascade on corpus_chunks needs this ON.
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    # -- ingestion ---------------------------------------------------------------

    async def ingest(self, filename: str, data: bytes) -> Ingested:
        """Extract, chunk, embed, and store one document. Idempotent per content.

        Phase split matters: extraction and the dedupe check run on a worker thread
        (a 25 MB PDF parse must not block the loop), embedding runs on the CALLER'S
        loop (an async httpx client cannot live inside a `to_thread`), and the write
        goes back to a thread.
        """
        prepared = await asyncio.to_thread(self._prepare_sync, filename, data)
        if isinstance(prepared, Ingested):  # skipped (duplicate) — nothing to embed
            return prepared
        doc_id, text, page_starts, kind, digest, chunks = prepared

        vectors = await self._embed_chunks([c.text for c in chunks])
        width = len(vectors[0])
        if any(len(v) != width for v in vectors):
            raise RuntimeError("Embedder returned vectors of inconsistent width.")

        await asyncio.to_thread(
            self._write_sync,
            doc_id,
            filename,
            text,
            page_starts,
            kind,
            digest,
            chunks,
            vectors,
            data,
        )
        logger.info(
            "corpus_ingested",
            filename=filename,
            doc_id=doc_id,
            chunks=len(chunks),
            model=self._embedder.model_id,
        )
        return Ingested(doc_id=doc_id, filename=filename, chunks_written=len(chunks))

    def _prepare_sync(
        self, filename: str, data: bytes
    ) -> Ingested | tuple[str, str, list[int], str, str, list]:
        text, page_starts, kind = extract_document(filename, data)
        digest = hashlib.sha256(data).hexdigest()

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM corpus_documents WHERE filename = ? AND sha256 = ?",
                (filename, digest),
            ).fetchone()
        if existing:
            # Same bytes under the same name: re-ingesting would double the corpus
            # and the embedding spend for zero new information.
            return Ingested(
                doc_id=existing[0],
                filename=filename,
                skipped=True,
                reason="identical content already ingested",
            )

        chunks = chunk_document(text, page_starts=page_starts)
        if not chunks:
            return Ingested(filename=filename, skipped=True, reason="no chunks produced")
        return str(uuid.uuid4()), text, page_starts, kind, digest, chunks

    def _write_sync(
        self,
        doc_id: str,
        filename: str,
        text: str,
        page_starts: list[int],
        kind: str,
        digest: str,
        chunks: list,
        vectors: list[list[float]],
        blob: bytes | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO corpus_documents "
                "(id, filename, kind, sha256, text, page_starts, chunk_count, ingested_at, "
                "blob) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    doc_id,
                    filename,
                    kind,
                    digest,
                    text,
                    json.dumps(page_starts),
                    len(chunks),
                    datetime.now(UTC).isoformat(),
                    blob,
                ),
            )
            conn.executemany(
                "INSERT INTO corpus_chunks "
                '(document_id, chunk_index, start, "end", page, text, embedding, '
                "embedding_model) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        doc_id,
                        index,
                        chunk.start,
                        chunk.end,
                        chunk.page,
                        chunk.text,
                        _pack(vector),
                        self._embedder.model_id,
                    )
                    for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
                ],
            )

    async def _embed_chunks(self, texts: list[str]) -> list[list[float]]:
        """Batched embedding; a width mismatch or count mismatch fails the ingestion."""
        vectors: list[list[float]] = []
        for start in range(0, len(texts), _EMBED_BATCH):
            batch = await self._embedder.embed(texts[start : start + _EMBED_BATCH])
            if len(batch) != len(texts[start : start + _EMBED_BATCH]):
                raise RuntimeError(
                    f"Embedder returned {len(batch)} vectors for "
                    f"{len(texts[start : start + _EMBED_BATCH])} chunks."
                )
            vectors.extend(batch)
        return vectors

    # -- retrieval (the Corpus port) ────────────────────────────────────────────

    async def search(self, query: str, max_results: int) -> list[dict]:
        # The query embedding is the ONLY model call retrieval makes — the store itself
        # never opens a socket. That made corpus mode's zero-egress claim rest entirely on
        # the host having configured a *local* embedder, and nothing checked: with
        # EMBEDDINGS_PROVIDER=google|openai the server embedded every corpus query through
        # a hosted API while docs/12 M10 advertised "no network calls at all, verified by
        # test". The test could not catch it either — it injects a FakeEmbeddings, so the
        # one call that egresses was the one call stubbed out. Enforce, don't trust.
        self._require_local_embedder_in_corpus_mode()
        query_vector = (await self._embedder.embed([query]))[0]
        return await asyncio.to_thread(self._search_sync, query_vector, max_results)

    def _require_local_embedder_in_corpus_mode(self) -> None:
        """Refuse to embed off-machine while claiming to be airgapped (docs/12 M10).

        Only corpus-only mode makes the zero-egress promise, so this is silent otherwise:
        a hosted embedder is perfectly correct for ordinary project memory.
        """
        if not get_run_config().corpus_mode:
            return
        if getattr(self._embedder, "is_local", False):
            return
        raise EmbeddingsUnavailable(
            f"Corpus-only mode guarantees zero network calls, but the configured "
            f"embeddings provider '{self._embedder.model_id}' is remote — every corpus "
            f"search would send the query off this machine. Set EMBEDDINGS_PROVIDER=ollama "
            f"with a local OLLAMA_BASE_URL, or run without corpus-only mode."
        )

    def _search_sync(self, query_vector: list[float], max_results: int) -> list[dict]:
        import numpy as np

        with self._connect() as conn:
            rows = conn.execute(
                'SELECT c.id, c.document_id, c.start, c."end", c.page, c.text, c.embedding, '
                "d.filename "
                "FROM corpus_chunks c JOIN corpus_documents d ON d.id = c.document_id "
                "WHERE c.embedding_model = ?",
                (self._embedder.model_id,),
            ).fetchall()

        if not rows:
            # Distinguish "empty corpus" from "wrong model" — both fail the run, but
            # the remedy differs (ingest documents vs re-index after a model change).
            with self._connect() as conn:
                other = conn.execute(
                    "SELECT embedding_model, COUNT(*) FROM corpus_chunks GROUP BY 1"
                ).fetchall()
            if other:
                models = ", ".join(f"{m} ({n} chunks)" for m, n in other)
                raise RuntimeError(
                    f"Corpus was indexed with a different embedding model ({models}); "
                    f"current model is '{self._embedder.model_id}'. Re-ingest to re-index."
                )
            raise RuntimeError(
                "The corpus is empty. Ingest documents before running corpus-only research."
            )

        matrix = np.stack([np.frombuffer(row[6], dtype=np.float32) for row in rows])
        if matrix.shape[1] != len(query_vector):
            raise RuntimeError(
                f"Stored vectors are {matrix.shape[1]}-wide but the query embedded to "
                f"{len(query_vector)} dimensions — the embedding model changed."
            )

        # Cosine similarity. Distance 1.0 is the memory-service cutoff's mirror:
        # orthogonal-or-worse matches are noise, not evidence.
        q = np.asarray(query_vector, dtype=np.float32)
        q_norm = q / (np.linalg.norm(q) or 1.0)
        norms = np.linalg.norm(matrix, axis=1)
        norms[norms == 0] = 1.0
        scores = (matrix / norms[:, None]) @ q_norm

        ranked = np.argsort(-scores)[: max_results * 4]
        results: list[dict] = []
        seen_docs: set[str] = set()
        for idx in ranked:
            if scores[idx] <= 0.0:
                break
            row = rows[int(idx)]
            doc_id = row[1]
            # One hit per document per search: two chunks from the same file are not
            # two independent sources, and the synthesizer counts URLs as sources.
            if doc_id in seen_docs:
                continue
            seen_docs.add(doc_id)
            results.append(
                {
                    "title": row[7],
                    "url": corpus_url(doc_id, start=row[2], end=row[3], page=row[4]),
                    "snippet": row[5],
                }
            )
            if len(results) >= max_results:
                break
        return results

    async def read(self, url: str) -> dict:
        return await asyncio.to_thread(self._read_sync, url)

    def _read_sync(self, url: str) -> dict:
        location = parse_corpus_url(url)
        if location is None:
            return {"url": url, "title": "", "text": "", "error": "not a valid corpus URL"}

        with self._connect() as conn:
            row = conn.execute(
                "SELECT filename, text FROM corpus_documents WHERE id = ?",
                (location.doc_id,),
            ).fetchone()
        if row is None:
            return {"url": url, "title": "", "text": "", "error": "document not found in corpus"}

        filename, text = row
        if location.start >= len(text) or location.end > len(text):
            # The span no longer fits its document — refuse rather than returning a
            # shifted window that would look right but cite the wrong place.
            return {"url": url, "title": filename, "text": "", "error": "location out of range"}

        # Expand to surrounding context on whole-word boundaries.
        lo = max(location.start - _READ_CONTEXT_CHARS, 0)
        hi = min(location.end + _READ_CONTEXT_CHARS, len(text))
        while lo > 0 and not text[lo - 1].isspace():
            lo -= 1
        while hi < len(text) and not text[hi].isspace():
            hi += 1
        window = text[lo:hi]
        if len(window) > _READ_MAX_CHARS:
            window = window[:_READ_MAX_CHARS]

        where = (
            f"page {location.page}, chars {location.start}-{location.end}"
            if location.page is not None
            else f"chars {location.start}-{location.end}"
        )
        return {
            "url": url,
            "title": f"{filename} ({where})",
            "text": window,
            "error": None,
        }

    # -- management ----------------------------------------------------------------

    async def documents(self) -> list[dict]:
        return await asyncio.to_thread(self._documents_sync)

    def _documents_sync(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, filename, kind, chunk_count, ingested_at, "
                # length() on a BLOB reads its size without loading the bytes, so listing
                # a corpus of 25 MB PDFs stays cheap. `downloadable` is derived rather
                # than assumed: documents ingested before the blob column existed have
                # NULL here, and the UI must offer Open only where a file really exists.
                "       length(blob) FROM corpus_documents "
                "ORDER BY ingested_at"
            ).fetchall()
        return [
            {
                "id": row[0],
                "filename": row[1],
                "kind": row[2],
                "chunk_count": row[3],
                "ingested_at": row[4],
                "size_bytes": row[5],
                "downloadable": row[5] is not None,
            }
            for row in rows
        ]

    async def blob(self, doc_id: str) -> tuple[bytes, str, str] | None:
        """The original upload as `(bytes, filename, kind)`, or None.

        None covers both "no such document" and "stored before originals were kept" —
        the caller cannot serve a file in either case, and distinguishing them would only
        leak whether an id exists.
        """
        return await asyncio.to_thread(self._blob_sync, doc_id)

    def _blob_sync(self, doc_id: str) -> tuple[bytes, str, str] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT blob, filename, kind FROM corpus_documents WHERE id = ?", (doc_id,)
            ).fetchone()
        if row is None or row[0] is None:
            return None
        return bytes(row[0]), row[1], row[2]

    async def delete(self, doc_id: str) -> bool:
        return await asyncio.to_thread(self._delete_sync, doc_id)

    def _delete_sync(self, doc_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM corpus_documents WHERE id = ?", (doc_id,))
        return cursor.rowcount > 0

    async def status(self) -> dict:
        return await asyncio.to_thread(self._status_sync)

    def _status_sync(self) -> dict:
        with self._connect() as conn:
            docs = conn.execute("SELECT COUNT(*) FROM corpus_documents").fetchone()[0]
            by_model = conn.execute(
                "SELECT embedding_model, COUNT(*) FROM corpus_chunks GROUP BY 1 ORDER BY 1"
            ).fetchall()
        return {
            "documents": docs,
            "chunks_by_model": {model: count for model, count in by_model},
            "current_model": self._embedder.model_id,
        }


def _pack(vector: list[float]) -> bytes:
    import numpy as np

    return np.asarray(vector, dtype=np.float32).tobytes()
