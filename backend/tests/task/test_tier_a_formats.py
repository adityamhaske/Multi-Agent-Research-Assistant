"""
Tier A formats (RFC V3.1 §10.2, PR-11; AC-15, AC-17): source code, LaTeX/BibTeX, CSV/TSV,
Jupyter notebooks — everything the standard library reads.

The canonical text of each fixture is pinned exactly: it is what every citation's quote is
verified against, so a change to it is a change to which quotes verify, and must be seen.
Each format is also checked for determinism, refusal of malformed and empty input, and the
location label a citation shows, through a real `CorpusStore`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_engine.corpus import CorpusStore, corpus_url
from research_engine.documents import LINEARIZED, VERBATIM, extract
from tests.dataflow.test_corpus_store import FakeEmbeddings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "formats"

GOLDEN = {
    "enrolment.csv": (
        "Row 2 — Name: North; Year: 2021; Enrolment: 1200\nRow 3 — Name: South; Year: 2021",
        "csv",
        LINEARIZED,
        [(0, "row 2"), (49, "row 3")],
    ),
    "enrolment.tsv": (
        "Row 2 — Name: North; Year: 2021; Enrolment: 1200",
        "csv",
        LINEARIZED,
        [(0, "row 2")],
    ),
    "stats.py": (
        'def mean(xs):\n    """The arithmetic mean."""\n    return sum(xs) / len(xs)\n',
        "code",
        VERBATIM,
        [],
    ),
    "method.tex": ("\\section{Method}\nWe sampled 40 districts.\n", "code", VERBATIM, []),
    "analysis.ipynb": (
        "## Cell 1 (markdown)\n# Enrolment\nEnrolment rose 12% in 2021.\n\n"
        "## Cell 2 (code) — 1 non-text output(s) not shown\nprint(1200 * 1.12)\n"
        "Output:\n1344.0\n<Figure>",
        "ipynb",
        LINEARIZED,
        [(0, "cell 1"), (62, "cell 2")],
    ),
}


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_canonical_text_is_exactly_the_golden(name):
    text, kind, mode, segments = GOLDEN[name]
    result = extract(name, (FIXTURES / name).read_bytes())
    assert result.text == text
    assert (result.kind, result.mode) == (kind, mode)
    assert result.segments == segments
    for start, label in result.segments:
        assert 0 <= start < len(result.text), label


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_extraction_is_deterministic(name):
    data = (FIXTURES / name).read_bytes()
    assert extract(name, data) == extract(name, data)


@pytest.mark.parametrize(
    ("name", "data", "message"),
    [
        ("empty.csv", b"", "no text"),
        ("header-only.csv", b"a,b,c\n", "no data rows"),
        ("empty.py", b"\n\n  \n", "no text"),
        ("broken.ipynb", b"{not json", "Not a readable notebook"),
        ("cellless.ipynb", json.dumps({"cells": []}).encode(), "no cells"),
        ("wrongshape.ipynb", json.dumps({"cells": "x"}).encode(), "Not a readable notebook"),
    ],
)
def test_malformed_and_empty_files_are_refused_by_name(name, data, message):
    with pytest.raises(ValueError, match=message):
        extract(name, data)


def test_an_oversized_table_is_refused_not_cut(monkeypatch):
    from research_engine import documents

    monkeypatch.setattr(documents, "MAX_TABLE_ROWS", 2)
    with pytest.raises(ValueError, match="rows by"):
        extract("big.csv", b"a,b\n1,2\n3,4\n5,6\n")


def test_a_csv_with_a_bom_and_windows_line_endings_reads_the_same():
    plain = extract("t.csv", b"Name,Year\nNorth,2021\n")
    windows = extract("t.csv", b"\xef\xbb\xbfName,Year\r\nNorth,2021\r\n")
    assert plain.text == windows.text == "Row 2 — Name: North; Year: 2021"


@pytest.mark.parametrize(
    ("name", "start", "end", "label"),
    [
        ("enrolment.csv", 52, 60, "row 3"),
        ("enrolment.csv", 0, 70, "rows 2–3"),
        ("stats.py", 14, 40, "line 2"),
        ("stats.py", 0, 60, "lines 1–3"),
        ("analysis.ipynb", 62, 80, "cell 2"),
    ],
)
async def test_a_citation_names_its_location(tmp_path, name, start, end, label):
    store = CorpusStore(tmp_path / "c.sqlite", FakeEmbeddings())
    result = await store.ingest(name, (FIXTURES / name).read_bytes())
    page = await store.read(corpus_url(result.doc_id, start=start, end=end, page=None))
    assert page["error"] is None, page
    assert label in page["title"], page["title"]
