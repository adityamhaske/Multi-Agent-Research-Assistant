"""
Reopening a document a run or session cited, wherever it lives now
(internal/rfcs/V3.1-corpus-scope.md §7.3; AC-27, second bullet).

**Desktop.** A real data directory holding a 3.0.x shared corpus is started, so the documents
move into "Documents from before 3.1". Then a run and a session recorded before the move are
written into another project. Their citation opens from that project through the narrow route,
and nothing else in the legacy project does.

**Server.** Each refusal rule, through the shared handler with a real store:
- an uncited version;
- a changed hash;
- a different corpus;
- someone else's run.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import run_lifecycle
from app.api.v1.runs import download_cited_document, get_cited_document_text
from app.errors import NotFound
from app.models.project import Project
from app.models.session import Session, SessionStatus
from app.models.user import User
from desktop import corpus_layout
from desktop.sidecar import create_sidecar_app
from research_engine.corpus import CorpusStore, corpus_url
from tests.dataflow.test_corpus_store import SOLAR_TEXT, VENTS_TEXT, FakeEmbeddings
from tests.sqlite_support import open_db

TOKEN = "cited-documents-token"
NOW = datetime(2026, 10, 28, tzinfo=UTC)


def _auth() -> dict:
    return {"Authorization": f"Bearer {TOKEN}"}


def _evidence(url: str) -> list[dict]:
    return [
        {"task_id": 1, "source_url": url, "source_title": "solar.txt", "snippet": SOLAR_TEXT[:60]}
    ]


# ── Desktop: a citation made before the move ──────────────────────────────────────


@pytest.fixture
async def migrated(tmp_path):
    """A started desktop whose 3.0.x shared corpus moved, plus a pre-3.1 run and session in
    another project that each cited `solar` (and not `vents`)."""
    legacy = CorpusStore(tmp_path / corpus_layout.LEGACY_FILENAME, FakeEmbeddings())
    solar = await legacy.ingest("solar.txt", SOLAR_TEXT.encode())
    vents = await legacy.ingest("vents.txt", VENTS_TEXT.encode())
    cited = corpus_url(solar.doc_id, start=0, end=60, page=None)

    app = create_sidecar_app(data_dir=tmp_path, token=TOKEN, fake=True)
    async with app.router.lifespan_context(app):
        app.state.sidecar["corpus"].embedder = FakeEmbeddings()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9") as client:
            made = await client.post("/api/v1/projects", headers=_auth(), json={"name": "Thesis"})
            thesis = uuid.UUID(made.json()["id"])

            engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'desktop.sqlite'}")
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as db:
                user_id = app.state.sidecar["user_id"]
                run = await run_lifecycle.create_run(
                    db, owner_id=user_id, project_id=thesis, question="q", corpus_mode=True
                )
                run.evidence_outcome = "READ"
                await run_lifecycle.record_evidence(
                    db,
                    run,
                    evidence=_evidence(cited),
                    numbered_sources=[{"index": 1, "url": cited, "title": "solar.txt"}],
                )
                session_id = uuid.uuid4()
                db.add(
                    Session(
                        id=session_id,
                        user_id=user_id,
                        project_id=thesis,
                        prompt="q",
                        status=SessionStatus.COMPLETED,
                        sources=[{"index": 1, "url": cited, "title": "solar.txt"}],
                    )
                )
                await db.commit()
            await engine.dispose()

            yield {
                "client": client,
                "thesis": thesis,
                "run": run.id,
                "session": session_id,
                "solar": solar.doc_id,
                "vents": vents.doc_id,
            }


@pytest.mark.parametrize("kind", ["runs", "research"])
async def test_a_citation_from_before_the_move_still_opens(migrated, kind):
    client, item = migrated["client"], migrated["run" if kind == "runs" else "session"]
    base = f"/api/v1/{kind}/{item}/cited-documents/{migrated['solar']}"

    text = await client.get(base, headers=_auth())
    assert text.status_code == 200, text.text
    assert text.json()["text"].startswith(SOLAR_TEXT[:40])

    original = await client.get(f"{base}/download", headers=_auth())
    assert original.status_code == 200, original.text
    assert original.content == SOLAR_TEXT.encode()


@pytest.mark.parametrize("kind", ["runs", "research"])
async def test_nothing_else_in_the_legacy_project_opens(migrated, kind):
    client, item = migrated["client"], migrated["run" if kind == "runs" else "session"]
    missing = await client.get(
        f"/api/v1/{kind}/{item}/cited-documents/no-such-document", headers=_auth()
    )
    uncited = await client.get(
        f"/api/v1/{kind}/{item}/cited-documents/{migrated['vents']}", headers=_auth()
    )
    assert uncited.status_code == missing.status_code == 404
    assert uncited.json() == missing.json(), "an uncited document reads as a missing one"


async def test_the_project_routes_still_do_not_reach_the_legacy_store(migrated):
    """The narrow route is the only way back: the citing project still has no such document."""
    client, thesis, solar = migrated["client"], migrated["thesis"], migrated["solar"]
    resp = await client.get(
        f"/api/v1/projects/{thesis}/corpus/documents/{solar}/text", headers=_auth()
    )
    assert resp.status_code == 404


# ── Server: every refusal rule ────────────────────────────────────────────────────


class _Locator:
    def __init__(self, stores: dict) -> None:
        self._stores = stores

    async def for_project(self, project_id, *, keys=None):  # noqa: ARG002
        return self._stores.get(project_id)


@pytest.fixture
async def server(tmp_path):
    store = CorpusStore(tmp_path / "corpus.sqlite", FakeEmbeddings())
    solar = await store.ingest("solar.txt", SOLAR_TEXT.encode())
    vents = await store.ingest("vents.txt", VENTS_TEXT.encode())
    cited = corpus_url(solar.doc_id, start=0, end=60, page=None)
    corpus_id, _ = await store.identity()
    async with open_db(tmp_path / "runs.sqlite") as maker, maker() as db:
        owner, stranger, pid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        for uid in (owner, stranger):
            await db.execute(
                insert(User).values(
                    id=uid, email=f"{uid}@x.invalid", hashed_pw="x", is_active=True, created_at=NOW
                )
            )
        await db.execute(
            insert(Project).values(id=pid, user_id=owner, name="P", created_at=NOW, updated_at=NOW)
        )
        await db.commit()
        run = await run_lifecycle.create_run(
            db,
            owner_id=owner,
            project_id=pid,
            question="q",
            corpus_mode=True,
            corpus_selection={
                "resolved": [
                    {"document_id": solar.doc_id, "sha256": await store.sha256_of(solar.doc_id)}
                ],
                "corpus_id": corpus_id,
            },
        )
        run.corpus_id = corpus_id
        run.evidence_outcome = "READ"
        await run_lifecycle.record_evidence(
            db,
            run,
            evidence=_evidence(cited),
            numbered_sources=[{"index": 1, "url": cited, "title": "solar.txt"}],
        )
        await db.commit()
        yield {
            "db": db,
            "run": run,
            "owner": await db.get(User, owner),
            "stranger": await db.get(User, stranger),
            "locator": _Locator({pid: store}),
            "solar": solar.doc_id,
            "vents": vents.doc_id,
        }


async def _open(server, document_id, *, user="owner"):
    return await get_cited_document_text(
        server["run"].id, document_id, server["db"], server[user], server["locator"], []
    )


async def test_the_server_opens_exactly_what_the_run_cited(server):
    found = await _open(server, server["solar"])
    assert found.text.startswith(SOLAR_TEXT[:40])
    original = await download_cited_document(
        server["run"].id, server["solar"], server["db"], server["owner"], server["locator"], []
    )
    assert original.body == SOLAR_TEXT.encode()


async def test_an_uncited_version_in_the_same_store_is_not_found(server):
    with pytest.raises(NotFound):
        await _open(server, server["vents"])


async def test_a_version_whose_hash_changed_is_not_found(server):
    server["run"].corpus_selection = {
        "resolved": [{"document_id": server["solar"], "sha256": "0" * 64}]
    }
    with pytest.raises(NotFound):
        await _open(server, server["solar"])


async def test_a_store_that_is_not_the_corpus_the_run_read_is_not_found(server):
    server["run"].corpus_id = "some-other-corpus"
    with pytest.raises(NotFound):
        await _open(server, server["solar"])


async def test_someone_elses_run_is_not_found(server):
    with pytest.raises(NotFound):
        await _open(server, server["solar"], user="stranger")
