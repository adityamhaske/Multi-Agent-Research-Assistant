"""
What the prompt editors may show, and what they may never show (scope freeze §12, D-1).

`GET /models/prompt-defaults` puts shipped prompt text on the wire for the first time, so it
is a new place the protected-purpose boundary could leak through. The rule it must hold is
§12's: "Protected purposes are never exposed." These tests hold it at the one producer,
`prompt_composition.editable_defaults`; `tests/workflow/test_prompt_defaults_route.py`
holds it again on the bytes both hosts actually serve.

**Why "distinctive" lines.** Two protected prompts share one boilerplate sentence each with
an overridable one — the same schema instruction, the same citation rule. Those sentences
are shipped text of an editable purpose too, so seeing them proves nothing. What must never
appear is the text only a protected prompt carries; the test computes that set and refuses
to pass on an empty one.
"""

from __future__ import annotations

from dataclasses import replace

from app.schemas.auth import MAX_PROMPT_OVERRIDE_CHARS, UserPreferences
from research_engine import prompts
from research_engine.prompt_composition import (
    NOTE_CARRYING_PURPOSES,
    OVERRIDABLE_PURPOSES,
    PROTECTED_PURPOSES,
    PURPOSE_CONSTANTS,
    ROLES,
    editable_defaults,
    role_of,
)
from research_engine.runconfig import RunConfig, reset_run_config, set_run_config

NOTE = prompts.UNTRUSTED_CONTENT_NOTE

#: §12 names these four as never to be mentioned by the customisation surface.
FORBIDDEN_NAMES = (
    "citation_verify",
    "contradiction_detector",
    "synthesizer.repair",
    "chat.project",
)


def _overridable_purpose(role: str) -> str:
    (purpose,) = [p for p in OVERRIDABLE_PURPOSES if role_of(p) == role]
    return purpose


def _distinctive_protected_lines() -> dict[str, set[str]]:
    """Per protected purpose, the lines no overridable prompt also ships."""
    editable_text = "\n".join(PURPOSE_CONSTANTS[p] for p in OVERRIDABLE_PURPOSES)
    return {
        purpose: {
            line.strip()
            for line in PURPOSE_CONSTANTS[purpose].splitlines()
            if line.strip() and line.strip() not in editable_text
        }
        for purpose in PROTECTED_PURPOSES
    }


def test_one_entry_per_public_role_in_role_order():
    assert [d.role for d in editable_defaults()] == list(ROLES)
    assert len(ROLES) == 5


def test_each_entry_is_its_roles_overridable_prompt_with_only_the_note_removed():
    """Every line is a line the role's editable purpose ships, and the only shipped line
    missing is the untrusted-content note — nothing else is trimmed, nothing is added."""
    for d in editable_defaults():
        shipped = PURPOSE_CONSTANTS[_overridable_purpose(d.role)]
        shown = {line for line in d.text.splitlines() if line.strip()}
        shipped_lines = {line for line in shipped.splitlines() if line.strip()}
        assert shown <= shipped_lines, d.role
        assert shipped_lines - shown == ({NOTE} if d.framed else set()), d.role


def test_no_editable_default_carries_the_untrusted_content_note():
    for d in editable_defaults():
        assert NOTE not in d.text, d.role


def test_framed_is_exactly_whether_composition_adds_the_note():
    for d in editable_defaults():
        assert d.framed == (_overridable_purpose(d.role) in NOTE_CARRYING_PURPOSES), d.role
    assert sum(d.framed for d in editable_defaults()) == 4


def test_no_protected_prompt_text_is_exposed():
    distinctive = _distinctive_protected_lines()
    for purpose, lines in distinctive.items():
        assert lines, f"{purpose} has no distinctive text — this check would pass vacuously"
    shown = "\n".join(d.text for d in editable_defaults())
    leaked = {
        p: sorted(line for line in lines if line in shown) for p, lines in distinctive.items()
    }
    assert not any(leaked.values()), f"protected prompt text exposed: {leaked}"


def test_no_protected_purpose_is_named():
    shown = "\n".join(f"{d.role}\n{d.text}" for d in editable_defaults())
    for name in FORBIDDEN_NAMES:
        assert name not in shown, name


def test_every_default_is_accepted_unchanged_as_an_override():
    """Saving the starting text as-is must not be refused — so each fits the user limit and
    passes the same validation a real save goes through."""
    for d in editable_defaults():
        assert len(d.text) <= MAX_PROMPT_OVERRIDE_CHARS, d.role
        UserPreferences.model_validate({"prompt_overrides": {d.role: d.text}})


def test_the_defaults_ignore_any_installed_override():
    """A property of the build: an override in force changes what a run composes, never
    what the editor starts from."""
    baseline = editable_defaults()
    token = set_run_config(
        replace(RunConfig(), prompt_overrides={role: f"OVERRIDE {role}" for role in ROLES})
    )
    try:
        assert editable_defaults() == baseline
    finally:
        reset_run_config(token)
