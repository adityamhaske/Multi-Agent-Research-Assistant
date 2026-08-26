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
