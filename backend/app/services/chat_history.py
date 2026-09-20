"""The model's view of a conversation: the most recent turns, in the order they happened.

Two things have to be true at once, and the query this replaces had neither.

The window must be the **newest** turns. `ORDER BY created_at ASC LIMIT 20` took the first
twenty messages ever written, so past turn twenty the model stopped seeing the conversation
— and because every caller commits the user's new message *before* reading the window, and
builds its message list only from that window, it also stopped seeing the question it was
being asked.

And the turns must reach the model **oldest first**, because a transcript in reverse reads
as a different conversation. Selecting newest-first and reversing is what satisfies both;
changing only the `LIMIT` would satisfy neither.

One home for three callers — `app/api/v1/chat.py`, `app/api/v1/threads.py` and
`desktop/sidecar.py`. This is a product rule that had been restated once per host, which is
the shape `AGENTS.md` records drifting every time it is kept in step by discipline.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_message import ChatMessage

#: How many turns of conversation the model is shown: enough for continuity, bounded so a
#: long thread cannot grow the prompt — and the bill — without limit. Report chat and
#: project threads have always used the same ceiling; they now read it from one place.
HISTORY_LIMIT = 20


async def recent_turns(db: AsyncSession, where, *, limit: int = HISTORY_LIMIT) -> list[ChatMessage]:
    """The newest `limit` messages matching `where`, returned oldest first.

    `where` rather than an id because the column is the only difference between the two
    conversations this serves: report chat scopes by `session_id`, project threads by
    `thread_id`, and `chat_messages` carries exactly one of them per row.
    """
    newest_first = (
        (
            await db.execute(
                select(ChatMessage)
                .where(where)
                .order_by(ChatMessage.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(reversed(newest_first))
