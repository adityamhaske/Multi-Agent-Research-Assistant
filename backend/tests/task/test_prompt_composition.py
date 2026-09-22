"""
The prompt seam resolves to today's prompts, byte for byte (RFC AP-7, scope-freeze §17).

`research_engine/prompt_composition.py` is the one place that answers "which system prompt
does this call use". It exists because five agent *roles* fan out across nine shipped
prompts — three of them resolve through the role literal `"critic"` alone — so when V3 lets
a user replace a role's prompt, something has to decide which of that role's prompts the
override may reach.

**This module reads no override yet, and these tests are the proof.** Every purpose returns
its shipped constant unchanged, so introducing the seam cannot have altered a single run.
The override policy and the untrusted-content recomposition are later changes, deliberately
separate: moving the note out of the six constants that carry it inline *changes the string
the model sees*, which belongs with the change that makes the body user-authored.

**Identity, not equality, for the fake-mode case.** `fakes.SCENARIO_BY_PROMPT` is keyed on
the prompt constant objects, so a scripted run finds its script by `is`. A copy would fall
back to the role and collapse the three scenarios that share `critic` into one — the exact
distinction PR #130 was written to preserve.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from research_engine import fakes, prompts
from research_engine.prompt_composition import (
    PURPOSE_CONSTANTS,
    ROLES,
    role_of,
    system_prompt,
)

BACKEND = Path(__file__).resolve().parents[2]

#: purpose -> the constant it must resolve to, spelled out rather than derived from the
#: module under test. A table generated from the implementation would agree with itself.
EXPECTED = {
    "planner.main": "PLANNER_PROMPT_V2",
    "executor.main": "EXECUTOR_PROMPT",
    "critic.research": "CRITIC_PROMPT_V2",
    "critic.citation_verify": "CITATION_VERIFY_PROMPT",
    "critic.contradiction_detector": "CONTRADICTION_DETECTOR_PROMPT",
    "synthesizer.main": "SYNTHESIZER_PROMPT_V2",
    "synthesizer.repair": "SYNTHESIZER_REPAIR_PROMPT",
    "chat.general": "CHAT_PROMPT",
    "chat.project": "PROJECT_CHAT_PROMPT",
}


# ── Byte-for-byte, and by identity ────────────────────────────────────────────────


@pytest.mark.parametrize(("purpose", "constant"), sorted(EXPECTED.items()))
def test_every_purpose_resolves_to_its_shipped_constant(purpose, constant):
    assert system_prompt(purpose) == getattr(prompts, constant)
    assert system_prompt(purpose) is getattr(prompts, constant), (
        "must be the same object: fakes.SCENARIO_BY_PROMPT resolves a scripted run by identity"
    )


def test_a_scripted_run_still_finds_its_script_through_the_seam():
    """The regression that would make every fake run fall back to its role."""
    for purpose in EXPECTED:
        composed = system_prompt(purpose)
        assert composed in fakes.SCENARIO_BY_PROMPT, (
            f"{purpose} no longer matches a scripted scenario by identity"
        )


# ── The purpose vocabulary ────────────────────────────────────────────────────────


def test_every_shipped_prompt_has_exactly_one_purpose():
    """Anti-rot: a prompt added to prompts.py and not registered here is invisible to the
    seam, so a later override policy could never reach — or protect — it."""
    shipped = {
        name
        for name, value in vars(prompts).items()
        if name.isupper() and isinstance(value, str) and name != "UNTRUSTED_CONTENT_NOTE"
    }
    assert shipped == set(EXPECTED.values()), (
        "prompts.py and the purpose registry disagree; register the new constant"
    )
    assert len(PURPOSE_CONSTANTS) == len(shipped)


def test_the_five_roles_are_exactly_the_model_roles():
    from research_engine.runconfig import DEFAULT_MODELS

    assert set(ROLES) == set(DEFAULT_MODELS)


@pytest.mark.parametrize(("purpose", "role"), [(p, p.split(".")[0]) for p in sorted(EXPECTED)])
def test_role_of_reads_the_role_off_the_purpose(purpose, role):
    assert role_of(purpose) == role


def test_three_purposes_share_the_critic_role():
    """The fan-out that makes a purpose vocabulary necessary rather than decorative."""
    assert sorted(p for p in PURPOSE_CONSTANTS if role_of(p) == "critic") == [
        "critic.citation_verify",
        "critic.contradiction_detector",
        "critic.research",
    ]


def test_an_unknown_purpose_raises_instead_of_resolving_to_something_plausible():
    with pytest.raises(KeyError, match="unknown prompt purpose"):
        system_prompt("critic")  # a role, not a purpose — the likeliest mistake
    with pytest.raises(KeyError, match="unknown prompt purpose"):
        role_of("planner.typo")


# ── The seam is actually used ─────────────────────────────────────────────────────


def test_no_call_site_still_selects_a_prompt_constant_directly():
    """Otherwise the seam exists and something bypasses it, which is worse than no seam.

    `prompts.planner_human` / `prompts.synthesizer_human` are *human* message builders and
    are deliberately out of scope — this checks system-prompt selection only.
    """
    offenders = []
    for rel in (
        "research_engine/graph.py",
        "app/api/v1/chat.py",
        "app/api/v1/threads.py",
        "desktop/sidecar.py",
        "evals/harness.py",
    ):
        source = (BACKEND / rel).read_text(encoding="utf-8")
        for name in EXPECTED.values():
            if f"prompts.{name}" in source:
                offenders.append(f"{rel}: prompts.{name}")
    assert not offenders, "these select a system prompt without the seam:\n  " + "\n  ".join(
        offenders
    )


def test_the_module_imports_nothing_it_may_not():
    """It sits on the desktop's request-time import path and the engine's.

    `research_engine` may not import `app` or `evals` (`test_engine_boundary`), and anything
    the desktop imports at request time must also fit the PyInstaller bundle.
    """
    tree = ast.parse((BACKEND / "research_engine" / "prompt_composition.py").read_text("utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = ("app", "evals", "desktop", "fastapi", "starlette", "sqlalchemy", "alembic")
    assert not [m for m in imported if m.split(".")[0] in forbidden], sorted(imported)


def test_prompts_remains_a_pure_constants_module():
    """If `prompts.py` gains a runtime dependency, the constants stop being inert and the
    identity mapping `fakes` relies on becomes something that can change under it."""
    tree = ast.parse((BACKEND / "research_engine" / "prompts.py").read_text("utf-8"))
    assert not [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
