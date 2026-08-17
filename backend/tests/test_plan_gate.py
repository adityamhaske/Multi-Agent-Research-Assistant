"""
The research design gate (docs/07 §2, Phase 4; plan §3 Phase 4).

The engine primitives landed inert in 62b946d — `plan_gate_node` existed and
interrupted correctly, but nothing could resume *past* that interrupt, so activating it
would have stranded a real run. These tests cover the path that makes activation safe,
and they deliberately drive whole runs through `research_engine.runner` rather than
poking the node: the failure mode being guarded against is a session that pauses and can
never continue, which is only observable end-to-end.

Three claims, from the plan:

1. Resume-after-edit is checkpoint-durable — the planner does not re-run.
2. An edited plan actually changes what the executor researches.
3. `skip_plan_gate` bypasses the gate cleanly, end to end.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
import pytest_asyncio
from langgraph.checkpoint.memory import MemorySaver

from research_engine import events
from research_engine.runconfig import RunConfig
from research_engine.runner import resume, run

QUERY = "What is the state of AI research assistants in 2026?"

#: The gate is on. This is what both hosts pass for a session whose `skip_plan_gate`
#: column is False (the product default); `RunConfig()`'s own bare default is the
#: opposite, and `test_pipeline.py` pins that dormancy.
GATE_ON = RunConfig(llm_mode="fake", skip_plan_gate=False)
GATE_OFF = RunConfig(llm_mode="fake", skip_plan_gate=True)


class _Collector:
    """Records emitted events so a test can assert on what the run actually did."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    async def __call__(self, session_id: str, event: dict) -> None:
        self.events.append(event)

    def agents(self) -> set[str]:
        return {e["agent"] for e in self.events if e.get("agent")}

    def researched_queries(self) -> list[str]:
        """Every task query the executor actually opened work on."""
        prefix = "Researching: "
        return [
            e["message"][len(prefix) :].strip("'")
            for e in self.events
            if e.get("agent") == "executor" and (e.get("message") or "").startswith(prefix)
        ]


# ── 1. Checkpoint durability ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_pauses_at_the_plan_gate_before_spending_on_search():
    """The whole point of the gate: it stops *before* the executor, so a user sees the
    plan while it is still free to change."""
    sink = _Collector()
    outcome = await run(
        checkpointer=MemorySaver(),
        session_id="plan-pause",
        user_id="u",
        query=QUERY,
        run_config=GATE_ON,
        event_sink=sink,
    )

    assert outcome.status == "awaiting_plan"
    assert outcome.plan_tasks, "the reviewer must be handed something to review"
    assert outcome.draft_report is None, "nothing is drafted at the plan gate"
    assert outcome.error is None, "an interrupt is not a failure"
    assert sink.agents() == {"planner"}, "no search ran before the human saw the plan"


@pytest.mark.asyncio
async def test_resume_after_edit_is_checkpoint_durable():
    """Resuming enters at the gate — the planner does not run a second time.

    Same guarantee `test_approval_finalizes_without_replanning` makes for the HITL gate,
    asserted the same way: a second planner call would be re-doing work the user already
    paid for, and would also discard the edits by overwriting the task list.
    """
    saver = MemorySaver()
    paused = await run(
        checkpointer=saver,
        session_id="plan-durable",
        user_id="u",
        query=QUERY,
        run_config=GATE_ON,
    )

    sink = _Collector()
    resumed = await resume(
        checkpointer=saver,
        session_id="plan-durable",
        plan={"tasks": paused.plan_tasks, "outline": paused.plan_outline},
        run_config=GATE_ON,
        event_sink=sink,
    )

    assert resumed.status == "awaiting_approval"
    assert resumed.draft_report
    assert "planner" not in sink.agents(), "resume must not re-plan"


@pytest.mark.asyncio
async def test_the_gate_is_passed_once_not_on_every_resume():
    """A plan-gated run still reaches the HITL gate and still approves from there.

    Guards the ordering bug this design invites: two interrupts on one thread, where
    approving the draft accidentally re-enters the plan gate and strands the session a
    second time.
    """
    saver = MemorySaver()
    paused = await run(
        checkpointer=saver, session_id="plan-once", user_id="u", query=QUERY, run_config=GATE_ON
    )
    at_hitl = await resume(
        checkpointer=saver,
        session_id="plan-once",
        plan={"tasks": paused.plan_tasks},
        run_config=GATE_ON,
    )
    assert at_hitl.status == "awaiting_approval"

    done = await resume(
        checkpointer=saver, session_id="plan-once", approved=True, run_config=GATE_ON
    )
    assert done.status == "completed"
    assert done.final_report


# ── 2. The edit has to change the run ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_edited_plan_changes_what_the_executor_researches():
    """A review gate that does not change the run is a rubber stamp.

    The reviewer drops one task and rewords the other; the executor must research the
    reworded query and nothing else.
    """
    saver = MemorySaver()
    paused = await run(
        checkpointer=saver, session_id="plan-edit", user_id="u", query=QUERY, run_config=GATE_ON
    )
    assert len(paused.plan_tasks) >= 2, (
        "fixture planner proposes >1 task; the edit needs one to drop"
    )

    kept, dropped = paused.plan_tasks[0], paused.plan_tasks[1]
    edited = [
        {**kept, "query": "reproducibility of agentic evaluation harnesses"},
        {**dropped, "include": False},
    ]

    sink = _Collector()
    await resume(
        checkpointer=saver,
        session_id="plan-edit",
        plan={"tasks": edited},
        run_config=GATE_ON,
        event_sink=sink,
    )

    researched = sink.researched_queries()
    assert "reproducibility of agentic evaluation harnesses" in researched
    assert dropped["query"] not in researched, "an excluded task must not be researched"


@pytest.mark.asyncio
async def test_an_unedited_resume_keeps_the_planner_proposal():
    """Approving without touching anything is a valid decision, not an empty plan.

    A resume that omits `tasks` means "unedited" — not "no tasks". Reading it as the
    latter would silently produce a report with no research in it.
    """
    saver = MemorySaver()
    paused = await run(
        checkpointer=saver, session_id="plan-noedit", user_id="u", query=QUERY, run_config=GATE_ON
    )
    proposed = [t["query"] for t in paused.plan_tasks]

    sink = _Collector()
    outcome = await resume(
        checkpointer=saver,
        session_id="plan-noedit",
        plan={},
        run_config=GATE_ON,
        event_sink=sink,
    )

    assert outcome.status == "awaiting_approval"
    assert sorted(sink.researched_queries()) == sorted(proposed)


# ── 3. The bypass ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skip_plan_gate_bypasses_the_gate_end_to_end():
    """Opting out runs planner → executor → … → HITL with no second pause anywhere,
    and still finishes. Asserted across the *whole* run rather than at the node, because
    a half-applied bypass would show up as a stranded resume, not a routing decision."""
    saver = MemorySaver()
    sink = _Collector()

    paused = await run(
        checkpointer=saver,
        session_id="plan-skip",
        user_id="u",
        query=QUERY,
        run_config=GATE_OFF,
        event_sink=sink,
    )
    assert paused.status == "awaiting_approval", "no plan gate for an opted-out run"
    assert paused.draft_report
    assert {"planner", "executor", "critic", "synthesizer"} <= sink.agents()

    done = await resume(
        checkpointer=saver, session_id="plan-skip", approved=True, run_config=GATE_OFF
    )
    assert done.status == "completed"
    assert done.final_report


@pytest.mark.asyncio
async def test_resume_refuses_an_ambiguous_decision():
    """`resume` carries two different decision shapes now. Guessing which one a caller
    meant — or defaulting to `approved` — is how a plan-gate resume silently becomes an
    approval of a draft that does not exist yet."""
    with pytest.raises(ValueError, match="exactly one"):
        await resume(checkpointer=MemorySaver(), session_id="plan-ambiguous")

    with pytest.raises(ValueError, match="exactly one"):
        await resume(
            checkpointer=MemorySaver(), session_id="plan-ambiguous", approved=True, plan={}
        )


@pytest.mark.asyncio
async def test_emitter_is_not_left_installed_by_a_gated_run():
    """Sanity that the plan-gate path unwinds its ports like every other run does."""
    sink = _Collector()
    await run(
        checkpointer=MemorySaver(),
        session_id="plan-ports",
        user_id="u",
        query=QUERY,
        run_config=GATE_ON,
        event_sink=sink,
    )
    seen = len(sink.events)
    await events.emit("plan-ports", "agent_log", agent="planner", message="after the run")
    assert len(sink.events) == seen


# ── 4. The server host maps the new outcome ────────────────────────────────────────
#
# The live server path needs Postgres and skips without one, so the mapping itself is
# asserted here against a real ORM object and a real RunOutcome with only the DB session
# faked. The equivalent desktop path runs for real over HTTP a few tests down — between
# them both homes of this contract are covered (AGENTS.md, "two hosts, one contract").


class _FakeDb:
    """Just enough AsyncSession for `_persist_outcome`: it only ever commits."""

    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_server_persists_awaiting_plan_and_emits_plan_ready():
    from app.models.session import Session as SessionRow
    from app.models.session import SessionStatus
    from app.workers.pipeline_runner import _persist_outcome
    from research_engine.runner import RunOutcome

    published: list[dict] = []

    async def sink(session_id: str, event: dict) -> None:
        published.append(event)

    row = SessionRow(prompt="q", research_depth="fast")
    outcome = RunOutcome(
        status="awaiting_plan",
        plan_tasks=[{"id": 1, "query": "background", "include": True}],
        plan_outline=[{"title": "Background", "description": ""}],
        cost_usd=0.01,
    )

    await _persist_outcome(_FakeDb(), row, "sess-1", outcome, sink)

    assert row.status == SessionStatus.AWAITING_PLAN
    assert row.plan_json == {"tasks": outcome.plan_tasks}
    assert row.outline_json == {"sections": outcome.plan_outline}
    assert row.plan_approved_at is None, "the reviewer has not decided yet"
    assert row.draft_report is None
    assert [e["type"] for e in published] == ["PLAN_READY"]
    assert published[0]["data"]["task_count"] == 1


@pytest.mark.asyncio
async def test_server_still_maps_the_draft_gate_unchanged():
    """The branch added above must not have moved the HITL mapping underneath it."""
    from app.models.session import Session as SessionRow
    from app.models.session import SessionStatus
    from app.workers.pipeline_runner import _persist_outcome
    from research_engine.runner import RunOutcome

    published: list[dict] = []

    async def sink(session_id: str, event: dict) -> None:
        published.append(event)

    row = SessionRow(prompt="q", research_depth="fast")
    await _persist_outcome(
        _FakeDb(),
        row,
        "sess-2",
        RunOutcome(status="awaiting_approval", draft_report="# Draft\n\nBody [1]."),
        sink,
    )

    assert row.status == SessionStatus.AWAITING_APPROVAL
    assert row.draft_report == "# Draft\n\nBody [1]."
    assert [e["type"] for e in published] == ["HITL_READY"]


# ── 5. The desktop host, over real HTTP ────────────────────────────────────────────
#
# The claim this phase has to make is "a real run can go through the gate and come back
# out", and only a whole-host test can make it. The sidecar is that host here: it runs
# the real graph, the real SQLite file, the real endpoints and the real SSE contract
# in-process, where the server path needs a Postgres CI does have and a laptop may not.


@pytest_asyncio.fixture
async def sidecar(tmp_path):
    from desktop.sidecar import create_sidecar_app

    app = create_sidecar_app(data_dir=tmp_path, token=_TOKEN, fake=True)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9") as client:
            yield client


_TOKEN = "test-sidecar-token"


def _auth() -> dict:
    return {"Authorization": f"Bearer {_TOKEN}"}


async def _until(client, session_id: str, want: str, tries: int = 60) -> dict:
    for _ in range(tries):
        resp = await client.get(f"/api/v1/research/{session_id}", headers=_auth())
        assert resp.status_code == 200
        body = resp.json()
        if body["status"] == want:
            return body
        assert body["status"] != "FAILED" or want == "FAILED", (
            f"session failed while waiting for {want}: {body.get('error_message')}"
        )
        await asyncio.sleep(0.2)
    raise AssertionError(f"session never reached {want}")


@pytest.mark.asyncio
async def test_desktop_run_pauses_at_the_plan_gate_then_resumes_to_a_finished_report(sidecar):
    """The whole journey, over HTTP: start → pause at the plan gate → read the proposal
    → submit edits → draft gate → approve → COMPLETED.

    This is the test that says the gate is safe to switch on. Every piece below existed
    in some form after the groundwork commit; none of them together did, which is exactly
    why that commit left the switch off.
    """
    start = await sidecar.post(
        "/api/v1/research",
        headers=_auth(),
        json={
            "query": "What is retrieval-augmented generation?",
            "depth": "fast",
            "skip_plan_gate": False,
        },
    )
    assert start.status_code == 202
    sid = start.json()["session_id"]

    detail = await _until(sidecar, sid, "AWAITING_PLAN")
    assert not detail["draft_report"], "nothing is drafted before the plan is approved"

    proposal = await sidecar.get(f"/api/v1/research/{sid}/plan", headers=_auth())
    assert proposal.status_code == 200
    tasks = proposal.json()["tasks"]
    assert tasks, "the reviewer must be handed the planner's proposal"

    edited = [
        {**tasks[0], "query": "how RAG grounding is evaluated", "subtopics": ["recall", "faith"]}
    ] + [{**t, "include": False} for t in tasks[1:]]
    submitted = await sidecar.post(
        f"/api/v1/research/{sid}/plan",
        headers=_auth(),
        json={
            "tasks": edited,
            "outline": [{"title": "Background", "description": "framing"}],
        },
    )
    assert submitted.status_code == 200

    detail = await _until(sidecar, sid, "AWAITING_APPROVAL")
    assert detail["draft_report"]

    approve = await sidecar.post(
        f"/api/v1/research/{sid}/approve", headers=_auth(), json={"approved": True}
    )
    assert approve.status_code == 200
    done = await _until(sidecar, sid, "COMPLETED")
    assert done["final_report"]
    assert done["sources"], "a report that came through the plan gate still cites"


@pytest.mark.asyncio
async def test_desktop_plan_decision_is_persisted_not_just_passed_through(sidecar):
    """`plan_json`/`outline_json` record what the reviewer decided, so the report stays
    attributable to a research design after the fact — the same reason `model_routing`
    is snapshotted rather than read back from a live preference."""
    start = await sidecar.post(
        "/api/v1/research",
        headers=_auth(),
        json={"query": "What is retrieval-augmented generation?", "skip_plan_gate": False},
    )
    sid = start.json()["session_id"]
    await _until(sidecar, sid, "AWAITING_PLAN")

    tasks = (await sidecar.get(f"/api/v1/research/{sid}/plan", headers=_auth())).json()["tasks"]
    outline = [{"title": "Findings", "description": "what the sources say"}]
    await sidecar.post(
        f"/api/v1/research/{sid}/plan",
        headers=_auth(),
        json={"tasks": [{**tasks[0], "query": "grounding metrics"}], "outline": outline},
    )
    await _until(sidecar, sid, "AWAITING_APPROVAL")

    after = (await sidecar.get(f"/api/v1/research/{sid}/plan", headers=_auth())).json()
    assert after["approved_at"], "an approved plan records when it was approved"
    assert [t["query"] for t in after["tasks"]] == ["grounding metrics"]
    assert after["outline"] == outline


@pytest.mark.asyncio
async def test_desktop_plan_endpoint_refuses_a_session_that_is_not_at_the_gate(sidecar):
    """Same 409 contract as `/approve` — resuming a thread that is not suspended at
    `plan_gate_node` would push a plan-shaped payload into whatever interrupt is
    actually pending."""
    start = await sidecar.post(
        "/api/v1/research",
        headers=_auth(),
        json={"query": "What is retrieval-augmented generation?", "skip_plan_gate": True},
    )
    sid = start.json()["session_id"]
    await _until(sidecar, sid, "AWAITING_APPROVAL")

    resp = await sidecar.post(f"/api/v1/research/{sid}/plan", headers=_auth(), json={"tasks": []})
    assert resp.status_code == 409
    assert "AWAITING_PLAN" in resp.json()["detail"]


# ── 6. The switch does not move for anyone who did not ask ─────────────────────────


def test_start_request_defaults_to_skipping_the_gate():
    """An un-updated caller that omits the field gets exactly today's behaviour.

    The gate is the product default *for the app* — the run form sends
    `skip_plan_gate: false` explicitly — but a script POSTing the same JSON it posted
    last week must not start pausing at a gate it cannot see or resume. Pinned here
    rather than reasoned about, the same way `test_pipeline.py` pins the engine default.
    """
    from app.schemas.research import ResearchStartRequest

    req = ResearchStartRequest(query="a" * 20, depth="fast")
    assert req.skip_plan_gate is True
    assert req.topic_seeds == []
    assert req.outline_template is None


@pytest.mark.asyncio
async def test_desktop_run_without_the_field_never_reaches_the_plan_gate(sidecar):
    """The same claim as above, proven through the host rather than the schema: an
    unchanged request body produces an unchanged journey."""
    start = await sidecar.post(
        "/api/v1/research",
        headers=_auth(),
        json={"query": "What is retrieval-augmented generation?", "depth": "fast"},
    )
    sid = start.json()["session_id"]

    detail = await _until(sidecar, sid, "AWAITING_APPROVAL")
    assert detail["draft_report"]

    plan = await sidecar.get(f"/api/v1/research/{sid}/plan", headers=_auth())
    assert plan.status_code == 404, "a run that skipped the gate has no plan to review"


# ── 7. Seeds and outlines have to reach a prompt ───────────────────────────────────
#
# `topic_seeds` and `outline_template` were declared on `RunConfig` by the groundwork
# commit with no consumer anywhere. Accepting them on the start request while nothing
# reads them would be the "accepted by the schema, dropped on the floor" bug this
# codebase has paid for three times (AGENTS.md), so the consumer is asserted here.


def test_outline_templates_are_engine_data_not_ui_text():
    """The four templates ship as structured data the API serves, so the picker renders
    them without a second copy of the section list living in TypeScript."""
    from research_engine import outlines

    assert set(outlines.TEMPLATES) == {
        "literature_review",
        "systematic_comparison",
        "methods_survey",
        "custom",
    }
    lit = outlines.sections_for("literature_review")
    assert [s["title"] for s in lit] == ["Background", "Methods", "Findings", "Gaps"]
    assert outlines.sections_for("custom") == [], "Custom means the reviewer authors it"
    assert outlines.sections_for("no-such-template") == [], "an unknown id is not a crash"


def test_topic_seeds_are_given_to_the_planner_as_constraints():
    from research_engine import prompts

    human = prompts.planner_human(
        "state of RAG in 2026", "balanced", ("evaluation harnesses", "retrieval recall")
    )
    assert "evaluation harnesses" in human
    assert "retrieval recall" in human

    assert "must cover" not in prompts.planner_human("q", "fast", ())


def test_the_approved_outline_is_given_to_the_synthesizer_as_a_contract():
    from research_engine import prompts

    outline = [
        {"title": "Background", "description": "framing"},
        {"title": "Findings", "description": ""},
    ]
    human = prompts.synthesizer_human("q", "Evidence for citation:\n[1] ...", None, outline)
    assert "## Background" in human
    assert "## Findings" in human
    assert "framing" in human

    # No outline chosen → the prompt is byte-for-byte what it was before this existed,
    # so an ungated run's report structure does not move.
    plain = prompts.synthesizer_human("q", "Evidence for citation:\n[1] ...", None, [])
    assert plain == "Original query: q\n\nEvidence for citation:\n[1] ..."


@pytest.mark.asyncio
async def test_a_template_chosen_at_start_is_what_the_gate_proposes():
    """Picking a template at start time must put its sections in front of the reviewer
    at the gate, not silently lose them behind whatever the model proposed."""
    outcome = await run(
        checkpointer=MemorySaver(),
        session_id="plan-template",
        user_id="u",
        query=QUERY,
        run_config=RunConfig(
            llm_mode="fake", skip_plan_gate=False, outline_template="literature_review"
        ),
    )
    assert outcome.status == "awaiting_plan"
    assert [s["title"] for s in outcome.plan_outline] == [
        "Background",
        "Methods",
        "Findings",
        "Gaps",
    ]
