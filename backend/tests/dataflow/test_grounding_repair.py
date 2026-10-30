"""
Keeping unsupported claims out of a selected-files report (RFC V3.1 §9.4–§9.6, §9.9).

The repair loop, the gate and the approval route, driven with real validator code and a
deterministic competent judge (`test_grounding_validator.Judge`), plus one end-to-end run
through the real graph in scripted mode.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

import pytest
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import insert

from app import run_lifecycle
from app.api.v1.runs import grounding_refusal
from app.models.project import Project
from app.models.user import User
from research_engine import grounding, grounding_repair, prompts
from research_engine.corpus import CorpusStore, ScopedCorpus
from research_engine.runconfig import RunConfig, reset_run_config, set_run_config
from research_engine.runner import run
from tests.dataflow.test_corpus_store import SOLAR_TEXT, VENTS_TEXT, FakeEmbeddings
from tests.dataflow.test_grounding_validator import Judge, _sources, _words
from tests.sqlite_support import open_db


class RepairingJudge(Judge):
    """The competent judge, plus a rewriter. `invent` makes every rewrite add a claim."""

    def __init__(self, *, invent: str | None = None, **kw):
        super().__init__(**kw)
        self.invent = invent

    async def ainvoke(self, messages):
        if prompts.SELECTION_REPAIR_PROMPT in messages[0].content:
            self.calls.append("repair")
            verified = [
                line[2:]
                for line in messages[1]
                .content.split("Verified claims in this passage:\n", 1)[1]
                .split("\n\nRejected", 1)[0]
                .splitlines()
                if line.startswith("- ")
            ]
            text = " ".join(v.rstrip(".") + "." for v in verified) or "REMOVE"
            if self.invent:
                text += " " + self.invent
            return self._msg(text)
        return await super().ainvoke(messages)


@pytest.fixture
def judge(monkeypatch):
    holder = {"judge": RepairingJudge()}
    monkeypatch.setattr(grounding, "get_llm", lambda role: holder["judge"])
    monkeypatch.setattr(grounding, "RETRY_BACKOFF_SECONDS", 0)
    token = set_run_config(RunConfig(llm_mode="real"))
    yield holder
    reset_run_config(token)


async def _ground(draft, sources, budget=None):
    return await grounding_repair.ground(
        draft,
        sources,
        question="How did enrolment change?",
        admissible=lambda url: True,
        budget=budget or grounding.Budget(spent_usd=0.0, tokens_in=0, started_at=None),
    )


async def test_a_unit_with_an_invented_clause_is_rewritten_to_what_is_supported(judge):
    result = await _ground(
        "## Findings\nEnrolment rose 12% in 2021 [1] and fell 5% in 2022.\n",
        _sources("Enrolment rose 12% in 2021 across the district."),
    )
    assert result.report["status"] == "complete", result.report
    assert "fell 5%" not in result.text
    assert "Enrolment rose 12% in 2021" in result.text
    assert result.report["units_repaired"] == 1
    assert (
        result.report["validated_text_sha256"]
        == hashlib.sha256(result.text.encode("utf-8")).hexdigest()
    )


async def test_a_rewrite_that_invents_a_claim_is_caught_and_the_unit_dropped(judge):
    judge["judge"] = RepairingJudge(invent="Spending tripled after 2019.")
    result = await _ground(
        "## Findings\nEnrolment rose 12% in 2021 [1] and fell 5% in 2022.\n\n"
        "## More\nSilicon cells absorb photons [2].\n",
        _sources("Enrolment rose 12% in 2021.", "Silicon cells absorb photons."),
    )
    assert "Spending tripled" not in result.text
    assert grounding.REMOVED_NOTICE in result.text, "dropped whole, with the notice in place"
    assert result.report["units_dropped"] >= 1
    assert result.report["status"] == "complete"
    # No dangling marker: [1] went with its unit, so the Sources list no longer has it.
    assert "[1]" not in result.text and "[2] corpus://doc-2" in result.text


async def test_a_conclusion_adding_a_cause_is_rewritten_from_supported_findings(judge):
    result = await _ground(
        "## Findings\nEnrolment rose 12% in 2021 [1].\n\n"
        "## Conclusion\nEnrolment rose 12% in 2021 because tuition fell [1].\n",
        _sources("Enrolment rose 12% in 2021."),
    )
    assert "because tuition fell" not in result.text
    assert result.report["status"] == "complete"


async def test_nothing_supported_is_no_evidence_not_an_answer(judge):
    result = await _ground(
        "## Findings\nThe market grew strongly.\n", _sources("Unrelated text about tides.")
    )
    assert result.report["status"] == "no_evidence"
    assert result.failure == "selection_no_evidence"


async def test_an_unmeasured_claim_fails_the_report_and_is_never_complete(judge):
    class _Down(Exception):
        status_code = 503

    judge["judge"] = RepairingJudge(fail=_Down("outage"))
    result = await _ground("Enrolment rose 12% in 2021 [1].\n", _sources("Enrolment rose 12%."))
    assert result.report["status"] == "unmeasured"
    assert result.failure.startswith("grounding_unmeasured") and "provider_outage" in result.failure
    assert result.report["validated_text_sha256"] is None


async def test_a_validation_that_cannot_fit_the_budget_is_refused_before_spending(
    judge, monkeypatch
):
    monkeypatch.setattr(grounding, "_estimate", lambda sentences: 0.5)
    token = set_run_config(RunConfig(llm_mode="real", max_cost_per_session_usd=1.0))
    try:
        budget = grounding.Budget(spent_usd=0.8, tokens_in=0, started_at=None)
        result = await _ground(
            "Enrolment rose 12% in 2021 [1].\n", _sources("Enrolment rose 12%."), budget=budget
        )
    finally:
        reset_run_config(token)
    assert result.failure.startswith("budget_insufficient")
    assert "$0.5000" in result.failure and "$1.00" in result.failure
    assert judge["judge"].calls == [], "nothing was spent on a check that could not finish"


async def test_validation_cost_is_recorded_apart_from_research_cost(judge):
    result = await _ground(
        "Enrolment rose 12% in 2021 [1].\n", _sources("Enrolment rose 12% in 2021.")
    )
    cost = result.report["validation_cost"]
    assert cost["calls"] >= 2 and cost["tokens_in"] > 0
    assert set(cost) >= {"estimated_usd", "actual_usd", "calls", "retries", "repairs", "seconds"}
    assert cost["seconds"] >= 0, "the check's own wall time, for gate G-5"


# ── The approval route decides on the row (AC-42) ─────────────────────────────────


async def test_the_approval_route_refuses_text_the_validation_did_not_cover(tmp_path):
    async with open_db(tmp_path / "gate.sqlite") as maker, maker() as db:
        now = datetime(2026, 10, 26, tzinfo=UTC)
        uid, pid = uuid.uuid4(), uuid.uuid4()
        await db.execute(
            insert(User).values(
                id=uid, email=f"{uid}@x.invalid", hashed_pw="x", is_active=True, created_at=now
            )
        )
        await db.execute(
            insert(Project).values(id=pid, user_id=uid, name="P", created_at=now, updated_at=now)
        )
        await db.commit()
        row = await run_lifecycle.create_run(
            db,
            owner_id=uid,
            project_id=pid,
            question="q",
            corpus_mode=True,
            corpus_selection={"resolved": [{"document_id": "d"}]},
        )
        text = "Checked text [1].\n"
        assert grounding_refusal(row, text), "no grounding record: refused"
        row.grounding_report = {
            "status": "complete",
            "claims_unmeasured": 0,
            "validated_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        }
        assert grounding_refusal(row, text) is None
        assert grounding_refusal(row, text + "An edit after validation.\n"), "other text: refused"
        row.grounding_report = {**row.grounding_report, "status": "unmeasured"}
        assert grounding_refusal(row, text)


# ── End to end through the real graph (AC-9, AC-14) ───────────────────────────────


async def test_a_scripted_selection_run_reaches_the_gate_with_a_complete_record(tmp_path):
    store = CorpusStore(tmp_path / "c.sqlite", FakeEmbeddings())
    solar = await store.ingest("solar.txt", SOLAR_TEXT.encode())
    await store.ingest("vents.txt", VENTS_TEXT.encode())
    allowed = frozenset({solar.doc_id})

    outcome = await run(
        checkpointer=(saver := MemorySaver()),
        session_id="selection-e2e",
        user_id="u",
        query="How do photovoltaic cells convert sunlight?",
        run_config=RunConfig(llm_mode="fake", corpus_mode=True, corpus_allowed_ids=allowed),
        corpus=ScopedCorpus(store, allowed),
    )

    assert outcome.status == "awaiting_approval", outcome.error
    state = (await saver.aget({"configurable": {"thread_id": "selection-e2e"}}))["channel_values"]
    report = state["grounding_report"]
    assert report["status"] == "complete"
    assert (
        report["validated_text_sha256"]
        == hashlib.sha256(outcome.draft_report.encode("utf-8")).hexdigest()
    )
    assert all(s["url"].startswith(f"corpus://{solar.doc_id}") for s in outcome.sources)
    assert _words("photovoltaic")  # the helper is shared; keep the import honest
