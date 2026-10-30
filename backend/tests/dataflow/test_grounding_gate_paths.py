"""
No path around the grounding gate (RFC V3.1 §9.6, AC-42).

An unmeasured claim must not reach `hitl_gate_node`'s interrupt however it arrives, and every
surface that shows a selection run's report must show the text that was validated. The
approval route deciding on the row is pinned in `test_grounding_repair.py`; this file holds
the other paths the AC names:

- **retry exhaustion** and the **disabled fallback**, through the real graph: a checker
  whose every call fails ends the run, and the non-selection pass that keeps every citation
  when its verifier is down is never reached;
- **resume from a checkpoint taken before validation was written**: a draft with no
  grounding record is refused at the route, not treated as "nothing to check";
- **a repeated identical claim**: judged each time it appears, so a verdict for one
  occurrence cannot vouch for the other;
- **every rendering surface** — the run page's revision, `.md`, `.pdf` and the bundle — on
  both hosts' real routes and run drivers, before and after approval.
"""

from __future__ import annotations

import asyncio
import hashlib
import re

import pytest
from langgraph.checkpoint.memory import MemorySaver

from research_engine import bundle, graph, grounding
from research_engine.corpus import CorpusStore, ScopedCorpus
from research_engine.runconfig import RunConfig, reset_run_config, set_run_config
from research_engine.runner import run
from tests.dataflow.test_corpus_store import SOLAR_TEXT, VENTS_TEXT, FakeEmbeddings
from tests.dataflow.test_grounding_repair import _ground
from tests.dataflow.test_grounding_validator import Judge, _sources
from tests.parity.drivers import Driver, desktop_driver, server_driver
from tests.security.test_corpus_project_isolation import (
    A_TEXT,
    _await_settled,
    _project,
    _upload,
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── The engine's route decides on the recorded report ─────────────────────────────


@pytest.fixture
def selection_run():
    token = set_run_config(RunConfig(llm_mode="real", corpus_allowed_ids=frozenset({"d"})))
    yield
    reset_run_config(token)


DRAFT = "Checked text [1].\n"


@pytest.mark.parametrize(
    "report",
    [
        None,  # resumed from a checkpoint taken before validation was written
        {"status": "unmeasured", "failure": "grounding_unmeasured: timeout"},
        {"status": "complete", "claims_unmeasured": 1, "validated_text_sha256": _sha(DRAFT)},
        {"status": "complete", "claims_unmeasured": 0, "validated_text_sha256": _sha("other")},
    ],
    ids=["no-record", "unmeasured", "unmeasured-claims-left", "edited-after-validation"],
)
def test_a_selection_draft_without_a_clean_record_never_reaches_the_gate(selection_run, report):
    state = {"draft_report": DRAFT, "grounding_report": report}
    assert graph.route_after_synthesizer(state) == "failer"


def test_a_validated_selection_draft_reaches_the_gate(selection_run):
    report = {"status": "complete", "claims_unmeasured": 0, "validated_text_sha256": _sha(DRAFT)}
    assert graph.route_after_synthesizer({"draft_report": DRAFT, "grounding_report": report}) == (
        "hitl_gate"
    )


# ── Retry exhaustion and the disabled fallback, through the real graph ────────────


async def test_a_checker_that_always_fails_ends_the_run_and_skips_the_fallback(
    tmp_path, monkeypatch
):
    judge = Judge(fail=TimeoutError("checker down"))
    monkeypatch.setattr(grounding, "get_llm", lambda role: judge)
    monkeypatch.setattr(grounding, "RETRY_BACKOFF_SECONDS", 0)

    async def fallback(*_a, **_kw):  # the keep-every-citation pass of non-selection runs
        raise AssertionError("a selection run reached the citation-keeping fallback")

    monkeypatch.setattr(graph, "_verify_citation_fidelity", fallback)

    store = CorpusStore(tmp_path / "c.sqlite", FakeEmbeddings())
    solar = await store.ingest("solar.txt", SOLAR_TEXT.encode())
    await store.ingest("vents.txt", VENTS_TEXT.encode())
    allowed = frozenset({solar.doc_id})

    outcome = await run(
        checkpointer=MemorySaver(),
        session_id="checker-down",
        user_id="u",
        query="How do photovoltaic cells convert sunlight?",
        run_config=RunConfig(llm_mode="fake", corpus_mode=True, corpus_allowed_ids=allowed),
        corpus=ScopedCorpus(store, allowed),
    )

    assert outcome.status != "awaiting_approval", "an unmeasured draft was offered for approval"
    assert "grounding_unmeasured" in (outcome.error or ""), outcome.error
    assert judge.calls.count("decompose") > 1, "the check was attempted and retried"


# ── A repeated claim is judged every time ─────────────────────────────────────────


class RecordingJudge(Judge):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.verified: list[str] = []

    def verify(self, human: str) -> str:
        self.verified.append(human)
        return super().verify(human)


async def test_a_repeated_identical_claim_is_judged_at_each_occurrence(monkeypatch):
    judge = RecordingJudge()
    monkeypatch.setattr(grounding, "get_llm", lambda role: judge)
    monkeypatch.setattr(grounding, "RETRY_BACKOFF_SECONDS", 0)
    token = set_run_config(RunConfig(llm_mode="real"))
    try:
        claim = "Enrolment rose 12% in 2021 [1]."
        result = await _ground(
            f"## Findings\n{claim}\n\n## Again\n{claim}\n",
            _sources("Enrolment rose 12% in 2021 across the district."),
        )
    finally:
        reset_run_config(token)

    sent = re.findall(r"^Claim \d+: (.*)$", "\n".join(judge.verified), re.M)
    assert sent == [claim, claim], "each occurrence went to the checker; no verdict was reused"
    assert result.report["status"] == "complete"


# ── Every surface renders the validated text, on both hosts ───────────────────────

HOSTS = {"server": server_driver, "desktop": desktop_driver}


@pytest.fixture(params=sorted(HOSTS))
async def host(request, tmp_path):
    async with HOSTS[request.param](tmp_path / request.param) as driver:
        yield request.param, driver


async def _surfaces(driver: Driver, run_id: str) -> dict[str, str]:
    body = (await driver.request("GET", f"/runs/{run_id}")).json()
    md = await driver.request("GET", f"/runs/{run_id}/export.md")
    assert md.status_code == 200, md.text
    bun = await driver.request("GET", f"/runs/{run_id}/bundle.json")
    assert bun.status_code == 200, bun.text
    return {
        "run page": body["revisions"][-1]["report_markdown"],
        "md": md.text,
        "bundle": bun.json()["report"],
    }


async def test_every_surface_renders_the_validated_text(host, monkeypatch):
    name, driver = host
    rendered: list[str] = []
    if name == "server":  # the desktop has no PDF renderer: its route is a handled 501
        from app.services import export

        def render_pdf(markdown, *_a, **_kw):
            rendered.append(markdown)
            return b"%PDF-1.7"

        monkeypatch.setattr(export, "render_pdf", render_pdf)

    pid = await _project(driver, "P")
    doc = await _upload(driver, pid, "solar.txt", A_TEXT, "Thesis/solar.txt")
    created = await driver.request(
        "POST",
        "/runs",
        json={
            "project_id": pid,
            "question": "What is retrieval-augmented generation?",
            "depth": "fast",
            "corpus_selection": {"doc_keys": [doc["doc_key"]]},
            "skip_plan_gate": True,
        },
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]
    run_row = (await _await_settled(driver, run_id))["run"]
    assert run_row["status"] == "AWAITING_REVIEW", run_row["error_message"]
    report = run_row["grounding_report"]
    assert report["status"] == "complete" and report["claims_unmeasured"] == 0

    before = await _surfaces(driver, run_id)
    text = before["run page"]
    assert _sha(text) == report["validated_text_sha256"]

    approved = await driver.request(
        "POST", f"/runs/{run_id}/report-review", json={"decision": "APPROVED"}
    )
    assert approved.status_code == 201, approved.text
    for _ in range(100):
        if (await driver.request("GET", f"/runs/{run_id}")).json()["run"]["status"] == "COMPLETED":
            break
        await asyncio.sleep(0.05)
    after = await _surfaces(driver, run_id)

    pdf = await driver.request("GET", f"/runs/{run_id}/export.pdf")
    if name == "server":
        assert pdf.status_code == 200, pdf.text
        assert rendered == [bundle.stamp_demo_md(text, demo=True)]
    else:
        assert pdf.status_code == 501

    for when, surfaces in (("before approval", before), ("after approval", after)):
        assert _sha(surfaces["run page"]) == report["validated_text_sha256"], when
        assert _sha(surfaces["bundle"]) == report["validated_text_sha256"], when
        # The prose export adds the demo banner and the model footer around the same bytes.
        assert surfaces["md"].startswith(bundle.stamp_demo_md(text, demo=True)), when
