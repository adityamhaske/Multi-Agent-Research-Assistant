"""
One accepted-format list, checked against every place that restates it (RFC V3.1 C8, §10).

Five homes disagreed at v3.0.2: the backend accepted `.csv`/`.json`/`.rst`, the upload
picker refused them, and the refusal message named neither. `documents.FORMATS` is the one
list now; these tests fail the moment another home drifts from it.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import pytest

from app.services.document_headers import _MEDIA_TYPES
from research_engine import documents
from research_engine.documents import FORMATS, extract, kind_for

REPO = Path(__file__).resolve().parents[3]


def test_the_upload_picker_offers_exactly_the_accepted_formats():
    page = (REPO / "frontend/app/(app)/corpus/page.tsx").read_text("utf-8")
    block = re.search(r"const ACCEPTED = \[(.*?)\];", page, re.S)
    assert block, "the picker's ACCEPTED list moved; point this test at it"
    offered = set(re.findall(r'"(\.[a-z0-9]+)"', block.group(1)))
    assert offered == set(FORMATS)


def test_every_kind_has_a_download_media_type():
    assert {f.kind for f in FORMATS.values()} <= set(_MEDIA_TYPES)


def test_the_refusal_names_every_accepted_extension():
    with pytest.raises(ValueError) as err:
        kind_for("archive.zip")
    for ext in FORMATS:
        assert ext in str(err.value)


def test_every_lazily_imported_parser_ships_in_the_desktop_bundle():
    """A parser imported inside a function is invisible to PyInstaller's scan, so a missing
    hiddenimports entry is a desktop-only failure with every CI check green."""
    spec = (REPO / "backend/desktop/research-sidecar.spec").read_text("utf-8")
    statically_imported = {"bs4"}  # research_engine/tools.py imports it at module scope
    for fmt in FORMATS.values():
        if fmt.parser_module and fmt.parser_module not in statically_imported:
            assert f'"{fmt.parser_module}"' in spec, fmt.parser_module


def test_a_parser_crash_is_a_refused_file_not_a_server_error(monkeypatch):
    def explode(_data):
        raise KeyError("parser bug")

    monkeypatch.setattr(documents, "_extract_html", explode)
    with pytest.raises(ValueError, match="Could not read this file: KeyError"):
        extract("page.html", b"<p>hi</p>")


def test_a_missing_parser_is_named_not_reported_as_a_bad_file(monkeypatch):
    def missing(_data):
        raise ModuleNotFoundError("No module named 'pypdf'", name="pypdf")

    monkeypatch.setattr(documents, "_extract_pdf", missing)
    with pytest.raises(ValueError, match="This build cannot read PDF files"):
        extract("paper.pdf", b"%PDF-1.4")


def _zip(members: dict[str, bytes], compression=zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_an_archive_bomb_is_refused_before_parsing():
    with pytest.raises(ValueError, match="compress more than"):
        documents.check_archive(_zip({"word/document.xml": b"\0" * 5_000_000}))


def test_an_archive_with_too_many_parts_is_refused(monkeypatch):
    monkeypatch.setattr(documents, "MAX_ARCHIVE_MEMBERS", 3)
    with pytest.raises(ValueError, match="parts"):
        documents.check_archive(_zip({f"p{i}": b"x" for i in range(4)}, zipfile.ZIP_STORED))


def test_an_archive_expanding_past_the_limit_is_refused(monkeypatch):
    monkeypatch.setattr(documents, "MAX_ARCHIVE_EXPANDED_BYTES", 1000)
    with pytest.raises(ValueError, match="expand to"):
        documents.check_archive(_zip({"a": b"x" * 2000}, zipfile.ZIP_STORED))


def test_an_ordinary_archive_passes():
    documents.check_archive(_zip({"a.xml": b"<x>hello</x>" * 10}))
