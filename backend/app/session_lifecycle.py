"""
The session status write a user's stop has to win against — one home for both hosts.

A stopped session stays stopped (issue #54), and for sessions that holds only as far as
every writer honours `cancelled_at`: unlike runs, sessions have no `ck_run_cancelled`
underneath them to refuse a bad write (`0019_sessions_cancelled_at.py`). The outcome
writers do honour it. The start write did not.

Both drivers — `app/workers/pipeline_runner.py::_execute` and `desktop/sidecar.py`'s
`_drive_session` — set RUNNING when they pick a session up, and the start route commits the
row and hands it over before they do. A stop landing in that window was overwritten: the
row went back to RUNNING with `cancelled_at` still set, and because every outcome writer
refuses to move a cancelled session, it then sat on RUNNING for good. The desktop's
cancellation test lost that race on `main`'s CI after passing on the pull request.

Host-free, like `app/run_lifecycle.py`: both hosts import it, so it may not reach
`app.config`, Redis or Celery.
"""

from __future__ import annotations

import uuid

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session, SessionStatus


async def mark_running(db: AsyncSession, session_id: uuid.UUID) -> bool:
    """Move the session to RUNNING unless the user has stopped it. True if it moved.

    The condition is part of the UPDATE rather than a read before it, so a stop that
    commits between the driver loading the row and this write still wins. The loaded
    object is deliberately left alone — a caller that needs the status afterwards
    re-reads the row.
    """
    result = await db.execute(
        update(Session)
        .where(Session.id == session_id, Session.cancelled_at.is_(None))
        .values(status=SessionStatus.RUNNING)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1
