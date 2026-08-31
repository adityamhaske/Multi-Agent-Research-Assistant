import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.v1.projects import _counts


@pytest.mark.asyncio
async def test_project_counts_combines_v1_and_v2():
    pid1 = uuid.uuid4()
    pid2 = uuid.uuid4()

    db = MagicMock()

    class FakeResult:
        def __init__(self, data):
            self._data = data

        def all(self):
            return self._data

    db.execute = AsyncMock(
        side_effect=[
            FakeResult([(pid1, 2)]),  # v1 rows
            FakeResult([(pid1, 1), (pid2, 4)]),  # v2 rows
        ]
    )

    counts = await _counts(db, [pid1, pid2])
    assert counts[pid1] == 3
    assert counts[pid2] == 4


# ── Desktop: does the sidecar's own project list count what the server counts? ──────


@pytest.mark.asyncio
async def test_desktop_project_list_counts_runs_not_only_sessions(tmp_path):
    """Drives the real sidecar rather than reading its source.

    A project with a v2 run and no v1 session must not show `session_count: 0` — that
    is the same undercount `_counts` was written to fix on the server (see
    `test_project_counts_combines_v1_and_v2` above), and until the desktop's project
    routes share that function instead of restating their own, nothing here proves the
    desktop actually applies the fix.
    """
    import httpx

    from desktop.sidecar import create_sidecar_app

    app = create_sidecar_app(data_dir=tmp_path, token="proj-count", fake=True)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://d.invalid") as client:
            headers = {"Authorization": "Bearer proj-count"}
            created = await client.post(
                "/api/v1/projects", json={"name": "Has A Run"}, headers=headers
            )
            assert created.status_code == 201
            project_id = created.json()["id"]

            run = await client.post(
                "/api/v1/runs",
                json={"project_id": project_id, "question": "Does this project count runs?"},
                headers=headers,
            )
            assert run.status_code == 201

            listed = await client.get("/api/v1/projects", headers=headers)
            row = next(p for p in listed.json()["projects"] if p["id"] == project_id)
            assert row["session_count"] == 1, (
                f"the desktop's project list did not count a v2 run — got {row['session_count']}"
            )
