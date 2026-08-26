"""
The product journeys, written once and driven against both hosts. **Not a test module.**

A journey is a plain async function over a `Driver` plus a recorder. Plain functions
rather than a step DSL on purpose: the golden they produce is reviewed by a human, and a
reviewer has to be able to read what was asked for without first learning a mini-language.

Every journey declares `checks` — product facts that must hold on both hosts. Those are
not decoration: two implementations that both return nothing agree perfectly, so shape
comparison alone can pass on a journey where nothing happened. See
`tests/parity/liveness.py`.

`requires` names what a host must be able to do for the journey to mean anything. A host
that cannot skips the journey *loudly* rather than recording an empty result that the
other host's empty result would match.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from tests.parity.drivers import Driver, pinned_routing
from tests.parity.liveness import body_at, status_at
from tests.parity.normalize import observe

TEXT_DOC = (
    b"Retrieval quality. Recall improved by twelve points on the internal benchmark, and "
    b"grounded answers beat ungrounded ones on factual questions."
)


@dataclass(frozen=True)
class Journey:
    name: str
    run: Callable[[Driver, Callable], Awaitable[None]]
    #: `(label, predicate)` pairs asserted against the observations on BOTH hosts.
    checks: tuple[tuple[str, Callable], ...]
    #: Driver attributes or capabilities this journey needs. `run_driver` means the host
    #: can start and finish a run in-process; a capability name means the host must claim it.
    requires: frozenset[str] = field(default_factory=frozenset)


async def drive(journey: Journey, driver: Driver) -> list[dict]:
    """Run one journey and return its normalized observations, in order."""
    observations: list[dict] = []

    def record(step: str, response) -> None:
        observations.append({"step": step, **observe(response)})

    await journey.run(driver, record)
    return observations


def unmet_requirements(journey: Journey, driver: Driver) -> list[str]:
    unmet = []
    for need in sorted(journey.requires):
        if need == "run_driver" and not driver.run_driver:
            unmet.append("this host cannot drive a run in-process")
        elif need == "postgres" and driver.backing != "postgres":
            unmet.append("needs a pgvector-backed database")
        elif need not in ("run_driver", "postgres") and need not in driver.capabilities:
            unmet.append(f"this host does not claim the {need!r} capability")
    return unmet


# ── Helpers ───────────────────────────────────────────────────────────────────────


async def _new_project(driver: Driver, record, name: str) -> str:
    resp = await driver.request("POST", "/projects", json={"name": name})
    record("create a project", resp)
    return resp.json()["id"]


async def _await_run_status(
    driver: Driver, run_id: str, wanted: set[str], *, timeout: float = 60.0
):
    """Poll one run until it reaches one of `wanted`, or the deadline passes.

    Both hosts dispatch fire-and-forget, so a journey that read the status immediately
    would record whichever of PENDING/RUNNING it happened to catch — a race, not a
    contract. The last response is returned either way: a timeout records the status the
    host was actually stuck on, which is the observation worth having.
    """
    path = f"/runs/{run_id}"
    deadline = asyncio.get_event_loop().time() + timeout
    resp = await driver.request("GET", path)
    while asyncio.get_event_loop().time() < deadline:
        if resp.status_code != 200 or resp.json()["run"]["status"] in wanted:
            return resp
        await asyncio.sleep(0.1)
        resp = await driver.request("GET", path)
    return resp


# ── Projects ──────────────────────────────────────────────────────────────────────


async def _projects(driver: Driver, record) -> None:
    project_id = await _new_project(driver, record, "Parity")

    record("list projects", await driver.request("GET", "/projects"))
    record(
        "rename the project",
        await driver.request("PATCH", f"/projects/{project_id}", json={"name": "Parity renamed"}),
    )
    record(
        "archive the project",
        await driver.request("PATCH", f"/projects/{project_id}", json={"archived": True}),
    )
    record(
        "restore the project",
        await driver.request("PATCH", f"/projects/{project_id}", json={"archived": False}),
    )
    record(
        "a duplicate name is refused",
        await driver.request("POST", "/projects", json={"name": "Parity renamed"}),
    )
    record(
        "an unknown project is not found",
        await driver.request("PATCH", "/projects/00000000-0000-0000-0000-0000000000ff", json={}),
    )
    record("delete the project", await driver.request("DELETE", f"/projects/{project_id}"))
    record(
        "the deleted project is gone",
        await driver.request("GET", f"/projects/{project_id}/corpus/status"),
    )


PROJECTS = Journey(
    name="projects",
    run=_projects,
    checks=(
        (
            "the created project carries the name that was asked for",
            lambda o: body_at(o, "create a project")["name"] == "Parity",
        ),
        (
            "the project list is not empty",
            lambda o: len(body_at(o, "list projects")["projects"]) >= 1,
        ),
        (
            "renaming actually changed the name",
            lambda o: body_at(o, "rename the project")["name"] == "Parity renamed",
        ),
        # `archived_at` is the field, not a boolean: a project records *when* it was
        # archived, and restore clears the instant rather than flipping a flag.
        (
            "archive and restore round-trip",
            lambda o: (
                body_at(o, "archive the project")["archived_at"] is not None
                and body_at(o, "restore the project")["archived_at"] is None
            ),
        ),
        (
            "a duplicate name is a conflict, not a second project",
            lambda o: status_at(o, "a duplicate name is refused") == 409,
        ),
        (
            "an unknown project is 404, never 403 — existence is not disclosed",
            lambda o: status_at(o, "an unknown project is not found") == 404,
        ),
        ("deletion returns no content", lambda o: status_at(o, "delete the project") == 204),
    ),
)


# ── Corpus ────────────────────────────────────────────────────────────────────────


async def _corpus(driver: Driver, record) -> None:
    project_id = await _new_project(driver, record, "Corpus parity")
    upload = f"/projects/{project_id}/corpus/documents"

    resp = await driver.request(
        "POST", upload, files={"file": ("retrieval.txt", TEXT_DOC, "text/plain")}
    )
    record("upload a document", resp)
    doc_id = resp.json().get("id") if resp.status_code < 300 else None

    record("list documents", await driver.request("GET", upload))
    record("corpus status", await driver.request("GET", f"/projects/{project_id}/corpus/status"))
    if doc_id:
        record(
            "download the original bytes",
            await driver.request("GET", f"{upload}/{doc_id}/download"),
        )

    record(
        "upload an empty document",
        await driver.request("POST", upload, files={"file": ("empty.txt", b"", "text/plain")}),
    )
    record(
        "upload an unsupported format",
        await driver.request(
            "POST", upload, files={"file": ("thing.exe", b"MZ\x00binary", "application/exe")}
        ),
    )
    record(
        "an unknown document is not found",
        await driver.request("DELETE", f"{upload}/does-not-exist"),
    )
    record(
        "another user's project is not found",
        await driver.request(
            "GET", "/projects/00000000-0000-0000-0000-0000000000ff/corpus/documents"
        ),
    )
    if doc_id:
        record("delete the document", await driver.request("DELETE", f"{upload}/{doc_id}"))
        record("the corpus is empty again", await driver.request("GET", upload))


CORPUS = Journey(
    name="corpus",
    run=_corpus,
    checks=(
        ("the upload succeeded", lambda o: 200 <= status_at(o, "upload a document") < 300),
        (
            "the upload wrote chunks — an ingest that stored nothing is not an ingest",
            lambda o: body_at(o, "upload a document")["chunks"] >= 1,
        ),
        ("the document list is not empty", lambda o: len(body_at(o, "list documents")) == 1),
        (
            "status counts the document and its chunks",
            lambda o: (
                body_at(o, "corpus status")["documents"] == 1
                and body_at(o, "corpus status")["chunks"] >= 1
            ),
        ),
        (
            "the download returned the original bytes, not an empty body",
            lambda o: body_at(o, "download the original bytes")["empty"] is False,
        ),
        ("an empty upload is refused", lambda o: status_at(o, "upload an empty document") >= 400),
        (
            "an unsupported format is refused",
            lambda o: status_at(o, "upload an unsupported format") >= 400,
        ),
        (
            "an unknown document is 404",
            lambda o: status_at(o, "an unknown document is not found") == 404,
        ),
        (
            "a project that is not yours is 404, not 403",
            lambda o: status_at(o, "another user's project is not found") == 404,
        ),
        ("deleting really removed it", lambda o: body_at(o, "the corpus is empty again") == []),
    ),
)


# ── Identity and models ───────────────────────────────────────────────────────────


async def _identity(driver: Driver, record) -> None:
    record("who am I", await driver.request("GET", "/auth/me"))
    record("my usage", await driver.request("GET", "/auth/me/usage"))
    record("the model catalog", await driver.request("GET", "/models"))
    record("routing before any choice", await driver.request("GET", "/models/routing"))
    record(
        "pin every role",
        await driver.request("PUT", "/models/routing", json={"routing": pinned_routing()}),
    )
    record("routing after pinning", await driver.request("GET", "/models/routing"))
    record("clear the routing", await driver.request("DELETE", "/models/routing"))
    record(
        "an unroutable model is refused",
        await driver.request("PUT", "/models/routing", json={"routing": {"planner": "nope"}}),
    )


IDENTITY = Journey(
    name="identity-and-models",
    run=_identity,
    checks=(
        ("the caller has an identity", lambda o: bool(body_at(o, "who am I")["email"])),
        (
            "usage reports its real windows rather than an empty object",
            lambda o: "cost_usd" in body_at(o, "my usage")["month"],
        ),
        (
            "the catalog is not empty — an empty catalog offers the user nothing",
            lambda o: len(body_at(o, "the model catalog")["models"]) >= 1,
        ),
        ("pinning every role is accepted", lambda o: 200 <= status_at(o, "pin every role") < 300),
        (
            "the pinned routing is what comes back",
            lambda o: body_at(o, "routing after pinning")["routing"] == pinned_routing(),
        ),
        (
            "an unroutable model is rejected, not silently stored",
            lambda o: status_at(o, "an unroutable model is refused") >= 400,
        ),
    ),
)


# ── A research run, end to end ────────────────────────────────────────────────────


async def _run_journey(driver: Driver, record) -> None:
    project_id = await _new_project(driver, record, "Run parity")

    resp = await driver.request(
        "POST",
        "/runs",
        json={
            "project_id": project_id,
            "question": "What is retrieval-augmented generation?",
            "depth": "fast",
            "skip_plan_gate": False,
        },
    )
    record("start a run", resp)
    run_id = resp.json()["run_id"]

    at_plan = await _await_run_status(driver, run_id, {"AWAITING_PLAN", "FAILED"})
    record("the run pauses at the design gate", at_plan)

    # Read after the run has settled, not before. Both hosts dispatch fire-and-forget and
    # stamp `demo` inside the driver, so a listing taken immediately after POST records
    # whichever of PENDING/RUNNING and demo-or-not the poller happened to catch — a race
    # the harness would then report as a divergence.
    record("the run appears in history", await driver.request("GET", "/runs"))

    record(
        "approve the plan",
        await driver.request("POST", f"/runs/{run_id}/plan-review", json={"decision": "APPROVED"}),
    )

    at_report = await _await_run_status(driver, run_id, {"AWAITING_REVIEW", "FAILED"})
    record("the run pauses at the report gate", at_report)

    record(
        "request rework",
        await driver.request(
            "POST",
            f"/runs/{run_id}/report-review",
            json={"decision": "REWORK_REQUESTED", "feedback": "Add a second source."},
        ),
    )
    reworked = await _await_run_status(driver, run_id, {"AWAITING_REVIEW", "FAILED"})
    record("a reworked draft comes back to the gate", reworked)

    record(
        "approve the report",
        await driver.request(
            "POST", f"/runs/{run_id}/report-review", json={"decision": "APPROVED"}
        ),
    )
    record("the finished run", await driver.request("GET", f"/runs/{run_id}"))
    record("export the report", await driver.request("GET", f"/runs/{run_id}/export.md"))
    record("the verifiable bundle", await driver.request("GET", f"/runs/{run_id}/bundle.json"))
    record("the standalone verifier", await driver.request("GET", f"/runs/{run_id}/verification"))
    record("archive the run", await driver.request("POST", f"/runs/{run_id}/archive"))
    record("restore the run", await driver.request("POST", f"/runs/{run_id}/unarchive"))
    record("delete the run", await driver.request("DELETE", f"/runs/{run_id}"))
    record("the deleted run is gone", await driver.request("GET", f"/runs/{run_id}"))


RUN = Journey(
    name="research-run",
    run=_run_journey,
    requires=frozenset({"run_driver"}),
    checks=(
        ("the run was created", lambda o: status_at(o, "start a run") == 201),
        ("history lists it", lambda o: len(body_at(o, "the run appears in history")["runs"]) == 1),
        (
            "the design gate was actually reached",
            lambda o: (
                body_at(o, "the run pauses at the design gate")["run"]["status"] == "AWAITING_PLAN"
            ),
        ),
        (
            "the plan proposed at least one task — a plan of nothing is not a plan",
            lambda o: (
                len(body_at(o, "the run pauses at the design gate")["plans"][0]["tasks"]) >= 1
            ),
        ),
        (
            "the report gate was reached",
            lambda o: (
                body_at(o, "the run pauses at the report gate")["run"]["status"]
                == "AWAITING_REVIEW"
            ),
        ),
        (
            "rework produced a second revision rather than ending the run",
            lambda o: len(body_at(o, "a reworked draft comes back to the gate")["revisions"]) >= 2,
        ),
        (
            "the run completed",
            lambda o: body_at(o, "the finished run")["run"]["status"] == "COMPLETED",
        ),
        (
            "evidence was gathered — a report with no evidence behind it is the P0 case",
            lambda o: len(body_at(o, "the finished run")["evidence"]) >= 1,
        ),
        (
            "the report carries at least one citation marker",
            lambda o: bool(
                body_at(o, "the finished run")["revisions"][-1]["report_markdown"]["markers"]
            ),
        ),
        (
            "an artifact was created at approval",
            lambda o: body_at(o, "the finished run")["artifact"] is not None,
        ),
        (
            "the export is not an empty file",
            lambda o: body_at(o, "export the report")["empty"] is False,
        ),
        ("the bundle assembled", lambda o: status_at(o, "the verifiable bundle") == 200),
        (
            "the verifier reached a verdict rather than declining to measure",
            lambda o: body_at(o, "the standalone verifier").get("passed") is not None,
        ),
        ("deletion is final", lambda o: status_at(o, "the deleted run is gone") == 404),
    ),
)


ALL: tuple[Journey, ...] = (PROJECTS, CORPUS, IDENTITY, RUN)
