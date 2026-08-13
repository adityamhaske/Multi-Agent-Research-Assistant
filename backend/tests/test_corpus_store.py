"""
Airgapped corpus: ingest, chunking, store, and the location contract (docs/12 M10).

The M10 DoD is "every citation resolves to an exact document location". These tests
prove the three load-bearing properties behind it, against a real SQLite file rather
than a mock — offsets are verbatim spans of the extracted text, corpus URLs round-trip
to those spans, and `read` hands back the text at exactly that spot. The embedding
step uses a deterministic local fake (no network, no Ollama): what matters here is the
store's contract, not any particular model's vectors.
"""

from __future__ import annotations

import hashlib
import io
import math
import re

import pytest

from research_engine.chunking import chunk_document
from research_engine.corpus import CorpusStore, corpus_url, parse_corpus_url
from research_engine.documents import extract_document, kind_for

SOLAR_TEXT = (
    "Solar energy converts sunlight into electricity. Photovoltaic cells made of "
    "silicon absorb photons and release electrons, creating a direct current. "
    "Modern panels convert roughly a fifth of the sunlight that reaches them. "
    "Installations range from rooftop arrays to desert farms the size of small towns. "
    "The cost of a solar module has fallen steadily for three decades, which is why "
    "new solar capacity now undercuts most fossil generation on price alone."
)

VENTS_TEXT = (
    "Deep sea hydrothermal vents host ecosystems that need no sunlight at all. "
    "Chemosynthetic bacteria oxidize hydrogen sulfide from the vent fluid and form "
    "the base of a food web that includes tube worms, shrimp, and ghostly white crabs. "
    "Vent fluids can exceed three hundred degrees Celsius yet the surrounding ocean "
    "sits just above freezing. Each vent field is an island of life, separated from "
    "the next by kilometers of barren seafloor."
)


class FakeEmbeddings:
    """Deterministic bag-of-word vectors: shared words give high cosine.

    Each distinct word gets its OWN dimension (assigned in first-seen order),
    counts accumulate, and the vector is L2-normalized. Width is fixed at
    construction so every stored blob has the same shape; words beyond the
    vocabulary fall back to a hash slot. Unlike a pure hash-mod scheme this is
    collision-free within capacity — 256 dimensions made near-duplicate test
    documents tie, which no real embedding model does.
    """

    def __init__(self, name: str = "fake", dims: int = 1024) -> None:
        self._model_id = f"fake:{name}"
        self._dims = dims
        self._vocab: dict[str, int] = {}

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def dimensions(self) -> int:
        return self._dims

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self._dims
        # Hyphen-joined words stay one token ("docid-250"); punctuation is dropped
        # so a trailing period cannot split a word off its query form.
        for word in re.findall(r"[a-z0-9][a-z0-9-]*", text.lower()):
            index = self._vocab.get(word)
            if index is None:
                if len(self._vocab) < self._dims:
                    index = self._vocab[word] = len(self._vocab)
                else:  # vocabulary full: degrade to a hash slot rather than fail
                    index = (
                        int.from_bytes(hashlib.sha256(word.encode()).digest()[:4], "big")
                        % self._dims
                    )
            vec[index] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


@pytest.fixture
def store(tmp_path) -> CorpusStore:
    return CorpusStore(tmp_path / "corpus.sqlite", FakeEmbeddings())


# ── chunk_document: the verbatim-span contract ─────────────────────────────────


def _long_text(paragraphs: int = 8) -> str:
    return "\n\n".join(
        f"Paragraph {i} discusses topic {i} at length. It carries several sentences "
        f"so the chunker has real boundaries to snap to. Sentence three of paragraph "
        f"{i} adds a further detail worth citing. The final sentence closes it out."
        for i in range(paragraphs)
    )


def test_chunk_spans_are_verbatim_slices_of_the_source():
    body = _long_text()
    chunks = chunk_document(body)
    assert len(chunks) > 1
    for chunk in chunks:
        assert body[chunk.start : chunk.end] == chunk.text, (
            "a corpus chunk must be exactly its source span — the location contract "
            "is structural, not conventional"
        )


def test_chunk_spans_cover_the_content():
    body = _long_text()
    chunks = chunk_document(body)
    covered = {(chunk.start, chunk.end) for chunk in chunks}
    # Every sentence of the body sits inside at least one chunk span.
    for match in re.finditer(r"Paragraph \d+", body):
        assert any(s <= match.start() < e for s, e in covered), match.group()


def test_chunks_overlap_and_progress():
    chunks = chunk_document(_long_text(12))
    assert len(chunks) > 2
    for prev, nxt in zip(chunks, chunks[1:], strict=False):
        assert nxt.start < prev.end, "overlap: the next chunk starts inside the previous"
        assert nxt.start >= prev.start, "progress: chunks never move backwards"


def test_chunk_pages_follow_page_starts():
    page1 = "Alpha sentences about solar panels and sunlight. " * 12
    page2 = "Beta sentences about hydrothermal vents and chemosynthesis. " * 12
    body = page1.rstrip() + "\n\n" + page2.rstrip()
    page_starts = [0, len(page1.rstrip()) + 2]

    chunks = chunk_document(body, page_starts=page_starts)
    pages = {chunk.page for chunk in chunks}
    assert pages == {1, 2}
    for chunk in chunks:
        expected = 1 if chunk.start < page_starts[1] else 2
        assert chunk.page == expected


def test_single_page_document_has_no_page_numbers():
    chunks = chunk_document(_long_text(), page_starts=[0])
    assert all(chunk.page is None for chunk in chunks)


def test_chunking_is_deterministic():
    body = _long_text()
    first = chunk_document(body)
    again = chunk_document(body)
    assert [(c.start, c.end) for c in first] == [(c.start, c.end) for c in again]


def test_empty_text_yields_no_chunks():
    assert chunk_document("") == []
    assert chunk_document("   \n  ") == []


# ── document extraction ─────────────────────────────────────────────────────────


def test_text_and_markdown_extract_with_no_pages():
    text, page_starts, kind = extract_document("notes.md", b"# Title\r\n\r\nBody text.")
    assert kind == "md"
    assert text == "# Title\n\nBody text.", "CRLF is normalized before chunking"
    assert page_starts == [0]

    _, _, kind = extract_document("readme.txt", b"plain")
    assert kind == "txt"


def test_unsupported_formats_are_refused():
    with pytest.raises(ValueError, match="Unsupported document type"):
        extract_document("archive.docx", b"whatever")
    with pytest.raises(ValueError, match="Unsupported document type"):
        kind_for("noextension")


def test_empty_documents_are_refused():
    with pytest.raises(ValueError, match="no text"):
        extract_document("blank.txt", b"   \n ")


def test_oversized_documents_are_refused():
    from research_engine.documents import MAX_DOCUMENT_BYTES

    with pytest.raises(ValueError, match="at most"):
        extract_document("big.txt", b"x" * (MAX_DOCUMENT_BYTES + 1))


def _build_pdf(page_texts: list[str]) -> bytes:
    """A minimal but valid multi-page PDF: Helvetica text, one Tj per page.

    Hand-built (rather than a fixture file) so the expected text and the xref
    offsets are both in the test — nothing about the fixture is taken on faith.
    """
    objects: dict[int, bytes] = {}
    page_ids = [4 + 2 * i for i in range(len(page_texts))]
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_texts)} >>".encode()
    objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    for i, text in enumerate(page_texts):
        content_id = 5 + 2 * i
        objects[page_ids[i]] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content_id} 0 R /Resources << /Font << /F1 3 0 R >> >> >>"
        ).encode()
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        objects[content_id] = (
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for obj_id in sorted(objects):
        offsets[obj_id] = out.tell()
        out.write(f"{obj_id} 0 obj\n".encode() + objects[obj_id] + b"\nendobj\n")
    xref_pos = out.tell()
    size = len(objects) + 1
    out.write(f"xref\n0 {size}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for obj_id in sorted(objects):
        out.write(f"{offsets[obj_id]:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF".encode())
    return out.getvalue()


def test_pdf_extraction_tracks_pages():
    pages = [
        "Solar panels convert sunlight into electricity",
        "Deep sea vents host unique ecosystems",
    ]
    text, page_starts, kind = extract_document("sample.pdf", _build_pdf(pages))
    assert kind == "pdf"
    assert page_starts[0] == 0
    assert len(page_starts) == 2
    assert pages[0] in text[: page_starts[1]]
    assert text[page_starts[1] :].startswith(pages[1]), (
        "page 2 begins exactly at its recorded offset"
    )


def test_garbage_bytes_are_not_a_pdf():
    with pytest.raises(ValueError, match="Not a readable PDF"):
        extract_document("broken.pdf", b"this is not a pdf at all")


# ── the corpus:// URL scheme ────────────────────────────────────────────────────


def test_corpus_urls_round_trip():
    url = corpus_url("doc-123", start=10, end=40, page=3)
    location = parse_corpus_url(url)
    assert location is not None
    assert (location.doc_id, location.start, location.end, location.page) == ("doc-123", 10, 40, 3)

    no_page = parse_corpus_url(corpus_url("d", start=0, end=5, page=None))
    assert no_page is not None and no_page.page is None


def test_corpus_url_parsing_fails_closed():
    assert parse_corpus_url("https://example.com/") is None
    assert parse_corpus_url("corpus:///chars=0-5") is None, "missing document id"
    assert parse_corpus_url("corpus://doc#chars=5-5") is None, "empty span"
    assert parse_corpus_url("corpus://doc#page=2") is None, "missing offsets"


# ── CorpusStore: ingest, search, read, manage ──────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_search_and_read_resolve_exact_locations(store):
    result = await store.ingest("solar.txt", SOLAR_TEXT.encode())
    assert result.doc_id and result.chunks_written >= 1 and not result.skipped

    hits = await store.search("photovoltaic cells convert sunlight into electricity", max_results=3)
    assert hits, "a query sharing tokens with the corpus must hit it"
    top = hits[0]
    assert top["title"] == "solar.txt"
    assert top["url"].startswith("corpus://")

    location = parse_corpus_url(top["url"])
    assert location is not None and location.doc_id == result.doc_id
    assert top["snippet"] == SOLAR_TEXT[location.start : location.end], (
        "the returned snippet is verbatim text at the returned location"
    )

    resolved = await store.read(top["url"])
    assert resolved["error"] is None
    assert top["snippet"] in resolved["text"], "read() returns the text around the cited span"
    assert resolved["title"].startswith("solar.txt")


@pytest.mark.asyncio
async def test_reingest_of_identical_content_is_skipped(store):
    first = await store.ingest("solar.txt", SOLAR_TEXT.encode())
    second = await store.ingest("solar.txt", SOLAR_TEXT.encode())
    assert second.skipped and second.doc_id == first.doc_id
    assert len(await store.documents()) == 1

    changed = await store.ingest("solar.txt", (SOLAR_TEXT + " An added sentence.").encode())
    assert not changed.skipped and changed.doc_id != first.doc_id
    assert len(await store.documents()) == 2


@pytest.mark.asyncio
async def test_search_returns_at_most_one_hit_per_document(store):
    await store.ingest("solar.txt", SOLAR_TEXT.encode())
    hits = await store.search("solar panels sunlight electricity photovoltaic", max_results=5)
    assert len(hits) == 1, "two chunks of one file are not two sources"


@pytest.mark.asyncio
async def test_empty_corpus_search_fails_closed(tmp_path):
    empty = CorpusStore(tmp_path / "empty.sqlite", FakeEmbeddings())
    with pytest.raises(RuntimeError, match="empty"):
        await empty.search("anything", max_results=3)


@pytest.mark.asyncio
async def test_embedding_model_mismatch_fails_closed(tmp_path):
    path = tmp_path / "corpus.sqlite"
    alpha = CorpusStore(path, FakeEmbeddings("alpha"))
    await alpha.ingest("solar.txt", SOLAR_TEXT.encode())

    beta = CorpusStore(path, FakeEmbeddings("beta"))
    with pytest.raises(RuntimeError, match="different embedding model"):
        await beta.search("solar", max_results=3)


@pytest.mark.asyncio
async def test_read_refuses_bad_locations(store):
    result = await store.ingest("solar.txt", SOLAR_TEXT.encode())
    doc_id = result.doc_id

    bad_scheme = await store.read("https://example.com/")
    assert "not a valid corpus URL" in bad_scheme["error"]

    unknown = await store.read(corpus_url("no-such-doc", start=0, end=5, page=None))
    assert "not found" in unknown["error"]

    out_of_range = await store.read(
        corpus_url(doc_id, start=len(SOLAR_TEXT) + 10, end=len(SOLAR_TEXT) + 20, page=None)
    )
    assert "out of range" in out_of_range["error"]


@pytest.mark.asyncio
async def test_delete_cascades_to_chunks(store):
    solar = await store.ingest("solar.txt", SOLAR_TEXT.encode())
    await store.ingest("vents.txt", VENTS_TEXT.encode())

    assert await store.delete(solar.doc_id) is True
    assert await store.delete(solar.doc_id) is False, "second delete finds nothing"

    remaining = await store.documents()
    assert [d["filename"] for d in remaining] == ["vents.txt"]

    hits = await store.search("hydrothermal vents chemosynthetic bacteria", max_results=3)
    assert hits and all(parse_corpus_url(h["url"]).doc_id != solar.doc_id for h in hits)

    status = await store.status()
    assert status["documents"] == 1


# ── the M10 DoD scale test: 500 documents, no OOM, retrieval still exact ───────


@pytest.mark.asyncio
async def test_ingest_500_documents(tmp_path):
    big = CorpusStore(tmp_path / "scale.sqlite", FakeEmbeddings())
    for i in range(500):
        # The docid word repeats so it dominates each document's vector: a query
        # for one specific docid must then rank that document first, decisively.
        text = " ".join(f"docid-{i} measurement {j} recorded." for j in range(12))
        result = await big.ingest(f"doc-{i:03d}.txt", text.encode())
        assert result.doc_id, f"doc {i} ingested"

    status = await big.status()
    assert status["documents"] == 500
    assert sum(status["chunks_by_model"].values()) >= 500

    hits = await big.search("docid-250", max_results=3)
    assert hits and hits[0]["title"] == "doc-250.txt"
    location = parse_corpus_url(hits[0]["url"])
    assert location is not None
    resolved = await big.read(hits[0]["url"])
    assert resolved["error"] is None and hits[0]["snippet"] in resolved["text"]
