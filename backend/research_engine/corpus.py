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
    blob        BLOB,
    -- 'uploaded' (a human added it) or 'generated' (this project's own approved report,
    -- auto-saved after the report-review gate — docs/12 M10 follow-up). Retrieval excludes
    -- 'generated' unconditionally (see `_search_sync`): without this, an approved report
    -- becomes citable evidence for the next one, and a `[n]` marker would resolve cleanly
    -- while pointing at the model's own earlier output rather than a real source — the
    -- unverifiable-citation class AGENTS.md calls P0, just laundered through a real file.
    origin      TEXT NOT NULL DEFAULT 'uploaded'
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

#: Who this corpus is, and how much has happened to it. One row.
#:
#: Identity has until now been the *file path* — one file per project on the server, one
#: flat file for the whole app on the desktop — which means a bundle could cite a corpus
#: document without being able to name the corpus it came from, and the desktop had no
#: per-project path to name. Identity that lives in the data is the same on both hosts.
#:
#: `version` is monotonic and bumped by anything that changes what retrieval can see. It is
#: what a run records so "reproduce this research" can say which corpus state produced it.
_META_SCHEMA = """
CREATE TABLE IF NOT EXISTS corpus_meta (
    corpus_id      TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    version        INTEGER NOT NULL,
    created_at     TEXT NOT NULL
);
"""

#: Corpus file schema this build writes. Bumped when `_migrate` gains a step.
_SCHEMA_VERSION = 2


class UnknownDocumentKey(LookupError):
    """A caller asked to supersede a logical document this corpus does not hold.

    Its own type because the alternative is silence: falling back to "create a new logical
    document" would answer 201 to a request that meant "replace", and the caller would
    discover months later that a corrected paper never superseded anything.
    """


@dataclass(frozen=True)
class Ingested:
    """What one ingestion attempt did. `skipped` is a success, not a failure."""

    doc_id: str | None = None
    filename: str = ""
    chunks_written: int = 0
    skipped: bool = False
    reason: str | None = None
    #: The logical document this version belongs to, and which revision it is. Returned so
    #: a caller can supersede this document later — `doc_key` is opaque and unguessable by
    #: design, so it has to come back out.
    doc_key: str | None = None
    version: int | None = None


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
        if "origin" not in have:
            conn.execute(
                "ALTER TABLE corpus_documents ADD COLUMN origin TEXT NOT NULL DEFAULT 'uploaded'"
            )

        # ── Schema 2: logical documents and versions ──────────────────────────────
        #
        # Order matters and is the whole migration: identity, then columns, then backfill,
        # then the uniqueness that backfill makes satisfiable. Creating the index first
        # would fail on any corpus that already holds rows.
        conn.executescript(_META_SCHEMA)
        if not conn.execute("SELECT 1 FROM corpus_meta").fetchone():
            conn.execute(
                "INSERT INTO corpus_meta (corpus_id, schema_version, version, created_at) "
                "VALUES (?, ?, 0, ?)",
                (str(uuid.uuid4()), _SCHEMA_VERSION, datetime.now(UTC).isoformat()),
            )
        if "doc_key" not in have:
            conn.execute("ALTER TABLE corpus_documents ADD COLUMN doc_key TEXT")
            conn.execute("ALTER TABLE corpus_documents ADD COLUMN version INTEGER")
            conn.execute("ALTER TABLE corpus_documents ADD COLUMN superseded_at TEXT")

        # Backfill: every pre-A4 row becomes its own logical document at version 1.
        #
        # Deliberately NOT grouped by filename. Two rows sharing a name may be revisions of
        # one paper or two unrelated papers, and nothing stored can tell them apart —
        # guessing would be exactly the identity inference this model exists to refuse. So
        # history is preserved as it actually is, no supersession is invented, and
        # retrieval returns precisely what it returned before. A user who knows two rows
        # are related expresses that by superseding one, which is intent rather than
        # inference.
        for (row_id,) in conn.execute(
            "SELECT id FROM corpus_documents WHERE doc_key IS NULL ORDER BY ingested_at, id"
        ).fetchall():
            conn.execute(
                "UPDATE corpus_documents SET doc_key = ?, version = 1 WHERE id = ?",
                (str(uuid.uuid4()), row_id),
            )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_corpus_doc_version "
            "ON corpus_documents (doc_key, version)"
        )

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

    async def ingest(
        self,
        filename: str,
        data: bytes,
        *,
        origin: str = "uploaded",
        doc_key: str | None = None,
    ) -> Ingested:
        """Extract, chunk, embed, and store one document version. Idempotent per content.

        `doc_key` is the only way one upload becomes a revision of another. Omitted — which
        is every caller that predates this — the upload is a **new logical document**, so
        two unrelated papers that happen to share a filename stay two documents. Supplied,
        the upload becomes the next version of that document and supersedes its
        predecessor. Nothing is inferred from the filename, the content, or anything in it:
        `filename` is version-level display metadata and may legitimately change between
        revisions of the same document.

        Phase split matters: extraction and the dedupe check run on a worker thread
        (a 25 MB PDF parse must not block the loop), embedding runs on the CALLER'S
        loop (an async httpx client cannot live inside a `to_thread`), and the write
        goes back to a thread.

        `origin` distinguishes a human upload from this project's own auto-saved report
        (`app/services/report_corpus.py`) — see the column comment in `_SCHEMA`.
        """
        prepared = await asyncio.to_thread(self._prepare_sync, filename, data, doc_key)
        if isinstance(prepared, Ingested):  # skipped (duplicate) — nothing to embed
            return prepared
        doc_id, text, page_starts, kind, digest, chunks = prepared

        vectors = await self._embed_chunks([c.text for c in chunks])
        width = len(vectors[0])
        if any(len(v) != width for v in vectors):
            raise RuntimeError("Embedder returned vectors of inconsistent width.")

        doc_key, version = await asyncio.to_thread(
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
            origin,
            doc_key,
        )
        logger.info(
            "corpus_ingested",
            filename=filename,
            doc_id=doc_id,
            chunks=len(chunks),
            model=self._embedder.model_id,
        )
        return Ingested(
            doc_id=doc_id,
            filename=filename,
            chunks_written=len(chunks),
            doc_key=doc_key,
            version=version,
        )

    def _prepare_sync(
        self, filename: str, data: bytes, doc_key: str | None = None
    ) -> Ingested | tuple[str, str, list[int], str, str, list]:
        text, page_starts, kind = extract_document(filename, data)
        digest = hashlib.sha256(data).hexdigest()

        with self._connect() as conn:
            if doc_key is not None:
                # Refuse before spending anything on embeddings. An unknown key means the
                # caller believes it is replacing something that is not here.
                if not conn.execute(
                    "SELECT 1 FROM corpus_documents WHERE doc_key = ?", (doc_key,)
                ).fetchone():
                    raise UnknownDocumentKey(doc_key)
                # Content identity is the sha, and it is scoped to this document: the same
                # bytes already standing as its current version are not a new revision,
                # whatever the file is called this time.
                existing = conn.execute(
                    "SELECT id FROM corpus_documents "
                    "WHERE doc_key = ? AND sha256 = ? AND superseded_at IS NULL",
                    (doc_key, digest),
                ).fetchone()
            else:
                existing = conn.execute(
                    "SELECT id FROM corpus_documents WHERE filename = ? AND sha256 = ?",
                    (filename, digest),
                ).fetchone()
        if existing:
            # Same bytes: re-ingesting would double the corpus and the embedding spend for
            # zero new information, and would mint a version number recording no change.
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
        origin: str = "uploaded",
        doc_key: str | None = None,
    ) -> tuple[str, int]:
        # One transaction for the whole state change: the version number, the predecessor's
        # supersession, the chunks, and the corpus counter. Anything less and a reader could
        # observe two current versions of one document, or a counter that disagrees with
        # what retrieval can see.
        with self._connect() as conn:
            now = datetime.now(UTC).isoformat()
            key = doc_key or str(uuid.uuid4())
            if doc_key is not None:
                # At most one current version per document, and it stops being current at
                # the moment its successor exists — not before, and not in another
                # transaction.
                conn.execute(
                    "UPDATE corpus_documents SET superseded_at = ? "
                    "WHERE doc_key = ? AND superseded_at IS NULL",
                    (now, doc_key),
                )
            # Allocated in the INSERT rather than read and then written, so two concurrent
            # ingests cannot both see the same MAX and mint the same number. The unique
            # index on (doc_key, version) is the backstop that turns a lost race into a
            # loud failure instead of a duplicate.
            conn.execute(
                "INSERT INTO corpus_documents "
                "(id, filename, kind, sha256, text, page_starts, chunk_count, ingested_at, "
                "blob, origin, doc_key, version) "
                "SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                "       COALESCE(MAX(version), 0) + 1 FROM corpus_documents WHERE doc_key = ?",
                (
                    doc_id,
                    filename,
                    kind,
                    digest,
                    text,
                    json.dumps(page_starts),
                    len(chunks),
                    now,
                    blob,
                    origin,
                    key,
                    key,
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
            conn.execute("UPDATE corpus_meta SET version = version + 1")
            # Read back rather than recomputed: the number that landed is the one the
            # INSERT allocated, and a second guess at it would be a second source of
            # truth for the identity a caller later uses to supersede this document.
            version = conn.execute(
                "SELECT version FROM corpus_documents WHERE id = ?", (doc_id,)
            ).fetchone()[0]
        return (key, int(version))

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
                # Unconditional, not a caller-chosen filter: a generated report resolving as
                # a clean citation for the next report is exactly the false-measurement bug
                # this store exists to refuse (see the `origin` column comment above).
                # `superseded_at IS NULL` is a visibility filter, not a ranking one:
                # scoring, ordering and the relevance cutoff below are untouched. A
                # superseded version stays readable through `read()` so citations made
                # against it keep resolving; it simply stops being offered as new evidence,
                # or a corrected document would be cited alongside the version it corrects.
                "WHERE c.embedding_model = ? AND d.origin != 'generated' "
                "AND d.superseded_at IS NULL",
                (self._embedder.model_id,),
            ).fetchall()

        if not rows:
            # Distinguish "empty corpus", "wrong model", and "nothing but auto-saved
            # reports" — all three fail the run, but the remedy differs (ingest documents,
            # re-index after a model change, or upload a real source). Each diagnostic
            # query below repeats the same `origin != 'generated'` exclusion as the main
            # query above, or a corpus holding only generated reports would misreport
            # itself as "wrong embedding model" instead of the true reason.
            # Supersession first, or the checks below misread it. Each diagnostic query
            # repeats the main query's filters except the one it is testing — so without
            # this branch a corpus whose documents have all been superseded matches the
            # embedding-model check against itself and reports "indexed with a different
            # embedding model (X); current model is 'X'", which is both untrue and
            # unactionable. Fail closed and say what actually happened.
            with self._connect() as conn:
                superseded = conn.execute(
                    "SELECT COUNT(*) FROM corpus_chunks c "
                    "JOIN corpus_documents d ON d.id = c.document_id "
                    "WHERE c.embedding_model = ? AND d.origin != 'generated' "
                    "AND d.superseded_at IS NOT NULL",
                    (self._embedder.model_id,),
                ).fetchone()[0]
            if superseded:
                raise RuntimeError(
                    "Every document in this corpus has been superseded and none has a "
                    "current version. Retrieval only reads current versions — ingest a "
                    "document, or the run would cite content that was replaced."
                )
            with self._connect() as conn:
                other = conn.execute(
                    "SELECT c.embedding_model, COUNT(*) FROM corpus_chunks c "
                    "JOIN corpus_documents d ON d.id = c.document_id "
                    "WHERE d.origin != 'generated' AND d.superseded_at IS NULL GROUP BY 1"
                ).fetchall()
            if other:
                models = ", ".join(f"{m} ({n} chunks)" for m, n in other)
                raise RuntimeError(
                    f"Corpus was indexed with a different embedding model ({models}); "
                    f"current model is '{self._embedder.model_id}'. Re-ingest to re-index."
                )
            with self._connect() as conn:
                generated_only = conn.execute(
                    "SELECT COUNT(*) FROM corpus_documents WHERE origin = 'generated'"
                ).fetchone()[0]
            if generated_only:
                raise RuntimeError(
                    "The corpus has only auto-saved reports and no uploaded documents. "
                    "Generated reports are never used as evidence — upload a source "
                    "before running corpus-only research."
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

    async def search_generated_reports(self, query: str, max_results: int) -> list[dict]:
        """Search auto-saved generated reports in this project's corpus for chat grounding."""
        query_vector = (await self._embedder.embed([query]))[0]
        return await asyncio.to_thread(self._search_generated_sync, query_vector, max_results)

    def _search_generated_sync(self, query_vector: list[float], max_results: int) -> list[dict]:
        import numpy as np

        with self._connect() as conn:
            rows = conn.execute(
                'SELECT c.id, c.document_id, c.start, c."end", c.page, c.text, c.embedding, '
                "d.filename "
                "FROM corpus_chunks c JOIN corpus_documents d ON d.id = c.document_id "
                "WHERE c.embedding_model = ? AND d.origin = 'generated'",
                (self._embedder.model_id,),
            ).fetchall()

        if not rows:
            return []

        matrix = np.stack([np.frombuffer(row[6], dtype=np.float32) for row in rows])
        if matrix.shape[1] != len(query_vector):
            return []

        q = np.asarray(query_vector, dtype=np.float32)
        q_norm = q / (np.linalg.norm(q) or 1.0)
        norms = np.linalg.norm(matrix, axis=1)
        norms[norms == 0] = 1.0
        scores = (matrix / norms[:, None]) @ q_norm

        ranked = np.argsort(-scores)[: max_results * 4]
        results: list[dict] = []
        for idx in ranked:
            if scores[idx] <= 0.0:
                break
            row = rows[int(idx)]
            doc_id = row[1]
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

    async def identity(self) -> tuple[str, int]:
        """`(corpus_id, corpus_version)` — which corpus this is, and its state right now.

        The one source for both hosts. A run records the pair at the moment it opens the
        corpus, which is what lets a finished run say which corpus state produced its
        evidence rather than merely which documents it happened to cite.
        """
        return await asyncio.to_thread(self._identity_sync)

    def _identity_sync(self) -> tuple[str, int]:
        with self._connect() as conn:
            row = conn.execute("SELECT corpus_id, version FROM corpus_meta").fetchone()
        return (row[0], int(row[1]))

    async def documents(self) -> list[dict]:
        return await asyncio.to_thread(self._documents_sync)

    def _documents_sync(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, filename, kind, chunk_count, ingested_at, "
                "       doc_key, version, superseded_at, "
                # length() on a BLOB reads its size without loading the bytes, so listing
                # a corpus of 25 MB PDFs stays cheap. `downloadable` is derived rather
                # than assumed: documents ingested before the blob column existed have
                # NULL here, and the UI must offer Open only where a file really exists.
                "       length(blob), origin FROM corpus_documents "
                "ORDER BY ingested_at"
            ).fetchall()
        return [
            {
                "id": row[0],
                "filename": row[1],
                "kind": row[2],
                "chunk_count": row[3],
                "ingested_at": row[4],
                "doc_key": row[5],
                "version": row[6],
                # Derived rather than stored: "is this the one retrieval can see" is a
                # question about `superseded_at`, and a second column recording the same
                # fact is a second thing that can disagree with it.
                "is_current": row[7] is None,
                "size_bytes": row[8],
                "downloadable": row[8] is not None,
                "origin": row[9],
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
        """Remove one *version*. Deliberately not a logical-document operation.

        Three things this does not do, each of which would be a defensible-looking mistake.
        It does not renumber later versions — a version number is a historical identifier
        and a citation may name it. It does not resurrect the predecessor when the current
        version is deleted: the document is then left with no current version, which is the
        honest state, where un-superseding one would silently republish content the user
        removed. And it does not cascade to siblings — deleting one revision is not
        deleting the document.
        """
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM corpus_documents WHERE id = ?", (doc_id,))
            if cursor.rowcount:
                conn.execute("UPDATE corpus_meta SET version = version + 1")
        return cursor.rowcount > 0

    async def status(self) -> dict:
        return await asyncio.to_thread(self._status_sync)

    def _status_sync(self) -> dict:
        with self._connect() as conn:
            meta = conn.execute("SELECT corpus_id, version FROM corpus_meta").fetchone()
            docs = conn.execute("SELECT COUNT(*) FROM corpus_documents").fetchone()[0]
            by_model = conn.execute(
                "SELECT embedding_model, COUNT(*) FROM corpus_chunks GROUP BY 1 ORDER BY 1"
            ).fetchall()
        return {
            "documents": docs,
            "chunks_by_model": {model: count for model, count in by_model},
            "current_model": self._embedder.model_id,
            "corpus_id": meta[0],
            "corpus_version": int(meta[1]),
        }


def _pack(vector: list[float]) -> bytes:
    import numpy as np

    return np.asarray(vector, dtype=np.float32).tobytes()
