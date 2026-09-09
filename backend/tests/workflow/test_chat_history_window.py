"""The model is shown the newest turns of a conversation, oldest first.

Both chat surfaces ran `ORDER BY created_at ASC LIMIT 20`, which is the *first* twenty
messages ever written rather than the last twenty. Past turn twenty the model stopped
seeing the conversation entirely — and because every caller commits the user's new message
before reading the window, and assembles its prompt only from that window, it also stopped
seeing the question it was being asked. Reproduced before the fix: with 25 turns written,
the model received `turn-00 … turn-19` and `turn-24` was absent.

Two properties have to hold together, which is why "change the LIMIT" is not the fix: the
window must be the newest turns, and it must reach the model in the order the turns
happened. A newest-first window handed straight to the prompt would be a transcript read
backwards.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import insert

from app.models.chat_message import ChatMessage
from app.models.chat_thread import ChatThread
from app.models.project import Project
from app.models.session import Session as SessionRow
from app.models.user import User
from app.services import chat_history
from tests.sqlite_support import open_db

NOW = datetime(2026, 9, 9, tzinfo=UTC)


@pytest.fixture
async def conversation(tmp_path):
    """A real session and a real thread, so both scopes are exercised against real rows."""
    async with open_db(tmp_path / "chat.sqlite") as maker, maker() as db:
        uid, pid = uuid.uuid4(), uuid.uuid4()
        sid, tid = uuid.uuid4(), uuid.uuid4()
        await db.execute(
            insert(User).values(
                id=uid, email=f"{uid}@x.invalid", hashed_pw="x", is_active=True, created_at=NOW
            )
        )
        await db.execute(
            insert(Project).values(id=pid, user_id=uid, name="P", created_at=NOW, updated_at=NOW)
        )
        await db.execute(
            insert(SessionRow).values(
                id=sid,
                user_id=uid,
                project_id=pid,
                prompt="q",
                status="COMPLETED",
                research_depth="fast",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await db.execute(
            insert(ChatThread).values(
                id=tid, project_id=pid, title="T", created_at=NOW, last_message_at=NOW
            )
        )
        await db.commit()
        yield db, sid, tid


async def _write_turns(db, count: int, *, session_id=None, thread_id=None) -> list[str]:
    """`count` turns with explicit, distinct timestamps.

    Explicit rather than server-defaulted because `now()` is transaction-start time on
    Postgres: a bulk insert would give every row the same instant and "the newest twenty"
    would have no meaning to assert. Production writes each turn in its own transaction,
    which is what this reproduces.
    """
    labels = [f"turn-{i:02d}" for i in range(count)]
    for i, label in enumerate(labels):
        await db.execute(
            insert(ChatMessage).values(
                id=uuid.uuid4(),
                session_id=session_id,
                thread_id=thread_id,
                role="user" if i % 2 == 0 else "assistant",
                content=label,
                created_at=NOW + timedelta(minutes=i),
            )
        )
    await db.commit()
    return labels


# ── The window ────────────────────────────────────────────────────────────────────


async def test_fewer_than_the_limit_returns_every_turn(conversation):
    db, sid, _ = conversation
    written = await _write_turns(db, 5, session_id=sid)

    got = await chat_history.recent_turns(db, ChatMessage.session_id == sid)

    assert [m.content for m in got] == written


async def test_exactly_the_limit_returns_every_turn(conversation):
    """The boundary. An off-by-one here drops the oldest turn for no reason."""
    db, sid, _ = conversation
    written = await _write_turns(db, chat_history.HISTORY_LIMIT, session_id=sid)

    got = await chat_history.recent_turns(db, ChatMessage.session_id == sid)

    assert len(got) == chat_history.HISTORY_LIMIT
    assert [m.content for m in got] == written


async def test_more_than_the_limit_keeps_the_newest_turns(conversation):
    """The defect. Before the fix this returned turn-00 … turn-19."""
    db, sid, _ = conversation
    written = await _write_turns(db, 25, session_id=sid)

    got = await chat_history.recent_turns(db, ChatMessage.session_id == sid)
    contents = [m.content for m in got]

    assert contents == written[-chat_history.HISTORY_LIMIT :]
    assert contents[-1] == "turn-24", "the newest turn must always be shown to the model"
    assert "turn-00" not in contents, "the oldest turns were retained instead of the newest"


async def test_the_window_reaches_the_model_in_chronological_order(conversation):
    """Selecting newest-first is half the fix; handing that to the prompt unreversed would
    be a transcript read backwards, which is a different conversation."""
    db, sid, _ = conversation
    await _write_turns(db, 25, session_id=sid)

    got = await chat_history.recent_turns(db, ChatMessage.session_id == sid)

    timestamps = [m.created_at for m in got]
    assert timestamps == sorted(timestamps), "history reached the model newest-first"


async def test_the_question_being_asked_is_always_in_the_window(conversation):
    """The sharpest consequence of the old ordering, and the reason this is a defect rather
    than a tuning choice: every caller commits the user's message *before* reading the
    window and builds its prompt only from the window, so an oldest-first window past turn
    twenty asked the model to answer a question it was never shown."""
    db, sid, _ = conversation
    await _write_turns(db, 40, session_id=sid)
    await db.execute(
        insert(ChatMessage).values(
            id=uuid.uuid4(),
            session_id=sid,
            role="user",
            content="the question actually being asked",
            created_at=NOW + timedelta(minutes=999),
        )
    )
    await db.commit()

    got = await chat_history.recent_turns(db, ChatMessage.session_id == sid)

    assert got[-1].content == "the question actually being asked"


async def test_project_threads_use_the_same_window(conversation):
    """`chat_messages` carries exactly one parent, so the column is the only difference
    between report chat and project threads. Both must window identically."""
    db, _, tid = conversation
    written = await _write_turns(db, 25, thread_id=tid)

    got = await chat_history.recent_turns(db, ChatMessage.thread_id == tid)

    assert [m.content for m in got] == written[-chat_history.HISTORY_LIMIT :]


async def test_the_window_does_not_leak_across_conversations(conversation):
    """The filter is the isolation boundary; a shared window must not widen it."""
    db, sid, tid = conversation
    await _write_turns(db, 3, session_id=sid)
    await _write_turns(db, 3, thread_id=tid)

    from_session = await chat_history.recent_turns(db, ChatMessage.session_id == sid)
    assert all(m.session_id == sid and m.thread_id is None for m in from_session)
    assert len(from_session) == 3


# ── One home ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "module_path",
    ["app.api.v1.chat", "app.api.v1.threads", "desktop.sidecar"],
)
def test_every_caller_resolves_to_the_same_window(module_path):
    """Identity, not equality. This rule had three copies — two on the server and one the
    desktop restated — and three copies that agree today are three copies."""
    import importlib

    module = importlib.import_module(module_path)
    assert module.recent_turns is chat_history.recent_turns, (
        f"{module_path} does not use the shared history window"
    )


def test_the_shared_window_is_imported_by_a_name_no_caller_shadows():
    """`desktop/sidecar.py` defines a route handler named `chat_history` inside
    `create_sidecar_app`. Importing the module under that name binds fine at module scope
    and is shadowed for the whole factory, so every chat request raises `AttributeError`
    at request time — which is what the desktop chat suite caught. Importing the function
    directly is what keeps the three callers uniform *and* collision-free."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    source = (root / "desktop/sidecar.py").read_text()
    assert "async def chat_history(" in source, "the shadowing handler was renamed; re-check"
    assert "from app.services import (\n    chat_history," not in source


def test_no_caller_still_windows_the_conversation_itself():
    """A surviving `created_at.asc()` beside a `limit` would be a fourth home waiting to
    drift back, even if nothing currently reaches it."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    for rel in ("app/api/v1/chat.py", "app/api/v1/threads.py", "desktop/sidecar.py"):
        source = (root / rel).read_text()
        assert ".limit(20)" not in source, f"{rel} still windows the conversation itself"
        assert "_HISTORY_LIMIT" not in source, f"{rel} still holds its own history ceiling"
