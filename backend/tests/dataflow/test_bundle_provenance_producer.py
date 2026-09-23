"""
The v2 producer copies persisted provenance; it never composes a prompt (PR-7b).

Driven through the real assembler against real rows, not a hand-built manifest. AGENTS.md
records why: `corpus_mode` lost the row → `RunConfig` hop on both hosts while a test that
built the config itself stayed green, because it had stubbed the exact hop that was broken.
The hop here is row → bundle, so the row is where these tests start.

The decisive test is `test_export_does_not_compose_a_single_prompt`: it detonates on any call
to `system_prompt` during assembly. Without it, a producer that recomputed instead of reading
would pass every other assertion in this file on the day it was written, and start lying the
first time a shipped constant changed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import insert

from app import run_bundle, run_lifecycle
from app.models.project import Project
from app.models.user import User
from research_engine.bundle import BundleManifest, compute_bundle_hash, content_hash
from research_engine.prompt_composition import PURPOSE_CONSTANTS, RUN_PURPOSES
from research_engine.verify_bundle import verify
from tests.sqlite_support import open_db

REPORT = "# R\n\n## Executive Summary\n\nA claim [1].\n\n## Sources\n\n[1] https://example.org/a\n"
EVIDENCE = [
    {
        "task_id": 1,
        "source_url": "https://example.org/a",
        "source_title": "A",
        "snippet": "Some supporting evidence text for the claim.",
        "key_fact": "fact",
    }
]
SOURCES = [{"index": 1, "url": "https://example.org/a", "title": "A", "snippet": ""}]


def _captured(purposes, overridden=()):
    """Provenance shaped exactly as the recorder writes it."""
    out = {}
    for purpose in purposes:
        text = f"OVERRIDE for {purpose}" if purpose in overridden else PURPOSE_CONSTANTS[purpose]
        out[purpose] = {
            "purpose": purpose,
            "role": purpose.split(".")[0],
            "policy": "PROTECTED"
            if purpose in {"critic.citation_verify", "synthesizer.repair"}
            else "OVERRIDABLE",
            "overridden": purpose in overridden,
            "effective_prompt": text,
        }
    return out


async def _run_with(db, provenance, status):
    now = datetime(2026, 9, 23, tzinfo=UTC)
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
    run = await run_lifecycle.create_run(
        db, owner_id=uid, project_id=pid, question="q", depth="fast"
    )
    run.effective_prompt_provenance = provenance
    run.prompt_overrides_status = status
    run.evidence_outcome = "READ"
    await db.commit()

    written = await run_lifecycle.record_evidence(
        db, run, evidence=EVIDENCE, numbered_sources=SOURCES
    )
    revision = await run_lifecycle.record_revision(
        db, run, report_markdown=REPORT, evidence_index=written
    )
    await run_lifecycle.set_status(db, run, "AWAITING_REVIEW")
    await db.commit()

    await run_lifecycle.record_report_review(
        db, run, revision.revision, reviewer_id=uid, decision="APPROVED"
    )
    await run_lifecycle.set_status(db, run, "COMPLETED")
    await db.commit()
    return run, revision


@pytest.fixture
async def assembled(tmp_path, request):
    provenance, status = getattr(request, "param", (_captured(sorted(RUN_PURPOSES)), "NONE"))
    async with open_db(tmp_path / "prov.sqlite") as maker, maker() as db:
        run, _ = await _run_with(db, provenance, status)
        manifest, reason = await run_bundle.assemble_with_reason(db, run.id)
        yield manifest, reason, run


# ── Version and content ───────────────────────────────────────────────────────────


async def test_a_run_with_captured_provenance_emits_v2(assembled):
    manifest, reason, _ = assembled
    assert reason is None and manifest is not None
    assert manifest.bundle_version == 2


@pytest.mark.parametrize("assembled", [(None, None)], indirect=True)
async def test_a_run_predating_capture_stays_v1(assembled):
    """Its prompts were never recorded, and nothing can honestly recreate them."""
    manifest, _, _ = assembled
    assert manifest.bundle_version == 1
    assert manifest.prompt_provenance == []
    assert manifest.prompt_overrides_status is None


async def test_every_captured_purpose_appears_exactly_once(assembled):
    manifest, _, _ = assembled
    purposes = [r.purpose for r in manifest.prompt_provenance]
    assert sorted(purposes) == sorted(RUN_PURPOSES)
    assert len(purposes) == len(set(purposes))


@pytest.mark.parametrize(
    "assembled",
    [(_captured(["planner.main", "executor.main", "critic.research", "synthesizer.main"]), "NONE")],
    indirect=True,
)
async def test_only_executed_purposes_appear(assembled):
    """A clean run composes four of the seven. The bundle reports four."""
    manifest, _, _ = assembled
    assert manifest.bundle_version == 2
    assert {r.purpose for r in manifest.prompt_provenance} == {
        "planner.main",
        "executor.main",
        "critic.research",
        "synthesizer.main",
    }


async def test_no_chat_purpose_reaches_a_research_bundle(assembled):
    manifest, _, _ = assembled
    assert not [r for r in manifest.prompt_provenance if r.purpose.startswith("chat.")]


async def test_the_digest_matches_the_persisted_text(assembled):
    manifest, _, _ = assembled
    for record in manifest.prompt_provenance:
        assert record.effective_prompt_sha256 == content_hash(record.effective_prompt)


# ── The decisive one ──────────────────────────────────────────────────────────────


async def test_export_does_not_compose_a_single_prompt(tmp_path, monkeypatch):
    """Assembly must read the row. Composing would report today's constants as history.

    Behavioural half: `system_prompt` detonates for the duration of the assembly.
    """
    import research_engine.prompt_composition as pc

    def _detonate(purpose):
        raise AssertionError(f"assembly composed {purpose} instead of reading the row")

    async with open_db(tmp_path / "nocompose.sqlite") as maker, maker() as db:
        run, _ = await _run_with(db, _captured(sorted(RUN_PURPOSES)), "APPLIED")
        monkeypatch.setattr(pc, "system_prompt", _detonate)
        manifest, reason = await run_bundle.assemble_with_reason(db, run.id)

    assert reason is None
    assert manifest.bundle_version == 2
    assert len(manifest.prompt_provenance) == len(RUN_PURPOSES)


def test_no_assembly_module_even_references_the_composer():
    """Structural half, and the one the patch above cannot make.

    A module-level `from prompt_composition import system_prompt` binds the function at
    import time, so patching the composer's own module would not reach it. Neither assembly
    module may name it at all.
    """
    import ast
    from pathlib import Path

    backend = Path(__file__).resolve().parents[2]
    for rel in ("app/run_bundle.py", "research_engine/bundle.py"):
        tree = ast.parse((backend / rel).read_text("utf-8"))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        imported = {
            a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names
        }
        assert "system_prompt" not in names | imported, f"{rel} reaches the composer"


async def test_the_bundle_reflects_the_row_even_when_it_disagrees_with_the_constants(tmp_path):
    """Edit the persisted text and the bundle follows it — proof the row is the source.

    A recomputing producer would silently "correct" this back to the shipped constant, which
    is exactly how an upgraded deployment would rewrite what an old artifact claims.
    """
    tampered = _captured(["planner.main"])
    tampered["planner.main"]["effective_prompt"] = "WHAT THE RUN ACTUALLY SAW"

    async with open_db(tmp_path / "row.sqlite") as maker, maker() as db:
        run, _ = await _run_with(db, tampered, "NONE")
        manifest, _ = await run_bundle.assemble_with_reason(db, run.id)

    record = manifest.prompt_provenance[0]
    assert record.effective_prompt == "WHAT THE RUN ACTUALLY SAW"
    assert record.effective_prompt != PURPOSE_CONSTANTS["planner.main"]
    assert record.effective_prompt_sha256 == content_hash("WHAT THE RUN ACTUALLY SAW")


# ── Status ────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("assembled", "expected"),
    [
        ((_captured(sorted(RUN_PURPOSES)), "NONE"), "NONE"),
        ((_captured(sorted(RUN_PURPOSES), overridden=["planner.main"]), "APPLIED"), "APPLIED"),
        ((_captured(sorted(RUN_PURPOSES)), "UNUSABLE"), "UNUSABLE"),
    ],
    indirect=["assembled"],
)
async def test_status_is_copied_from_the_row(assembled, expected):
    manifest, _, _ = assembled
    assert manifest.prompt_overrides_status == expected
    assert manifest.bundle_version == 2, "v2 is not a claim about customisation"


@pytest.mark.parametrize("assembled", [(_captured(["planner.main"]), None)], indirect=True)
async def test_a_null_status_with_provenance_reads_as_none(assembled):
    """Pre-0026 rows hold NULL; the existing mapping to NONE is preserved."""
    manifest, _, _ = assembled
    assert manifest.prompt_overrides_status == "NONE"


# ── Integrity through the merged PR-7a verifier ───────────────────────────────────


async def test_the_v2_bundle_verifies(assembled):
    manifest, _, _ = assembled
    result = verify(manifest)
    assert result.passed, [(c.name, c.detail) for c in result.checks if not c.passed]
    assert len(result.prompt_provenance) == len(RUN_PURPOSES)


async def test_mutating_the_prompt_breaks_integrity(assembled):
    manifest, _, _ = assembled
    data = manifest.model_dump()
    data["prompt_provenance"][0]["effective_prompt"] += " edited"
    result = verify(BundleManifest.model_validate(data))
    assert [c.name for c in result.checks if not c.passed] == ["bundle_integrity"]


async def test_mutating_the_digest_breaks_integrity(assembled):
    manifest, _, _ = assembled
    data = manifest.model_dump()
    data["prompt_provenance"][0]["effective_prompt_sha256"] = "0" * 64
    result = verify(BundleManifest.model_validate(data))
    assert [c.name for c in result.checks if not c.passed] == ["bundle_integrity"]


async def test_an_inconsistent_pair_fails_even_with_the_hash_rebuilt(assembled):
    manifest, _, _ = assembled
    data = manifest.model_dump()
    data["prompt_provenance"][0]["effective_prompt"] = "swapped"
    rebuilt = BundleManifest.model_validate(data)
    rebuilt.bundle_hash = compute_bundle_hash(rebuilt)
    result = verify(rebuilt)
    assert [c.name for c in result.checks if not c.passed] == ["bundle_integrity"]


async def test_assembly_is_deterministic(assembled, tmp_path):
    """Two assemblies of one run must hash identically — the records are ordered."""
    manifest, _, run = assembled
    async with open_db(tmp_path / "again.sqlite") as maker, maker() as db:
        again, _ = await _run_with(db, _captured(sorted(RUN_PURPOSES)), "NONE")
        second, _ = await run_bundle.assemble_with_reason(db, again.id)
    assert [r.purpose for r in manifest.prompt_provenance] == [
        r.purpose for r in second.prompt_provenance
    ]


# ── The merge across invocations ──────────────────────────────────────────────────


async def test_provenance_survives_an_invocation_that_ends_at_the_plan_gate(tmp_path):
    """A gated run composes its planner prompt in one invocation and the rest in the next.

    `persist_outcome` returns early for `awaiting_plan` — before evidence, before metrics —
    so a provenance write placed with the other row writes is skipped entirely, and the
    planner's prompt, always the first one composed, reaches no bundle. It is written above
    every early return for that reason.

    This escaped every unit test because they all drive one uninterrupted invocation; the
    golden run journey caught it. The regression lives here so it fails in isolation too.
    """
    from app import run_execution
    from research_engine.runner import RunOutcome

    async with open_db(tmp_path / "gate.sqlite") as maker, maker() as db:
        run, _ = await _run_with(db, None, None)

        # Invocation 1 stops at the design gate carrying only the planner's prompt.
        await run_execution.persist_outcome(
            db,
            run,
            RunOutcome(status="awaiting_plan", plan_tasks=[], plan_outline=[]),
            prompt_provenance=_captured(["planner.main"]),
        )
        await db.commit()
        assert set(run.effective_prompt_provenance) == {"planner.main"}

        # Invocation 2 resumes and composes the rest.
        await run_execution.persist_outcome(
            db,
            run,
            RunOutcome(status="awaiting_review", draft_report="d"),
            state={},
            prompt_provenance=_captured(["executor.main", "synthesizer.main"]),
        )
        await db.commit()

    assert set(run.effective_prompt_provenance) == {
        "planner.main",
        "executor.main",
        "synthesizer.main",
    }


async def test_a_later_invocation_does_not_overwrite_what_an_earlier_one_ran_under(tmp_path):
    """Earlier-first: the string a purpose actually ran under is the one that stays."""
    from app import run_execution
    from research_engine.runner import RunOutcome

    first = _captured(["planner.main"])
    first["planner.main"]["effective_prompt"] = "WHAT THE FIRST SEGMENT SAW"
    second = _captured(["planner.main"])
    second["planner.main"]["effective_prompt"] = "a later recomposition"

    async with open_db(tmp_path / "merge.sqlite") as maker, maker() as db:
        run, _ = await _run_with(db, None, None)
        await run_execution.persist_outcome(
            db, run, RunOutcome(status="awaiting_plan"), prompt_provenance=first
        )
        await run_execution.persist_outcome(
            db, run, RunOutcome(status="awaiting_plan"), prompt_provenance=second
        )
        await db.commit()

    assert (
        run.effective_prompt_provenance["planner.main"]["effective_prompt"]
        == "WHAT THE FIRST SEGMENT SAW"
    )


async def test_a_single_uninterrupted_invocation_records_everything_it_composed(tmp_path):
    """The ungated path, which the gate tests above would not cover on their own."""
    from app import run_execution
    from research_engine.runner import RunOutcome

    everything = _captured(sorted(RUN_PURPOSES))
    async with open_db(tmp_path / "single.sqlite") as maker, maker() as db:
        run, _ = await _run_with(db, None, None)
        await run_execution.persist_outcome(
            db,
            run,
            RunOutcome(status="awaiting_review", draft_report="d"),
            state={},
            prompt_provenance=everything,
        )
        await db.commit()

    assert set(run.effective_prompt_provenance) == set(RUN_PURPOSES)


async def test_the_persisted_result_does_not_depend_on_invocation_order(tmp_path):
    """Two runs that composed the same purposes in different segments persist the same thing.

    Determinism matters because the bundle hash covers the provenance: a run whose records
    depended on how it happened to be split would hash differently from an identical one.
    """
    from app import run_execution
    from research_engine.runner import RunOutcome

    async def persist(path, segments):
        async with open_db(path) as maker, maker() as db:
            run, _ = await _run_with(db, None, None)
            for segment in segments:
                await run_execution.persist_outcome(
                    db,
                    run,
                    RunOutcome(status="awaiting_plan"),
                    prompt_provenance=_captured(segment),
                )
            await db.commit()
            return run.effective_prompt_provenance

    split_one = await persist(
        tmp_path / "a.sqlite", [["planner.main"], ["executor.main", "critic.research"]]
    )
    split_two = await persist(
        tmp_path / "b.sqlite", [["planner.main", "executor.main"], ["critic.research"]]
    )

    assert split_one == split_two


async def test_omitting_provenance_does_not_erase_what_is_already_recorded(tmp_path):
    """A caller that did not drive the graph must not blank the column."""
    from app import run_execution
    from research_engine.runner import RunOutcome

    async with open_db(tmp_path / "keep.sqlite") as maker, maker() as db:
        run, _ = await _run_with(db, _captured(["planner.main"]), "NONE")
        await run_execution.persist_outcome(db, run, RunOutcome(status="awaiting_plan"))
        await db.commit()

    assert set(run.effective_prompt_provenance) == {"planner.main"}


# ── The recorded contract is what protects the duplicated run driver ──────────────


def test_the_golden_run_journey_records_captured_provenance():
    """`tests/parity/drivers.py::_InProcessDispatcher` restates `execute_run` rather than
    calling it — a third run driver, which lagged the moment `execute_run` gained the
    recorder and reported its own omission as a host divergence.

    This pins the *outcome* rather than comparing source: the golden run journey drives a
    real graph run on both hosts, so a driver that stops capturing produces a v1 bundle with
    no provenance. Re-recording the golden would not hide it — the assertions below would
    then fail on the re-recorded file, which a source-text comparison could never claim.

    Deliberately narrow: it checks that capture happened at all, not which purposes ran, so
    an engine change that legitimately skips a conditional purpose does not fail it.
    """
    import json
    from pathlib import Path

    golden = json.loads(
        (Path(__file__).resolve().parents[1] / "parity" / "golden" / "research-run.json").read_text(
            "utf-8"
        )
    )
    blob = json.dumps(golden)

    assert '"bundle_version": 1' not in blob, (
        "the golden run journey emits a v1 bundle — a run driver stopped capturing provenance"
    )
    assert '"bundle_version": 2' in blob
    assert '"effective_prompt"' in blob, "no captured prompt reached the recorded contract"
    assert '"purpose": "chat.' not in blob, "a chat purpose reached a research bundle"
