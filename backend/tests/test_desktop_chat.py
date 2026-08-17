"""
Follow-up chat on the desktop host (docs/07 §2, Phase 5 completion).

The sidecar implemented **no chat routes at all**, while `frontend/.../ChatPanel.tsx`
renders on desktop and POSTs to one — so clicking Send on a finished desktop report hit
a 404. Not a missing feature behind a flag: a shipped, reachable control that failed.
That is the "two hosts, one contract" bug AGENTS.md opens with, in its purest form —
the server path is exercised constantly and the desktop path only at release time.

These run against the real sidecar app, the real SQLite file, the real graph in fake
mode and the real SSE contract, because the desktop host is a thin adapter and testing
it through HTTP is the honest scope (same reasoning as `test_desktop_sidecar.py`).
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import pytest_asyncio

TOKEN = "test-sidecar-token"


@pytest_asyncio.fixture
async def sidecar(tmp_path):
    from desktop.sidecar import create_sidecar_app

    app = create_sidecar_app(data_dir=tmp_path, token=TOKEN, fake=True)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9") as client:
            yield client


def _auth() -> dict:
    return {"Authorization": f"Bearer {TOKEN}"}


async def _completed_session(client) -> str:
    """Run a fake session all the way to COMPLETED — chat needs a finished report."""
    start = await client.post(
        "/api/v1/research",
        headers=_auth(),
        json={"query": "What is retrieval-augmented generation?", "depth": "fast"},
    )
    sid = start.json()["session_id"]

    for _ in range(60):
        body = (await client.get(f"/api/v1/research/{sid}", headers=_auth())).json()
        if body["status"] == "AWAITING_APPROVAL":
            break
        assert body["status"] != "FAILED", body.get("error_message")
        await asyncio.sleep(0.2)
    else:
        raise AssertionError("session never reached the review gate")

    await client.post(f"/api/v1/research/{sid}/approve", headers=_auth(), json={"approved": True})
    for _ in range(60):
        body = (await client.get(f"/api/v1/research/{sid}", headers=_auth())).json()
        if body["status"] == "COMPLETED":
            return sid
        await asyncio.sleep(0.2)
    raise AssertionError("session never completed")


def _sse_events(text: str) -> list[dict]:
    events = []
    for line in text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: ") :]))
    return events


# ── The gap itself ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_desktop_chat_endpoint_exists_at_all(sidecar):
    """The regression in one line: this route 404'd while the UI that calls it shipped."""
    sid = await _completed_session(sidecar)
    resp = await sidecar.get(f"/api/v1/research/{sid}/chat", headers=_auth())
    assert resp.status_code == 200, "the desktop build renders a chat panel for this route"
    assert resp.json() == []


@pytest.mark.asyncio
async def test_a_follow_up_streams_an_answer_and_persists_both_turns(sidecar):
    sid = await _completed_session(sidecar)

    resp = await sidecar.post(
        f"/api/v1/research/{sid}/chat",
        headers=_auth(),
        json={"message": "What were the limitations?"},
    )
    assert resp.status_code == 200
    events = _sse_events(resp.text)
    assert events[0]["type"] == "connected"
    assert any(e["type"] == "chunk" for e in events), "the answer must actually stream"
    assert events[-1]["type"] == "done"

    history = (await sidecar.get(f"/api/v1/research/{sid}/chat", headers=_auth())).json()
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[0]["content"] == "What were the limitations?"
    assert history[1]["content"], "an empty assistant turn is a failed answer stored as success"


@pytest.mark.asyncio
async def test_chat_is_refused_before_the_report_is_final(sidecar):
    """Same contract as the server: grounding in a draft the human has not approved
    would let an unapproved claim be quoted back as settled."""
    start = await sidecar.post(
        "/api/v1/research",
        headers=_auth(),
        json={"query": "What is retrieval-augmented generation?", "depth": "fast"},
    )
    sid = start.json()["session_id"]

    resp = await sidecar.post(
        f"/api/v1/research/{sid}/chat", headers=_auth(), json={"message": "anything"}
    )
    assert resp.status_code == 400
    assert "completed" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_an_unauthenticated_follow_up_is_rejected(sidecar):
    resp = await sidecar.post("/api/v1/research/x/chat", json={"message": "hi"})
    assert resp.status_code in (401, 403)


# ── Scope parity ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_scope_selector_is_not_a_control_that_does_nothing(sidecar):
    """`ScopeSelector` is already mounted on the desktop panel. The host has to honour
    the field, or it is a segmented control that changes what the user believes and not
    what the run reads — the "accepted by the schema, dropped on the floor" bug."""
    sid = await _completed_session(sidecar)

    resp = await sidecar.post(
        f"/api/v1/research/{sid}/chat",
        headers=_auth(),
        json={"message": "anything new since?", "scope": "corpus"},
    )
    assert resp.status_code == 200
    connected = _sse_events(resp.text)[0]
    # Echoed back so the answer can state which scope produced it — same frame shape as
    # the server (`app/api/v1/chat.py`).
    assert connected["scope"] == "corpus"
    assert "sources" in connected and "notes" in connected


@pytest.mark.asyncio
async def test_an_omitted_scope_still_means_report(sidecar):
    """Default parity with the server: a client that has not been updated gets today's
    grounding, not a silently widened one."""
    sid = await _completed_session(sidecar)
    resp = await sidecar.post(
        f"/api/v1/research/{sid}/chat", headers=_auth(), json={"message": "recap?"}
    )
    assert _sse_events(resp.text)[0]["scope"] == "report"
