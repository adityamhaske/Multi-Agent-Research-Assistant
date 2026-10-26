"""
A selected-files run: request → frozen row → RunConfig → scoped port, on both hosts.

internal/rfcs/V3.1-corpus-scope.md §8 (AC-7, AC-8, AC-12). Every hop is the shipped one:
the server's `runs.create_run` handler against a real database and a real `CorpusStore`;
the desktop through its real routes, up to the engine's entry point. A hand-built
`RunConfig` would stub exactly the hop this exists to prove (root AGENTS.md: "A field on
the row is not a field the run reads").
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import insert

from app import run_execution
from app.api.v1.runs import create_run
from app.errors import NotFound, Unprocessable
from app.models.project import Project
from app.models.research import ResearchRun
from app.models.user import User
from app.schemas.runs import CreateRunRequest
from desktop.sidecar import create_sidecar_app
from research_engine.corpus import CorpusStore, ScopedCorpus
from tests.dataflow.test_corpus_store import SOLAR_TEXT, VENTS_TEXT, FakeEmbeddings
from tests.sqlite_support import open_db

NOW = datetime(2026, 10, 25, tzinfo=UTC)
TOKEN = "test-selection-token"


class _NoDispatch:
    async def start(self, *_a, **_k):
        raise AssertionError("these tests create with dispatch=False")


class _Locator:
    """The host port that says where a project's corpus lives — here, one real store."""

    def __init__(self, store: CorpusStore | None) -> None:
        self._store = store

    async def for_project(self, project_id, *, keys=None):  # noqa: ARG002
        return self._store


@pytest.fixture
async def server(tmp_path):
    store = CorpusStore(tmp_path / "corpus.sqlite", FakeEmbeddings())
    solar = await store.ingest("solar.txt", SOLAR_TEXT.encode())
    vents = await store.ingest("vents.txt", VENTS_TEXT.encode())
    async with open_db(tmp_path / "runs.sqlite") as maker, maker() as db:
        uid, pid = uuid.uuid4(), uuid.uuid4()
        await db.execute(
            insert(User).values(
                id=uid, email=f"{uid}@x.invalid", hashed_pw="x", is_active=True, created_at=NOW
            )
        )
        await db.execute(
            insert(Project).values(id=pid, user_id=uid, name="P", created_at=NOW, updated_at=NOW)
        )
        await db.commit()
        user = await db.get(User, uid)
        yield {"db": db, "user": user, "pid": pid, "store": store, "solar": solar, "vents": vents}


async def _create(server, locator=None, **body) -> ResearchRun:
    request = CreateRunRequest(
        project_id=server["pid"], question="q", depth="fast", dispatch=False, **body
    )
    out = await create_run(
        request,
        server["db"],
        server["user"],
        _NoDispatch(),
        locator or _Locator(server["store"]),
    )
    await server["db"].commit()
    return await server["db"].get(ResearchRun, uuid.UUID(out["run_id"]))


async def test_a_selection_is_frozen_to_exact_versions_and_reaches_the_engine(server):
    row = await _create(server, corpus_selection={"doc_keys": [server["solar"].doc_key]})

    assert row.corpus_mode is True, "a selection is corpus-only research"
    resolved = row.corpus_selection["resolved"]
    assert [item["document_id"] for item in resolved] == [server["solar"].doc_id]

    config = await run_execution.run_config_for_run(server["db"], row)
    assert config.corpus_mode is True
    assert config.corpus_allowed_ids == frozenset({server["solar"].doc_id})

    port = run_execution.corpus_port_for(server["store"], config)
    assert isinstance(port, ScopedCorpus)
    assert port.allowed_ids == frozenset({server["solar"].doc_id})


async def test_the_selection_does_not_move_when_the_document_is_superseded(server):
    row = await _create(server, corpus_selection={"doc_keys": [server["solar"].doc_key]})
    newer = await server["store"].ingest(
        "solar.txt", VENTS_TEXT.encode(), doc_key=server["solar"].doc_key
    )

    config = await run_execution.run_config_for_run(server["db"], row)
    assert config.corpus_allowed_ids == frozenset({server["solar"].doc_id})
    assert newer.doc_id not in config.corpus_allowed_ids


async def test_corpus_mode_without_a_selection_freezes_the_whole_corpus(server):
    row = await _create(server, corpus_mode=True)

    assert row.corpus_selection["requested"]["whole_corpus"] is True
    config = await run_execution.run_config_for_run(server["db"], row)
    assert config.corpus_allowed_ids == frozenset({server["solar"].doc_id, server["vents"].doc_id})


async def test_a_web_run_carries_no_selection(server):
    row = await _create(server)

    assert row.corpus_selection is None
    config = await run_execution.run_config_for_run(server["db"], row)
    assert config.corpus_allowed_ids is None
    assert run_execution.corpus_port_for(server["store"], config) is server["store"]


async def test_an_empty_selection_is_refused_before_the_run_exists(server):
    with pytest.raises(Unprocessable, match="Select at least one"):
        await _create(server, corpus_selection={"doc_keys": [], "folder_ids": []})
    assert (await server["db"].execute(ResearchRun.__table__.select())).first() is None


async def test_a_selection_that_resolves_to_nothing_is_refused(tmp_path, server):
    empty = CorpusStore(tmp_path / "empty.sqlite", FakeEmbeddings())
    with pytest.raises(Unprocessable, match="no documents"):
        await _create(server, locator=_Locator(empty), corpus_mode=True)
    with pytest.raises(Unprocessable, match="no documents"):
        await _create(server, locator=_Locator(None), corpus_mode=True)


async def test_an_unknown_file_or_folder_is_not_found_and_not_named(server):
    with pytest.raises(NotFound) as err:
        await _create(
            server, corpus_selection={"doc_keys": [server["solar"].doc_key, "someone-elses"]}
        )
    assert "someone-elses" not in str(err.value)

    with pytest.raises(NotFound):
        await _create(server, corpus_selection={"folder_ids": ["folder-1"]})


async def test_a_selection_with_corpus_mode_false_is_refused(server):
    with pytest.raises(Unprocessable, match="corpus_mode cannot be false"):
        await _create(
            server,
            corpus_mode=False,
            corpus_selection={"doc_keys": [server["solar"].doc_key]},
        )


async def test_the_run_builders_share_one_selection_rule():
    """Both hosts read the selection through the same function object (AGENTS.md)."""
    import desktop.sidecar as sidecar_mod

    source = sidecar_mod.__loader__.get_source(sidecar_mod.__name__)
    assert "run_execution.row_overrides(run)" in source
    assert "run_execution.corpus_port_for(" in source


# ── The desktop, through its real routes ──────────────────────────────────────────


async def test_a_desktop_selection_run_reaches_the_engine_scoped(monkeypatch, tmp_path):
    captured: dict = {}

    class _Stop(Exception):
        pass

    async def _capture(**kwargs):
        captured.update(kwargs)
        raise _Stop

    monkeypatch.setattr("desktop.sidecar.run_pipeline", _capture)

    app = create_sidecar_app(data_dir=tmp_path, token=TOKEN, fake=True)
    async with app.router.lifespan_context(app):
        app.state.sidecar["corpus"]._embedder = FakeEmbeddings()  # noqa: SLF001
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9") as client:
            auth = {"Authorization": f"Bearer {TOKEN}"}
            pid = (await client.post("/api/v1/projects", headers=auth, json={"name": "S"})).json()[
                "id"
            ]
            docs = []
            for name, text in (("solar.txt", SOLAR_TEXT), ("vents.txt", VENTS_TEXT)):
                up = await client.post(
                    f"/api/v1/projects/{pid}/corpus/documents",
                    headers=auth,
                    files={"file": (name, text.encode(), "text/plain")},
                )
                assert up.status_code == 201, up.text
                docs.append(up.json())

            refused = await client.post(
                "/api/v1/runs",
                headers=auth,
                json={"project_id": pid, "question": "q", "corpus_selection": {"doc_keys": []}},
            )
            assert refused.status_code == 422, refused.text

            created = await client.post(
                "/api/v1/runs",
                headers=auth,
                json={
                    "project_id": pid,
                    "question": "How do photovoltaic cells work?",
                    "depth": "fast",
                    "corpus_selection": {"doc_keys": [docs[0]["doc_key"]]},
                },
            )
            assert created.status_code == 201, created.text

            deadline = asyncio.get_event_loop().time() + 20
            while "run_config" not in captured and asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(0.01)

    assert "run_config" in captured, "the engine was never reached"
    config = captured["run_config"]
    assert config.corpus_mode is True
    assert config.corpus_allowed_ids == frozenset({docs[0]["id"]})
    assert isinstance(captured["corpus"], ScopedCorpus)
    assert captured["corpus"].allowed_ids == frozenset({docs[0]["id"]})


async def test_a_session_never_carries_a_selection():
    """Sessions are the earlier pipeline and do not take selections (RFC D-8, AC-12):
    a session in corpus mode keeps reading its project's whole corpus, as it always did."""
    import app.workers.pipeline_runner as runner_mod
    from app.models.session import Session as SessionRow
    from tests.dataflow.test_corpus_egress import _SessionDb

    row = SessionRow(prompt="q", research_depth="fast")
    row.corpus_mode = True
    row.demo = False

    cfg = await runner_mod._run_config_for(_SessionDb(), row, str(uuid.uuid4()))

    assert cfg.corpus_mode is True
    assert cfg.corpus_allowed_ids is None
