"""
One grounding record, the same everywhere it is shown (RFC V3.1 §9.6, AC-9).

The validator's own rules — uncited claims judged, failures repaired out, the "what your
files don't cover" section accepting only statements about the selection — are pinned in
`test_grounding_validator.py` and `test_grounding_repair.py`. This file pins the record they
leave: on both hosts' real routes and run drivers, the counts a selection run stores on its
row are the counts its bundle trace carries, and they add up. The run page renders the
row's counts (`frontend/components/runs/RunScopePanel.test.tsx`).
"""

from __future__ import annotations

import pytest

from tests.parity.drivers import desktop_driver, server_driver
from tests.security.test_corpus_project_isolation import (
    A_TEXT,
    _await_settled,
    _project,
    _upload,
)

HOSTS = {"server": server_driver, "desktop": desktop_driver}


@pytest.fixture(params=sorted(HOSTS))
async def host(request, tmp_path):
    async with HOSTS[request.param](tmp_path / request.param) as driver:
        yield driver


async def test_the_row_and_the_bundle_trace_carry_one_record(host):
    pid = await _project(host, "P")
    doc = await _upload(host, pid, "solar.txt", A_TEXT, "Thesis/solar.txt")
    created = await host.request(
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
    run = (await _await_settled(host, created.json()["run_id"]))["run"]
    assert run["status"] == "AWAITING_REVIEW", run["error_message"]

    report = run["grounding_report"]
    assert report["status"] == "complete"
    # Every claim the final text makes is in the list and in exactly one count.
    assert report["claims_total"] == len(report["claims"]) > 0
    assert report["claims_total"] == (
        report["claims_supported"] + report["claims_rejected"] + report["claims_unmeasured"]
    )
    assert report["claims_rejected"] == sum(report["rejected_by_cause"].values())
    assert report["claims_unmeasured"] == sum(report["unmeasured_by_cause"].values())

    bundle = (await host.request("GET", f"/runs/{run['id']}/bundle.json")).json()
    (entry,) = [e for e in bundle["trace"] if e.get("event") == "grounding_validation"]
    assert entry == {"event": "grounding_validation"} | {
        k: v for k, v in report.items() if k != "claims"
    }
