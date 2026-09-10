"""Corpus identity, logical documents, and document versions (V2.1-a A4).

A corpus could not name itself: identity was the file path, and the desktop has one flat
file for the whole app, so a bundle citing `corpus://<id>` could say which bytes but never
which corpus or what state it was in. And a corrected document was not a revision of
anything — re-uploading it produced a second independent document, so a report cited the
old and the new version side by side, both showing the same filename.

The model here keeps four things apart that were previously conflated:

    content identity   sha256 of the bytes
    logical document   doc_key, an opaque uuid minted by the store
    version            the revision, whose row id stays the citation target
    filename           version-level display metadata, free to change between revisions

**Nothing is inferred.** A filename is not identity, because two unrelated papers can
legitimately share one; an upload is a revision only when the caller says which document it
revises. That refusal to guess is what these tests mostly pin.
"""

from __future__ import annotations

import pytest

from research_engine.corpus import CorpusStore, UnknownDocumentKey, parse_corpus_url
from tests.dataflow.test_corpus_store import FakeEmbeddings

V1 = b"Photovoltaic cells convert light into direct current across a doped junction."
V2 = b"Photovoltaic cells convert light into direct current; revised with new figures."
OTHER = b"Hydrothermal vents host chemosynthetic bacteria far below the sunlit zone."


@pytest.fixture
async def store(tmp_path) -> CorpusStore:
    return CorpusStore(tmp_path / "corpus.sqlite", FakeEmbeddings())


# ── Corpus identity ───────────────────────────────────────────────────────────────


async def test_a_fresh_corpus_names_itself_and_starts_unversioned(store):
    corpus_id, version = await store.identity()
    assert corpus_id and len(corpus_id) == 36, "a corpus must carry an opaque id"
    assert version == 0


async def test_corpus_identity_survives_reopening_the_same_file(tmp_path):
    """Identity that changed on reopen would make a recorded snapshot meaningless."""
    first = CorpusStore(tmp_path / "c.sqlite", FakeEmbeddings())
    before = await first.identity()
    assert await CorpusStore(tmp_path / "c.sqlite", FakeEmbeddings()).identity() == before


async def test_two_corpora_are_distinct(tmp_path):
    """Isolation, as identity rather than as a filesystem convention."""
    a = await CorpusStore(tmp_path / "a.sqlite", FakeEmbeddings()).identity()
    b = await CorpusStore(tmp_path / "b.sqlite", FakeEmbeddings()).identity()
    assert a[0] != b[0]


async def test_the_corpus_version_advances_on_ingest_and_delete(store):
    assert (await store.identity())[1] == 0
    result = await store.ingest("paper.md", V1)
    assert (await store.identity())[1] == 1

    await store.ingest("paper.md", V1)  # identical bytes: nothing changed
    assert (await store.identity())[1] == 1, "a skipped ingest must not advance the version"

    await store.delete(result.doc_id)
    assert (await store.identity())[1] == 2


# ── Logical identity is never inferred ────────────────────────────────────────────


async def test_an_upload_without_a_key_is_a_new_logical_document(store):
    first = await store.ingest("paper.md", V1)
    second = await store.ingest("paper.md", OTHER)

    assert first.doc_key != second.doc_key, "same filename must not imply same document"
    assert first.version == second.version == 1


async def test_two_unrelated_documents_sharing_a_filename_both_stay_retrievable(store):
    """The case that ruled out filename-as-identity. Two different papers, one name."""
    await store.ingest("paper.md", V1)
    await store.ingest("paper.md", OTHER)

    titles = [d["filename"] for d in await store.documents()]
    assert titles == ["paper.md", "paper.md"]
    assert all(d["is_current"] for d in await store.documents())


async def test_supplying_a_key_creates_the_next_version_and_supersedes_the_previous(store):
    first = await store.ingest("paper.md", V1)
    second = await store.ingest("paper-revised.md", V2, doc_key=first.doc_key)

    assert second.doc_key == first.doc_key
    assert (first.version, second.version) == (1, 2)

    by_id = {d["id"]: d for d in await store.documents()}
    assert by_id[first.doc_id]["is_current"] is False
    assert by_id[second.doc_id]["is_current"] is True


async def test_a_filename_may_change_between_versions_of_one_document(store):
    """Filename is version-level metadata, so a corrected file may be renamed. A citation
    must render the name of the version cited, not whatever the document is called now."""
    first = await store.ingest("paper.md", V1)
    second = await store.ingest("paper-revised.md", V2, doc_key=first.doc_key)

    by_id = {d["id"]: d for d in await store.documents()}
    assert by_id[first.doc_id]["filename"] == "paper.md"
    assert by_id[second.doc_id]["filename"] == "paper-revised.md"


async def test_an_unknown_key_is_refused_rather_than_absorbed(store):
    """Creating a new document instead would answer success to a request meaning replace."""
    with pytest.raises(UnknownDocumentKey):
        await store.ingest("paper.md", V1, doc_key="00000000-0000-0000-0000-000000000000")
    assert await store.documents() == []
    assert (await store.identity())[1] == 0, "a refused ingest must change nothing"


# ── Idempotency ───────────────────────────────────────────────────────────────────


async def test_identical_bytes_are_still_skipped_without_a_key(store):
    """Pre-A4 behaviour, unchanged."""
    first = await store.ingest("paper.md", V1)
    again = await store.ingest("paper.md", V1)
    assert again.skipped is True and again.doc_id == first.doc_id
    assert len(await store.documents()) == 1


async def test_identical_bytes_for_the_current_version_do_not_mint_a_new_version(store):
    """Rule 7. A version number records a change; re-uploading the same bytes is not one."""
    first = await store.ingest("paper.md", V1)
    again = await store.ingest("paper.md", V1, doc_key=first.doc_key)

    assert again.skipped is True
    assert [d["version"] for d in await store.documents()] == [1]


# ── Versions are historical facts ─────────────────────────────────────────────────


async def test_versions_increase_monotonically_within_a_document(store):
    first = await store.ingest("p.md", V1)
    key = first.doc_key
    second = await store.ingest("p.md", V2, doc_key=key)
    third = await store.ingest("p.md", OTHER, doc_key=key)
    assert [first.version, second.version, third.version] == [1, 2, 3]


async def test_deleting_a_version_never_renumbers_the_others(store):
    """A version number may have been cited; renumbering would silently repoint it."""
    first = await store.ingest("p.md", V1)
    second = await store.ingest("p.md", V2, doc_key=first.doc_key)
    third = await store.ingest("p.md", OTHER, doc_key=first.doc_key)

    await store.delete(second.doc_id)
    assert sorted(d["version"] for d in await store.documents()) == [1, 3]
    assert {d["id"] for d in await store.documents()} == {first.doc_id, third.doc_id}


async def test_deleting_the_current_version_does_not_resurrect_its_predecessor(store):
    """Rules 4 and 5. Un-superseding would republish content the user removed."""
    first = await store.ingest("p.md", V1)
    second = await store.ingest("p.md", V2, doc_key=first.doc_key)

    await store.delete(second.doc_id)
    remaining = await store.documents()
    assert [d["id"] for d in remaining] == [first.doc_id]
    assert remaining[0]["is_current"] is False, "a superseded version must stay superseded"
    # Fail closed rather than empty: a corpus-mode run whose only content was replaced must
    # say so, not quietly research nothing. The message names supersession specifically —
    # without that branch the embedding-model diagnostic misfires and compares a model to
    # itself.
    with pytest.raises(RuntimeError, match="superseded"):
        await store.search("photovoltaic direct current", 5)


# ── Retrieval and readability ─────────────────────────────────────────────────────


async def test_retrieval_returns_only_the_current_version(store):
    """The defect this model exists for: a corrected paper cited beside the version it
    corrects, both displaying the same filename."""
    first = await store.ingest("paper.md", V1)
    await store.ingest("paper.md", V2, doc_key=first.doc_key)

    hits = await store.search("photovoltaic direct current", 5)
    assert len(hits) == 1
    assert parse_corpus_url(hits[0]["url"]).doc_id != first.doc_id


async def test_a_superseded_version_remains_readable_so_its_citations_resolve(store):
    """Historical evidence must not stop resolving because the document moved on."""
    first = await store.ingest("paper.md", V1)
    hits = await store.search("photovoltaic direct current", 5)
    cited = hits[0]["url"]

    await store.ingest("paper.md", V2, doc_key=first.doc_key)

    resolved = await store.read(cited)
    assert resolved["error"] is None
    assert V1.decode().split(".")[0] in resolved["text"]


async def test_chunks_belong_to_exactly_one_version(store):
    first = await store.ingest("p.md", V1)
    second = await store.ingest("p.md", V2, doc_key=first.doc_key)
    with store._connect() as conn:
        owners = dict(
            conn.execute("SELECT document_id, COUNT(*) FROM corpus_chunks GROUP BY 1").fetchall()
        )
    assert set(owners) == {first.doc_id, second.doc_id}


async def test_generated_reports_are_still_excluded_from_retrieval(store):
    """Unchanged by versioning: a corpus holding only auto-saved reports still refuses,
    rather than treating the model's own earlier output as evidence."""
    await store.ingest("report-1.md", V1, origin="generated")
    with pytest.raises(RuntimeError, match="only auto-saved reports"):
        await store.search("photovoltaic direct current", 5)


# ── Migrating a corpus written before versioning existed ──────────────────────────


def _make_pre_a4(path) -> None:
    """A corpus file exactly as builds before A4 wrote one: no meta, no version columns."""
    import sqlite3

    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE corpus_documents (
            id TEXT PRIMARY KEY, filename TEXT NOT NULL, kind TEXT NOT NULL,
            sha256 TEXT NOT NULL, text TEXT NOT NULL, page_starts TEXT NOT NULL,
            chunk_count INTEGER NOT NULL DEFAULT 0, ingested_at TEXT NOT NULL,
            blob BLOB, origin TEXT NOT NULL DEFAULT 'uploaded'
        );
        CREATE UNIQUE INDEX idx_corpus_doc_dedupe ON corpus_documents (filename, sha256);
        CREATE TABLE corpus_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT NOT NULL REFERENCES corpus_documents(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL, start INTEGER NOT NULL, "end" INTEGER NOT NULL,
            page INTEGER, text TEXT NOT NULL, embedding BLOB NOT NULL,
            embedding_model TEXT NOT NULL
        );
        """
    )
    # Two rows sharing a filename — the case migration must NOT try to interpret.
    for doc_id, ts, body in (
        ("doc-old", "2026-01-01T00:00:00+00:00", "Photovoltaic cells convert light."),
        ("doc-new", "2026-02-01T00:00:00+00:00", "Photovoltaic cells convert light better."),
    ):
        conn.execute(
            "INSERT INTO corpus_documents (id, filename, kind, sha256, text, page_starts, "
            "chunk_count, ingested_at, origin) VALUES (?, 'paper.md', 'txt', ?, ?, '[]', 1, ?, "
            "'uploaded')",
            (doc_id, f"sha-{doc_id}", body, ts),
        )
        conn.execute(
            'INSERT INTO corpus_chunks (document_id, chunk_index, start, "end", page, text, '
            "embedding, embedding_model) VALUES (?, 0, 0, ?, NULL, ?, ?, 'fake:fake')",
            (doc_id, len(body), body, b"\x00" * 12),
        )
    conn.commit()
    conn.close()


async def test_migration_preserves_every_byte_that_a_citation_depends_on(tmp_path):
    """The strictest gate. A pre-A4 corpus must come through with its ids, text, hashes and
    embedding blobs untouched, or an existing `corpus://` citation stops resolving to what
    was cited."""
    import sqlite3

    path = tmp_path / "old.sqlite"
    _make_pre_a4(path)
    conn = sqlite3.connect(path)
    before_docs = conn.execute(
        "SELECT id, text, sha256, ingested_at FROM corpus_documents ORDER BY id"
    ).fetchall()
    before_chunks = conn.execute(
        "SELECT document_id, text, embedding FROM corpus_chunks ORDER BY id"
    ).fetchall()
    conn.close()

    CorpusStore(path, FakeEmbeddings())  # opening runs the migration

    conn = sqlite3.connect(path)
    after_docs = conn.execute(
        "SELECT id, text, sha256, ingested_at FROM corpus_documents ORDER BY id"
    ).fetchall()
    after_chunks = conn.execute(
        "SELECT document_id, text, embedding FROM corpus_chunks ORDER BY id"
    ).fetchall()
    conn.close()

    assert after_docs == before_docs, "migration altered a document's identity or content"
    assert after_chunks == before_chunks, "migration altered a chunk or its vector"


async def test_migration_gives_each_existing_row_its_own_logical_document(tmp_path):
    """It must NOT group the two `paper.md` rows. Whether they are revisions of one paper
    or two unrelated papers is not knowable from anything stored, and guessing is exactly
    the identity inference this model refuses. Both stay current and retrievable."""
    path = tmp_path / "old.sqlite"
    _make_pre_a4(path)
    store = CorpusStore(path, FakeEmbeddings())

    docs = await store.documents()
    assert len(docs) == 2
    assert len({d["doc_key"] for d in docs}) == 2, "filename-based grouping was performed"
    assert all(d["version"] == 1 for d in docs)
    assert all(d["is_current"] for d in docs), "migration invented a supersession"


async def test_migration_is_deterministic_and_idempotent(tmp_path):
    """Reopening must not re-key, re-version, or double anything."""
    path = tmp_path / "old.sqlite"
    _make_pre_a4(path)
    first = {
        d["id"]: (d["doc_key"], d["version"])
        for d in await CorpusStore(path, FakeEmbeddings()).documents()
    }
    second = {
        d["id"]: (d["doc_key"], d["version"])
        for d in await CorpusStore(path, FakeEmbeddings()).documents()
    }
    assert first == second


async def test_a_migrated_corpus_can_then_be_versioned_explicitly(tmp_path):
    """Migration hands the user a mechanism it declined to use on their behalf: once they
    say the two rows are related, supersession works normally."""
    path = tmp_path / "old.sqlite"
    _make_pre_a4(path)
    store = CorpusStore(path, FakeEmbeddings())
    keys = {d["filename"]: d["doc_key"] for d in await store.documents()}

    revised = await store.ingest(
        "paper.md", b"Photovoltaic cells, third revision entirely.", doc_key=list(keys.values())[0]
    )
    assert revised.version == 2
    current = [d for d in await store.documents() if d["is_current"]]
    assert len(current) == 2, "one document advanced; the other is untouched"
