"""
The prompt seam resolves to today's prompts, byte for byte (RFC AP-7, scope-freeze §17).

`research_engine/prompt_composition.py` is the one place that answers "which system prompt
does this call use". It exists because five agent *roles* fan out across nine shipped
prompts — three of them resolve through the role literal `"critic"` alone — so when V3 lets
a user replace a role's prompt, something has to decide which of that role's prompts the
override may reach.

**With no override in force, every purpose still returns its shipped constant unchanged** —
the majority path, and the one that must stay byte-identical however the composition layer
grows. The override cases below are the other half: a body a user wrote, wrapped in the
untrusted-content note only where the shipped prompt carried one inline, and refused
outright on the four protected purposes.

**Identity, not equality, for the fake-mode case.** `fakes.SCENARIO_BY_PROMPT` is keyed on
the prompt constant objects, so a scripted run finds its script by `is`. A copy would fall
back to the role and collapse the three scenarios that share `critic` into one — the exact
distinction PR #130 was written to preserve.
"""

from __future__ import annotations

import ast
from contextlib import contextmanager
from pathlib import Path

import pytest

from research_engine import fakes, prompts
from research_engine.prompt_composition import (
    NON_RUN_PURPOSES,
    NOTE_CARRYING_PURPOSES,
    OVERRIDABLE_PURPOSES,
    PURPOSE_CONSTANTS,
    ROLES,
    RUN_PURPOSES,
    role_of,
    system_prompt,
)
from research_engine.runconfig import RunConfig, reset_run_config, set_run_config


@contextmanager
def overriding(**by_role: str):
    """Run the block with these role overrides in force, through the real config path.

    Installs a `RunConfig` rather than patching `system_prompt`'s internals: the contextvar
    is how an override actually reaches composition on both hosts, and a test that patched
    the lookup would prove the patch works.
    """
    token = set_run_config(RunConfig(prompt_overrides=by_role))
    try:
        yield
    finally:
        reset_run_config(token)


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


# ── Composition: a user's body, and where the note goes ───────────────────────────

BODY = "Answer only in haiku."


@pytest.mark.parametrize("purpose", sorted(OVERRIDABLE_PURPOSES))
def test_an_override_replaces_an_overridable_purposes_prompt(purpose):
    """The hop itself: a stored body reaches the model for every eligible purpose."""
    with overriding(**{role_of(purpose): BODY}):
        assert BODY in system_prompt(purpose)
        assert system_prompt(purpose) is not PURPOSE_CONSTANTS[purpose]


@pytest.mark.parametrize("purpose", sorted(OVERRIDABLE_PURPOSES & NOTE_CARRYING_PURPOSES))
def test_a_note_carrying_purpose_keeps_its_note_around_the_users_body(purpose):
    """The note is the defence that stops retrieved text giving the model instructions.

    It is inline in the shipped constants, so replacing one wholesale would delete it — and
    the deletion would be invisible, because the prompt still reads like a prompt. Bracketed
    on both sides for the same reason the shipped constants are: a body long enough to push
    the opening note out of attention still has one at the end.
    """
    note = prompts.UNTRUSTED_CONTENT_NOTE
    with overriding(**{role_of(purpose): BODY}):
        composed = system_prompt(purpose)
    assert composed.startswith(note) and composed.endswith(note)
    assert composed.count(note) == 2
    assert BODY in composed


@pytest.mark.parametrize("purpose", sorted(OVERRIDABLE_PURPOSES - NOTE_CARRYING_PURPOSES))
def test_a_purpose_whose_shipped_prompt_has_no_note_does_not_gain_one(purpose):
    """The control. Wrapping unconditionally would pass every test above and quietly add a
    warning about untrusted content to a prompt that never handles any."""
    with overriding(**{role_of(purpose): BODY}):
        assert system_prompt(purpose) == BODY


def test_the_note_carrying_set_is_derived_from_the_prompts_not_listed():
    """Hand-listing it would drift the moment a prompt gains or loses its note — and the
    failure mode is a user's body replacing a note that nothing puts back."""
    src = (BACKEND / "research_engine" / "prompt_composition.py").read_text(encoding="utf-8")
    node = next(
        n
        for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.AnnAssign)
        and getattr(n.target, "id", None) == "NOTE_CARRYING_PURPOSES"
    )
    assert any(isinstance(g, ast.comprehension) for g in ast.walk(node)), (
        "NOTE_CARRYING_PURPOSES is enumerated; it must be computed from PURPOSE_CONSTANTS"
    )
    assert NOTE_CARRYING_PURPOSES == {
        p for p, c in PURPOSE_CONSTANTS.items() if prompts.UNTRUSTED_CONTENT_NOTE in c
    }


def test_an_override_for_one_role_does_not_leak_to_another():
    with overriding(planner=BODY):
        assert system_prompt("planner.main") == BODY
        assert system_prompt("executor.main") is prompts.EXECUTOR_PROMPT


def test_an_override_reaches_every_overridable_purpose_of_its_role():
    """Eligibility is per purpose, but an override is stored per role. `critic` fans out to
    three purposes and only `critic.research` is eligible — so the same stored body must
    reach that one and stop at the other two."""
    with overriding(critic=BODY):
        assert BODY in system_prompt("critic.research")
        assert system_prompt("critic.citation_verify") is prompts.CITATION_VERIFY_PROMPT
        assert system_prompt("critic.contradiction_detector") is (
            prompts.CONTRADICTION_DETECTOR_PROMPT
        )


@pytest.mark.parametrize("junk", [None, "", "   ", 0, 42, [], {}, ["text"]])
def test_an_override_that_is_not_usable_text_reads_as_no_override(junk):
    """Last-resort defence for a config assembled outside the host builders. Anything that
    is not usable text must fall back to the shipped prompt — never to a partial one, and
    never to `str(junk)`."""
    with overriding(planner=junk):
        assert system_prompt("planner.main") is prompts.PLANNER_PROMPT_V2


@pytest.mark.parametrize("container", ["a string", 42, None, ["planner"], object()])
def test_an_override_container_that_is_not_a_mapping_reads_as_no_override(container):
    """One level up from the test above: the whole `prompt_overrides` field, not one entry.

    Raising here would kill a graph node mid-run over a malformed config field. Falling back
    is the honest failure — the run proceeds on shipped prompts and its row already says
    `UNUSABLE`, which is a state a reader can act on; a half-written report is not.
    """
    token = set_run_config(RunConfig(prompt_overrides=container))
    try:
        assert system_prompt("planner.main") is prompts.PLANNER_PROMPT_V2
    finally:
        reset_run_config(token)


def test_a_demo_run_still_scripts_every_purpose_with_overrides_in_force():
    """Demo mode is a shipped feature, and PR-6 changes the string those runs see.

    `_ScriptedModel` matches a known constant as a substring first and falls back to the
    caller's role — a fallback `fakes` documents as being for exactly this, a platform where
    the system prompt is the user's. What makes it safe is that the two policies line up: the
    only purpose of a role that can be overridden is the one the role-level scenario names.
    `critic` fans out to three, and its other two are protected, so they keep matching by
    constant and no scenario collapses. Making one of them overridable would silently
    mis-script every demo run — which is what this catches.
    """
    every_role = {role: BODY for role in ROLES}
    with overriding(**every_role):
        for purpose in EXPECTED:
            composed = system_prompt(purpose)
            by_prompt = [s for p_, s in fakes.SCENARIO_BY_PROMPT.items() if p_ in composed]
            resolved = by_prompt[0] if by_prompt else fakes.SCENARIO_BY_ROLE[role_of(purpose)]
            assert resolved is fakes.SCENARIO_BY_PROMPT[PURPOSE_CONSTANTS[purpose]], (
                f"{purpose} scripts as {resolved} once overridden"
            )


# ── Run applicability: which purposes a research run executes ─────────────────────


def test_the_run_partition_covers_every_purpose_exactly_once():
    """Applicability is a total, disjoint partition, and an unclassified purpose fails here.

    Neither default is safe, which is why this is not derived. Leaving a new purpose out of
    the run set silently drops provenance for a prompt that did run; putting it in claims
    provenance for one that did not. Both are silent, both are wrong, so a new purpose has
    to be classified by a person rather than fall to a side.
    """
    assert RUN_PURPOSES | NON_RUN_PURPOSES == set(PURPOSE_CONSTANTS)
    assert not (RUN_PURPOSES & NON_RUN_PURPOSES)


def test_the_seven_research_run_purposes_are_the_frozen_seven():
    """Spelled out, because the scope freeze spells them out (§16 decisions, G-2)."""
    assert RUN_PURPOSES == {
        "planner.main",
        "executor.main",
        "critic.research",
        "critic.citation_verify",
        "critic.contradiction_detector",
        "synthesizer.main",
        "synthesizer.repair",
    }


def test_chat_is_the_whole_of_the_non_run_set():
    """Chat answers questions about a finished report; it is not part of producing one."""
    assert NON_RUN_PURPOSES == {"chat.general", "chat.project"}


def test_applicability_is_not_a_restatement_of_the_override_policy():
    """Two independent classifications over the same nine purposes.

    A reader who assumed one implied the other would conclude that everything a run executes
    is overridable, which is false in both directions: three run purposes are protected, and
    `chat.general` is overridable but never runs during a run.
    """
    assert RUN_PURPOSES & OVERRIDABLE_PURPOSES == {
        "planner.main",
        "executor.main",
        "critic.research",
        "synthesizer.main",
    }
    assert "chat.general" in OVERRIDABLE_PURPOSES and "chat.general" not in RUN_PURPOSES


def test_adding_applicability_did_not_move_the_override_boundary():
    """The guard on this change: classification for the bundle must not have altered who may
    replace a prompt. Five overridable, four protected, exactly as PR-4 froze them."""
    assert len(OVERRIDABLE_PURPOSES) == 5
    assert len(set(PURPOSE_CONSTANTS) - OVERRIDABLE_PURPOSES) == 4
