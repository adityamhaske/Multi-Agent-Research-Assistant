"""
Tier C formats (RFC V3.1 §10.2, PR-13; AC-15, AC-16, AC-17): PowerPoint, OpenDocument
text, EPUB and RTF.

PowerPoint, ODT and EPUB are read as ZIP archives of XML with the standard library and lxml,
so python-pptx and the image library it pulls in never join the desktop bundle. RTF goes
through striprtf (BSD-3, pure Python). Fixtures were written once by python-pptx and odfpy,
or by hand, and committed as bytes.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from research_engine.corpus import CorpusStore, corpus_url
from research_engine.documents import LINEARIZED, VERBATIM, extract
from tests.dataflow.test_corpus_store import FakeEmbeddings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "formats"

GOLDEN = {
    "deck.pptx": (
        "## Slide 1: Enrolment\nEnrolment rose 12% in 2021.\nNotes:\nMention the North district."
        "\n\n## Slide 2: By district\nRow 2 — District: North; Change: 12%\n"
        "Row 3 — District: South; Change: -3%",
        "pptx",
        LINEARIZED,
    ),
    "notes.odt": ("# Method\nWe sampled 40 districts in 2021.", "odt", LINEARIZED),
    "book.epub": (
        "Origins\nSchools opened in 1901.\n\nGrowth\nEnrolment rose 12% in 2021.",
        "epub",
        VERBATIM,
    ),
    "memo.rtf": ("Enrolment rose 12% in 2021.\nThe North led.", "rtf", LINEARIZED),
}


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_canonical_text_is_exactly_the_golden(name):
    text, kind, mode = GOLDEN[name]
    result = extract(name, (FIXTURES / name).read_bytes())
    assert result.text == text
    assert (result.kind, result.mode) == (kind, mode)


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_extraction_is_deterministic(name):
    data = (FIXTURES / name).read_bytes()
    assert extract(name, data) == extract(name, data)


def test_epub_chapters_follow_the_spine_not_the_manifest():
    """The manifest lists chapter 2 first; reading order is the spine's."""
    text = extract("book.epub", (FIXTURES / "book.epub").read_bytes()).text
    assert text.index("Origins") < text.index("Growth")


def test_external_entities_in_document_xml_are_not_resolved():
    """An XML part declaring an external entity must not read a local file into the text."""
    bad = io.BytesIO()
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        z.writestr(
            "content.xml",
            '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
            '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:'
            'office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
            "<office:body><office:text><text:p>Leak: &e;</text:p></office:text></office:body>"
            "</office:document-content>",
        )
    try:
        text = extract("evil.odt", bad.getvalue()).text
    except ValueError:
        return  # refusing the file outright is also safe
    assert "root:" not in text


@pytest.mark.parametrize(
    ("name", "data", "message"),
    [
        ("locked.pptx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 600, "password-protected"),
        ("garbage.pptx", b"not a zip", "Not a readable document"),
        ("garbage.odt", b"not a zip", "Not a readable document"),
        ("garbage.epub", b"not a zip", "Not a readable document"),
        ("garbage.rtf", b"plain words, no rtf header", "Not a readable RTF"),
        ("empty.rtf", b"{\\rtf1\\ansi }", "no text"),
    ],
)
def test_encrypted_malformed_and_empty_files_are_refused_by_name(name, data, message):
    with pytest.raises(ValueError, match=message):
        extract(name, data)


def test_an_epub_without_a_package_document_is_refused():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
    with pytest.raises(ValueError, match="container.xml"):
        extract("broken.epub", buf.getvalue())


@pytest.mark.parametrize(
    ("name", "needle", "label"),
    [
        ("deck.pptx", "South", "slide 2"),
        ("deck.pptx", "Mention", "slide 1"),
        ("book.epub", "Enrolment", "chapter 2: Growth"),
        ("notes.odt", "We sampled", "Method"),
    ],
)
async def test_a_citation_names_its_slide_chapter_or_section(tmp_path, name, needle, label):
    store = CorpusStore(tmp_path / "c.sqlite", FakeEmbeddings())
    result = await store.ingest(name, (FIXTURES / name).read_bytes())
    text = extract(name, (FIXTURES / name).read_bytes()).text
    start = text.index(needle)
    page = await store.read(corpus_url(result.doc_id, start=start, end=start + 5, page=None))
    assert page["error"] is None, page
    assert label in page["title"], page["title"]
