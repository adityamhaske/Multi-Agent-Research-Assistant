"""
Deleting a project must not orphan its corpus file (app/api/v1/projects.py).

The project model documents "no orphan vectors after a delete" as a guarantee it holds
for project memory (an ON DELETE CASCADE at the database level). The airgapped corpus
(docs/12 M10) is a standalone SQLite file keyed by project_id with no foreign key
pointing at it, so nothing enforced the same guarantee for it — `delete_project` deleted
every row and every LangGraph checkpoint and left `corpus_<project_id>.sqlite` behind
forever, unreachable by any route once the project was gone.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_user
from app.models.project import Project
from app.models.user import User
from tests.dataflow.test_project_memory import StubEmbeddings

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def user(db: AsyncSession) -> User:
    u = User(id=uuid.uuid4(), email="corpus-delete@example.com", hashed_pw="...", display_name="U")
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@pytest.fixture
async def project(db: AsyncSession, user: User) -> Project:
    p = Project(id=uuid.uuid4(), name="Deletable", user_id=user.id)
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


@pytest.fixture
async def auth_client(user: User, monkeypatch):
    from app.main import app

    async def _mock_embeddings_for(*args, **kwargs):
        return StubEmbeddings()

    monkeypatch.setattr("app.api.v1.corpus.embeddings_for", _mock_embeddings_for)

    app.dependency_overrides[get_current_user] = lambda: user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


async def test_delete_project_removes_its_corpus_file(
    auth_client: AsyncClient, project: Project
) -> None:
    files = {"file": ("doc.txt", b"content the corpus should not outlive.", "text/plain")}
    upload = await auth_client.post(f"/api/v1/projects/{project.id}/corpus/documents", files=files)
    assert upload.status_code == 200, upload.json()

    corpus_file = settings.corpus_path / f"corpus_{project.id}.sqlite"
    assert corpus_file.exists(), "precondition: ingest must have created the corpus file"

    resp = await auth_client.delete(f"/api/v1/projects/{project.id}")
    assert resp.status_code == 204

    assert not corpus_file.exists(), "corpus file must not survive its project's deletion"
    for suffix in ("-wal", "-shm"):
        assert not corpus_file.with_name(corpus_file.name + suffix).exists()


async def test_delete_project_without_a_corpus_file_still_succeeds(
    auth_client: AsyncClient, project: Project
) -> None:
    """No document was ever ingested, so no corpus file exists — unlink must be a no-op,
    not a FileNotFoundError that turns a clean delete into a 500."""
    resp = await auth_client.delete(f"/api/v1/projects/{project.id}")
    assert resp.status_code == 204
