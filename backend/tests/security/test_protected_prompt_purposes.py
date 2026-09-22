"""
A user's prompt override can never reach a protected purpose (PR-4, scope freeze §4).

**The defect this forecloses.** Three distinct prompts resolve through the single role
literal `"critic"` — `CRITIC_PROMPT_V2` (`graph.py:1097`), `CITATION_VERIFY_PROMPT`
(`:1318`) and `CONTRADICTION_DETECTOR_PROMPT` (`:1440`). If override eligibility were
answered from the role, a user editing "critic" would be rewriting the component that
decides whether their own citations are supported, and the one that decides whether
conflicting sources are reported. `synthesizer` and `chat` fan out the same way.

So eligibility is a property of the **purpose**, and the tests below try to break that in
the three ways it could actually break:

1. by renaming a protected purpose so its role prefix changes (`test_rotating_...`);
2. by pointing an overridable purpose at a protected prompt (`test_no_overridable_purpose...`);
3. by computing eligibility from the role after all (`test_is_overridable_never_consults...`,
   which reads the function's AST rather than trusting its name).

**Protection is the default.** `PROTECTED_PURPOSES` is the complement of an explicit
allowlist, not a second hand-written list, so a purpose added and forgotten is protected
rather than exposed. `test_a_newly_added_purpose_is_protected_until_classified` pins that
directly, because it is the property that makes the other three durable.

Nothing here makes overrides active. `is_overridable()` has no caller yet; this establishes
the boundary before anything is allowed to flow across it.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from research_engine import prompt_composition as pc
from research_engine import prompts

BACKEND = Path(__file__).resolve().parents[2]

#: The frozen answer (scope freeze §4), written out rather than imported, so a change to the
#: module cannot quietly agree with itself.
FROZEN_PROTECTED = {
    "critic.citation_verify",
    "critic.contradiction_detector",
    "synthesizer.repair",
    "chat.project",
}
FROZEN_OVERRIDABLE = {
    "planner.main",
    "executor.main",
    "critic.research",
    "synthesizer.main",
    "chat.general",
}

#: The constants a user must never be able to replace, by name. Anchored to the constant
#: rather than the purpose string so that renaming a purpose cannot smuggle one of these
#: into an overridable slot.
PROTECTED_CONSTANT_NAMES = {
    "CITATION_VERIFY_PROMPT",
    "CONTRADICTION_DETECTOR_PROMPT",
    "SYNTHESIZER_REPAIR_PROMPT",
    "PROJECT_CHAT_PROMPT",
}


# ── The classification itself ─────────────────────────────────────────────────────


def test_the_protected_set_is_exactly_the_frozen_four():
    assert pc.PROTECTED_PURPOSES == FROZEN_PROTECTED


def test_the_overridable_set_is_exactly_the_frozen_five():
    assert pc.OVERRIDABLE_PURPOSES == FROZEN_OVERRIDABLE


def test_the_two_sets_partition_every_known_purpose():
    """Every purpose is classified, and none is classified twice."""
    assert pc.OVERRIDABLE_PURPOSES | pc.PROTECTED_PURPOSES == set(pc.PURPOSE_CONSTANTS)
    assert not (pc.OVERRIDABLE_PURPOSES & pc.PROTECTED_PURPOSES)


@pytest.mark.parametrize("purpose", sorted(FROZEN_PROTECTED))
def test_a_protected_purpose_is_not_overridable(purpose):
    assert pc.is_overridable(purpose) is False


@pytest.mark.parametrize("purpose", sorted(FROZEN_OVERRIDABLE))
def test_an_overridable_purpose_is_overridable(purpose):
    assert pc.is_overridable(purpose) is True


def test_an_unknown_purpose_raises_rather_than_reading_as_protected():
    """`False` would be the safe answer and the wrong behaviour: it hides the typo, and a
    purpose nobody can override is a purpose whose editor silently does nothing."""
    with pytest.raises(KeyError, match="unknown prompt purpose"):
        pc.is_overridable("critic.typo")
    with pytest.raises(KeyError, match="unknown prompt purpose"):
        pc.is_overridable("critic")  # a role, not a purpose — the likeliest mistake


# ── Anti-rotation ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("purpose", sorted(FROZEN_PROTECTED))
def test_rotating_a_protected_purpose_onto_another_role_cannot_free_it(purpose):
    """Re-keying `critic.citation_verify` as `planner.citation_verify` must not help.

    `OVERRIDABLE_PURPOSES` is an allowlist of exact strings, so every rotation of a
    protected purpose — onto any of the five roles, or a role that does not exist — lands
    outside it. The only way to make something overridable is to add that exact string to
    the allowlist, which is a deliberate and reviewable edit.
    """
    leaf = purpose.split(".", 1)[1]
    for role in (*pc.ROLES, "auditor", "admin", ""):
        assert f"{role}.{leaf}" not in pc.OVERRIDABLE_PURPOSES, (
            f"rotating {purpose!r} onto role {role!r} would make it overridable"
        )


def test_no_overridable_purpose_resolves_to_a_protected_prompt():
    """The other rotation: leave the keys alone and repoint one at a protected constant.

    `PURPOSE_CONSTANTS["critic.research"] = prompts.CITATION_VERIFY_PROMPT` would pass every
    test above while handing the citation verifier to the `critic` editor. Anchoring on the
    constant is what catches it.
    """
    protected_objects = {getattr(prompts, n) for n in PROTECTED_CONSTANT_NAMES}
    leaked = [p for p in pc.OVERRIDABLE_PURPOSES if pc.PURPOSE_CONSTANTS[p] in protected_objects]
    assert not leaked, f"overridable purposes resolve to protected prompts: {leaked}"


def test_every_protected_constant_is_reachable_only_through_a_protected_purpose():
    """The same claim from the other end: each protected prompt has a purpose, and every
    purpose that resolves to it is protected."""
    for name in sorted(PROTECTED_CONSTANT_NAMES):
        constant = getattr(prompts, name)
        purposes = [p for p, c in pc.PURPOSE_CONSTANTS.items() if c is constant]
        assert purposes, f"{name} has no purpose; it would be unreachable through the seam"
        for purpose in purposes:
            assert purpose in pc.PROTECTED_PURPOSES, f"{name} is reachable via {purpose}"


def test_protected_is_derived_from_the_allowlist_not_enumerated():
    """The fail-closed property, pinned structurally rather than behaviourally.

    A hand-written `PROTECTED_PURPOSES = {...}` listing today's four would satisfy every
    other test in this file — the two sets coincide right now, so nothing behavioural can
    tell the difference. What it would quietly remove is the guarantee for *tomorrow*: a
    purpose added to `PURPOSE_CONSTANTS` and forgotten would then be in neither set instead
    of protected. So this reads the assignment itself.
    """
    module = ast.parse((BACKEND / "research_engine" / "prompt_composition.py").read_text("utf-8"))
    assigned = [
        n
        for n in module.body
        if isinstance(n, ast.AnnAssign)
        and isinstance(n.target, ast.Name)
        and n.target.id == "PROTECTED_PURPOSES"
    ]
    assert len(assigned) == 1, "PROTECTED_PURPOSES must be assigned exactly once"
    expr = ast.unparse(assigned[0].value)
    assert "-" in expr and "PURPOSE_CONSTANTS" in expr and "OVERRIDABLE_PURPOSES" in expr, (
        "PROTECTED_PURPOSES must be the complement of the allowlist over PURPOSE_CONSTANTS, "
        f"not an enumerated list; found: {expr}"
    )


def test_a_newly_added_purpose_is_protected_until_classified():
    """The property that keeps the rest true as the codebase grows.

    Simulated against the real sets rather than by mutating the module: `PROTECTED_PURPOSES`
    is the complement of the allowlist, so anything not named in the allowlist is protected
    by construction — including a purpose that does not exist yet.
    """
    assert pc.PROTECTED_PURPOSES == set(pc.PURPOSE_CONSTANTS) - pc.OVERRIDABLE_PURPOSES
    for hypothetical in ("critic.new_check", "synthesizer.rewrite", "chat.summarise"):
        assert hypothetical not in pc.OVERRIDABLE_PURPOSES


# ── No role-based path, proved structurally ───────────────────────────────────────


def test_is_overridable_never_consults_the_role():
    """Read the function, do not trust its name.

    A `role_of()` call inside `is_overridable` would be the exact defect this file exists to
    prevent, and it would still pass every behavioural test above on today's data.
    """
    tree = ast.parse(inspect.getsource(pc.is_overridable))
    called = {
        n.func.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "role_of" not in called
    assert "_checked" in called, "eligibility must still fail closed on an unknown purpose"


def test_the_module_exposes_no_role_keyed_eligibility_helper():
    """There is no `is_role_overridable`, and there must not be.

    A helper that answers from a role would have to be wrong for two of `critic`'s three
    purposes, and its existence is what a future caller would reach for.
    """
    suspects = [
        name
        for name in vars(pc)
        if name.startswith(("is_", "can_", "may_")) and "role" in name.lower()
    ]
    assert not suspects, f"role-keyed eligibility helpers exist: {suspects}"


def test_the_critic_role_alone_cannot_answer_the_question():
    """Why the purpose vocabulary exists, asserted rather than asserted in prose.

    `critic` spans both policies. Any future code that resolves eligibility from a role is
    therefore provably wrong for this role, whatever it returns.
    """
    critic = {p for p in pc.PURPOSE_CONSTANTS if pc.role_of(p) == "critic"}
    assert critic & pc.OVERRIDABLE_PURPOSES
    assert critic & pc.PROTECTED_PURPOSES


@pytest.mark.parametrize("role", ["critic", "synthesizer", "chat"])
def test_every_fanned_out_role_spans_both_policies(role):
    """`critic`, `synthesizer` and `chat` each own more than one purpose, and in each case
    at least one is protected — so none of the three can be answered from the role."""
    owned = {p for p in pc.PURPOSE_CONSTANTS if pc.role_of(p) == role}
    assert len(owned) > 1
    assert owned & pc.PROTECTED_PURPOSES


# ── Nothing is active yet ─────────────────────────────────────────────────────────


def test_nothing_consumes_eligibility_yet():
    """PR-4 draws the boundary; PR-6 is what makes overrides flow across it.

    If this starts failing because a caller appeared, the caller belongs in the change that
    also carries the override plumbing and its behavioural tests — not here.
    """
    callers = []
    for path in sorted(BACKEND.rglob("*.py")):
        rel = path.relative_to(BACKEND).as_posix()
        if rel.startswith((".venv", "desktop/target")) or "test_" in path.name:
            continue
        if rel.endswith("research_engine/prompt_composition.py"):
            continue
        if "is_overridable" in path.read_text(encoding="utf-8"):
            callers.append(rel)
    assert not callers, f"is_overridable is being consumed by: {callers}"


def test_shipped_prompt_resolution_is_unchanged_by_the_policy_layer():
    """PR-4 adds classification, not behaviour: every purpose still returns its constant."""
    for purpose, constant in pc.PURPOSE_CONSTANTS.items():
        assert pc.system_prompt(purpose) is constant
