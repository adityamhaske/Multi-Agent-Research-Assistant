"""
Tests for Corpus endpoints.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models.project import Project
from app.models.user import User
from tests.dataflow.test_project_memory import StubEmbeddings

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def user(db: AsyncSession) -> User:
    u = User(
        id=uuid.uuid4(),
        email="test@example.com",
        hashed_pw="...",
        display_name="Test User",
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@pytest.fixture
async def project(db: AsyncSession, user: User) -> Project:
    p = Project(
        id=uuid.uuid4(),
        name="Test Project",
        user_id=user.id,
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


@pytest.fixture
async def other_project(db: AsyncSession) -> Project:
    u = User(
        id=uuid.uuid4(),
        email="other@example.com",
        hashed_pw="...",
        display_name="Other User",
    )
    db.add(u)
    await db.commit()
    p = Project(
        id=uuid.uuid4(),
        name="Other Project",
        user_id=u.id,
    )
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


async def test_corpus_api_lifecycle(
    auth_client: AsyncClient,
    project: Project,
    db: AsyncSession,
) -> None:
    # 1. Upload a document
    file_content = b"This is a test document."
    files = {"file": ("test.txt", file_content, "text/plain")}
    response = await auth_client.post(
        f"/api/v1/projects/{project.id}/corpus/documents",
        files=files,
    )
    assert response.status_code == 200, response.json()
    doc = response.json()
    assert doc["filename"] == "test.txt"
    assert "id" in doc
    doc_id = doc["id"]

    # 2. List documents
    response = await auth_client.get(f"/api/v1/projects/{project.id}/corpus/documents")
    assert response.status_code == 200
    docs = response.json()
    assert len(docs) == 1
    assert docs[0]["id"] == doc_id

    # 3. Status
    response = await auth_client.get(f"/api/v1/projects/{project.id}/corpus/status")
    assert response.status_code == 200
    status_data = response.json()
    assert status_data["documents"] == 1

    # 4. Delete document
    response = await auth_client.delete(f"/api/v1/projects/{project.id}/corpus/documents/{doc_id}")
    assert response.status_code == 204

    # 5. List again, should be empty
    response = await auth_client.get(f"/api/v1/projects/{project.id}/corpus/documents")
    assert response.status_code == 200
    assert len(response.json()) == 0


async def test_corpus_isolation(
    auth_client: AsyncClient,
    other_project: Project,
) -> None:
    file_content = b"Hacked document."
    files = {"file": ("hack.txt", file_content, "text/plain")}
    response = await auth_client.post(
        f"/api/v1/projects/{other_project.id}/corpus/documents",
        files=files,
    )
    assert response.status_code == 404
