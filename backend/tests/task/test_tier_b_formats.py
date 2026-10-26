"""
Tier B formats (RFC V3.1 §10.2, PR-12; AC-15, AC-16, AC-17): Word documents, and Excel and
OpenDocument spreadsheets, through exact-pinned python-docx and python-calamine.

Canonical text is pinned per fixture, because it is what every quote is verified against.
The fixtures in tests/fixtures/formats were written once by xlsxwriter, xlwt, odfpy and
python-docx and committed as bytes; none of those writers is a runtime dependency.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import pytest

from research_engine.corpus import CorpusStore, corpus_url
from research_engine.documents import LINEARIZED, extract
from tests.dataflow.test_corpus_store import FakeEmbeddings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "formats"

SHEET = "## Sheet: Budget\nRow 2 — Item: Staff; Cost: 1200\nRow 3 — Item: Travel; Cost: 300.5"

GOLDEN = {
    "report.docx": (
        "# Method\nWe sampled 40 districts in 2021.\n## Results\n"
        "Enrolment rose 12% in the North.\n"
        "Row 2 — District: North; Change: 12%\nRow 3 — District: South; Change: -3%",
        "docx",
    ),
    "budget.xlsx": (
        SHEET + "\n## Sheet: Notes (hidden)\nRow 2 — Note: Draft figures",
        "spreadsheet",
    ),
    "budget.xls": (SHEET, "spreadsheet"),
    "budget.ods": (SHEET, "spreadsheet"),
}


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_canonical_text_is_exactly_the_golden(name):
    text, kind = GOLDEN[name]
    result = extract(name, (FIXTURES / name).read_bytes())
    assert result.text == text
    assert (result.kind, result.mode) == (kind, LINEARIZED)
    assert all(0 <= start < len(result.text) for start, _ in result.segments)


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_extraction_is_deterministic(name):
    data = (FIXTURES / name).read_bytes()
    assert extract(name, data) == extract(name, data)


def test_a_hidden_sheet_is_read_and_marked():
    text = extract("budget.xlsx", (FIXTURES / "budget.xlsx").read_bytes()).text
    assert "## Sheet: Notes (hidden)" in text


def _rewrite_docx(transform) -> bytes:
    """The fixture with its document.xml passed through `transform`."""
    source = zipfile.ZipFile(FIXTURES / "report.docx")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "word/document.xml":
                data = transform(data.decode("utf-8")).encode("utf-8")
            target.writestr(item, data)
    return out.getvalue()


def test_tracked_changes_read_as_accepted():
    """Inserted text is in, deleted text is out: what a reader of the finished document sees."""

    def track(xml: str) -> str:
        return xml.replace(
            "<w:t>We sampled 40 districts in 2021.</w:t>",
            '<w:t>We sampled </w:t></w:r><w:ins w:id="1" w:author="a"><w:r><w:t>forty </w:t>'
            '</w:r></w:ins><w:del w:id="2" w:author="a"><w:r><w:delText>40 </w:delText></w:r>'
            "</w:del><w:r><w:t>districts in 2021.</w:t>",
        )

    text = extract("report.docx", _rewrite_docx(track)).text
    assert "We sampled forty districts in 2021." in text
    assert "40 districts" not in text


@pytest.mark.parametrize(
    ("name", "data", "message"),
    [
        ("locked.docx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 600, "password-protected"),
        ("locked.xlsx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 600, "password-protected"),
        ("garbage.docx", b"this is not a zip file at all", "Not a readable document"),
        ("garbage.xlsx", b"this is not a zip file at all", "Not a readable document"),
        ("garbage.xls", b"this is not a workbook", "Could not read this file"),
    ],
)
def test_encrypted_and_malformed_files_are_refused_by_name(name, data, message):
    with pytest.raises(ValueError, match=message):
        extract(name, data)


def test_an_empty_document_is_refused():
    stripped = _rewrite_docx(lambda xml: re.sub(r"<w:t(?: [^>]*)?>[^<]*</w:t>", "", xml))
    with pytest.raises(ValueError, match="no text"):
        extract("blank.docx", stripped)


def test_a_docx_bomb_is_refused_before_parsing():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", b"\0" * 5_000_000)
    with pytest.raises(ValueError, match="compress more than"):
        extract("bomb.docx", out.getvalue())


def test_an_oversized_sheet_is_refused_not_cut(monkeypatch):
    from research_engine import documents

    monkeypatch.setattr(documents, "MAX_TABLE_ROWS", 1)
    with pytest.raises(ValueError, match="rows by"):
        extract("budget.xlsx", (FIXTURES / "budget.xlsx").read_bytes())


@pytest.mark.parametrize(
    ("name", "needle", "label"),
    [
        ("budget.xlsx", "Travel", "Sheet Budget, row 3"),
        ("budget.ods", "Staff", "Sheet Budget, row 2"),
        ("report.docx", "Enrolment rose", "Method › Results"),
        ("report.docx", "South", "table 1 row 3"),
    ],
)
async def test_a_citation_names_its_sheet_row_or_section(tmp_path, name, needle, label):
    store = CorpusStore(tmp_path / "c.sqlite", FakeEmbeddings())
    result = await store.ingest(name, (FIXTURES / name).read_bytes())
    text = extract(name, (FIXTURES / name).read_bytes()).text
    start = text.index(needle)
    page = await store.read(corpus_url(result.doc_id, start=start, end=start + 5, page=None))
    assert page["error"] is None, page
    assert label in page["title"], page["title"]
