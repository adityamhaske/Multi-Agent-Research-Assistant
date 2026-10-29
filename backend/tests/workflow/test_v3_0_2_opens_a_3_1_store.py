"""
The shipped 3.0.2 engine opens a corpus that 3.1 wrote (RFC V3.1 §16 rollback; AC-24).

Downgrading to 3.0.x is supported on read. 3.0.x does not see what only 3.1 can write
(folders, the new kinds, selections), but it must not be corrupted by them either. So a store
is built here with this checkout's code, holding everything 3.1 adds. The `CorpusStore` from
the `v3.0.2` tag, byte-for-byte and in its own interpreter (`tests/released_code.py`), then
opens it, lists it, searches it and reads a legacy document. Then the store is checked again
with this checkout, so 3.0.2's own open-time migration is shown to have changed nothing 3.1
needs.

Supplementary to gate G-3, which launches the actual 3.0.2 application on such data.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from research_engine.corpus import CorpusStore, corpus_url
from research_engine.embeddings import FakeEmbeddings
from tests.released_code import released_engine

FORMATS = Path(__file__).resolve().parents[1] / "fixtures" / "formats"

PROBE = """
import asyncio, json, sys
sys.path.insert(0, {engine!r})
from research_engine import corpus as old
assert old.__file__.startswith({engine!r}), old.__file__
from research_engine.embeddings import FakeEmbeddings

async def main():
    store = old.CorpusStore({path!r}, FakeEmbeddings())
    docs = await store.documents()
    hits = await store.search("Enrolment rose in 2021", 5)
    page = await store.read({legacy_url!r})
    print(json.dumps({{
        "ids": sorted(d["id"] for d in docs),
        "kinds": sorted({{d["kind"] for d in docs}}),
        "hits": [h["url"] for h in hits],
        "read_error": page["error"],
        "read_text": page["text"][:60],
    }}))

asyncio.run(main())
"""


def _rows(path: Path) -> list[tuple]:
    with sqlite3.connect(path) as conn:
        return conn.execute(
            "SELECT id, doc_key, version, sha256, superseded_at FROM corpus_documents ORDER BY id"
        ).fetchall()


async def test_the_3_0_2_store_reads_a_3_1_corpus_and_leaves_it_intact(tmp_path):
    path = tmp_path / "corpus.sqlite"
    store = CorpusStore(path, FakeEmbeddings())
    legacy = await store.ingest("notes.txt", (FORMATS / "notes.txt").read_bytes())
    await store.ingest(
        "notes.txt", (FORMATS / "notes.txt").read_bytes() + b"Attendance fell.\n",
        doc_key=legacy.doc_key,
    )  # fmt: skip
    new_kinds = {}
    for name in ("report.docx", "budget.xlsx", "deck.pptx", "stats.py"):
        new_kinds[name] = await store.ingest(name, (FORMATS / name).read_bytes())
    folder = await store.ensure_folder_path(["Thesis", "Chapter 2"])
    await store.add_membership(new_kinds["report.docx"].doc_key, folder, "report.docx")
    before, tables_before = _rows(path), await store.folders()

    engine = released_engine("v3.0.2", tmp_path / "v3.0.2")
    probe = PROBE.format(
        engine=str(engine),
        path=str(path),
        legacy_url=corpus_url(legacy.doc_id, start=0, end=40, page=None),
    )
    done = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, cwd=tmp_path
    )

    assert done.returncode == 0, done.stderr[-2000:]
    seen = json.loads(done.stdout.strip().splitlines()[-1])
    assert legacy.doc_id in seen["ids"], "3.0.2 lists the document it could have written"
    assert seen["hits"], "and searches the corpus"
    assert seen["read_error"] is None and seen["read_text"].startswith("Enrolment rose 12%")

    # 3.0.2 ran its own open-time migration on the file. 3.1 must find it as it left it.
    assert _rows(path) == before
    assert await CorpusStore(path, FakeEmbeddings()).folders() == tables_before
