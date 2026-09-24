"""
Storing a replacement prompt: what is accepted, what is refused, and what reset means.

This file is the **storage** half: what a request may put in `users.preferences`, what it is
refused for, and what resetting one role means. What consuming it looks like — the snapshot a
run freezes, and the purposes an override may reach — is
`tests/dataflow/test_prompt_override_snapshot.py` and `tests/task/test_prompt_composition.py`.
The split matters, because the API's refusals are not what makes the boundary safe: a
snapshot can also arrive from a hand-edited row, so the runtime re-checks everything below
rather than trusting that a request came through this validator.

**Two things here are not just field validation.**

*The merge is two levels deep.* Preferences arrive a section at a time and are merged rather
than replaced, so a request that sets one role's prompt must not drop the other four — which
a top-level `dict.update` would do, because `prompt_overrides` is itself a map. `null` for a
role therefore deletes that role's entry, which is what makes "reset this one" distinguish-
able from "I sent you nothing about it". `app/services/preferences.py` is the one home for
that rule; before it, the top-level merge was already restated per host.

*The desktop used to validate nothing.* It merged raw JSON, so a preference the server
refused with a 422 was stored there without complaint. That gap is harmless for
`retrieval_k` and is not harmless for a field that sits on the boundary PR-4 drew, so both
hosts now go through `UserPreferences`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.auth import MAX_PROMPT_OVERRIDE_CHARS, UserPreferences
from app.services.preferences import merge_preferences
from research_engine.prompt_composition import ROLES

VALID = "You are a meticulous research planner. Prefer primary sources."


def _prefs(**overrides):
    return UserPreferences.model_validate({"prompt_overrides": overrides})


# ── Positive ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("role", sorted(ROLES))
def test_every_public_role_accepts_an_override(role):
    assert _prefs(**{role: VALID}).prompt_overrides == {role: VALID}


def test_the_public_role_set_is_exactly_the_canonical_one():
    """Requirement 8: the roles come from `prompt_composition`, not a second list here.

    Acceptance per role is the parametrized test above; this pins the set itself, so the
    schema cannot start accepting a sixth role without someone changing the frozen surface.
    """
    assert set(ROLES) == {"planner", "executor", "critic", "synthesizer", "chat"}
    from app.schemas import auth as auth_schema

    assert auth_schema.ROLES is ROLES, "the schema must not carry its own copy of the roles"


# ── Absent / empty / reset ────────────────────────────────────────────────────────


def test_absent_is_the_default_and_stays_unset():
    assert UserPreferences().prompt_overrides is None
    assert "prompt_overrides" not in UserPreferences().model_dump(exclude_unset=True)


def test_an_empty_map_is_accepted_and_means_nothing_is_overridden():
    assert UserPreferences.model_validate({"prompt_overrides": {}}).prompt_overrides == {}


def test_null_for_a_role_is_accepted_as_the_reset_sentinel():
    assert _prefs(critic=None).prompt_overrides == {"critic": None}


def test_null_for_the_whole_field_is_accepted():
    assert UserPreferences.model_validate({"prompt_overrides": None}).prompt_overrides is None


# ── Negative ──────────────────────────────────────────────────────────────────────


def test_an_empty_string_is_refused_and_says_what_to_send_instead():
    """An empty system prompt is a deletion, not a customisation, and the two must not be
    confusable — so the refusal names `null` rather than just failing."""
    with pytest.raises(ValidationError, match="send null to reset"):
        _prefs(critic="")


@pytest.mark.parametrize("blank", [" ", "   ", "\t", "\n", " \t\n "])
def test_whitespace_only_is_refused(blank):
    with pytest.raises(ValidationError, match="is empty"):
        _prefs(planner=blank)


@pytest.mark.parametrize("bad", [1, 0, 1.5, True, [], {}, ["a"], {"a": 1}])
def test_a_non_string_override_is_refused(bad):
    with pytest.raises(ValidationError, match="must be a string or null"):
        _prefs(executor=bad)


@pytest.mark.parametrize(
    "role", ["researcher", "citation_verify", "critic.citation_verify", "Critic", "", "admin"]
)
def test_an_unknown_role_is_refused_and_the_error_names_the_valid_ones(role):
    """Fail closed, and specifically closed against purpose-shaped keys: `critic.citation_verify`
    is a purpose, not a role, and must not be reachable through this surface."""
    with pytest.raises(ValidationError, match="unknown agent role"):
        UserPreferences.model_validate({"prompt_overrides": {role: VALID}})


@pytest.mark.parametrize("bad", ["a string", 42, ["critic"], True])
def test_a_non_object_prompt_overrides_is_refused(bad):
    with pytest.raises(ValidationError, match="must be an object keyed by agent role"):
        UserPreferences.model_validate({"prompt_overrides": bad})


def test_an_unknown_preference_key_is_still_refused():
    """`extra="forbid"` predates this field and must keep holding."""
    with pytest.raises(ValidationError):
        UserPreferences.model_validate({"prompt_overrideZ": {}})


# ── Boundary ──────────────────────────────────────────────────────────────────────


def test_exactly_the_maximum_is_accepted():
    text = "x" * MAX_PROMPT_OVERRIDE_CHARS
    assert _prefs(synthesizer=text).prompt_overrides["synthesizer"] == text


def test_one_over_the_maximum_is_refused_and_the_error_states_both_numbers():
    with pytest.raises(ValidationError, match=f"is {MAX_PROMPT_OVERRIDE_CHARS + 1} characters"):
        _prefs(synthesizer="x" * (MAX_PROMPT_OVERRIDE_CHARS + 1))


def test_the_limit_clears_the_largest_shipped_prompt():
    """2,500 exists so a user can write something of the scale we ship (freeze §7, D-2).
    If a shipped prompt ever grows past the ceiling, the ceiling is wrong, not the prompt."""
    from research_engine.prompt_composition import PURPOSE_CONSTANTS

    largest = max(len(v) for v in PURPOSE_CONSTANTS.values())
    assert largest <= MAX_PROMPT_OVERRIDE_CHARS


def test_the_limit_is_per_role_with_no_total_across_the_five():
    """Requirement 7: no artificial global requirement. Five at the ceiling is fine."""
    text = "x" * MAX_PROMPT_OVERRIDE_CHARS
    prefs = _prefs(**{r: text for r in ROLES})
    assert len(prefs.prompt_overrides) == len(ROLES)


def test_a_role_is_measured_after_the_value_arrives_not_after_stripping():
    """2,500 characters of real prose is accepted even when it ends in whitespace; the
    strip is only how emptiness is detected, not how length is counted."""
    text = "x" * (MAX_PROMPT_OVERRIDE_CHARS - 1) + " "
    assert len(_prefs(chat=text).prompt_overrides["chat"]) == MAX_PROMPT_OVERRIDE_CHARS


# ── The merge ─────────────────────────────────────────────────────────────────────


def test_setting_one_role_leaves_the_others_alone():
    """The defect a top-level merge would cause: `prompt_overrides` is a map, so replacing
    it wholesale would drop four roles to set one."""
    stored = {"prompt_overrides": {"planner": "P", "critic": "C"}}
    out = merge_preferences(stored, {"prompt_overrides": {"chat": "H"}})
    assert out["prompt_overrides"] == {"planner": "P", "critic": "C", "chat": "H"}


def test_null_removes_only_that_role():
    stored = {"prompt_overrides": {"planner": "P", "critic": "C"}}
    out = merge_preferences(stored, {"prompt_overrides": {"critic": None}})
    assert out["prompt_overrides"] == {"planner": "P"}


def test_resetting_the_last_override_leaves_no_empty_map_behind():
    """A user who reset their last override must look like one who never set any."""
    stored = {"prompt_overrides": {"critic": "C"}}
    out = merge_preferences(stored, {"prompt_overrides": {"critic": None}})
    assert "prompt_overrides" not in out


def test_null_for_the_whole_field_clears_every_override():
    stored = {"prompt_overrides": {"planner": "P", "critic": "C"}}
    assert "prompt_overrides" not in merge_preferences(stored, {"prompt_overrides": None})


def test_other_preferences_survive_a_prompt_override_request():
    stored = {"retrieval_k": 9, "prompt_overrides": {"planner": "P"}}
    out = merge_preferences(stored, {"prompt_overrides": {"critic": "C"}})
    assert out["retrieval_k"] == 9


def test_prompt_overrides_survive_an_unrelated_section_request():
    stored = {"prompt_overrides": {"planner": "P"}}
    out = merge_preferences(stored, {"retrieval_k": 9})
    assert out["prompt_overrides"] == {"planner": "P"}
    assert out["retrieval_k"] == 9


def test_merge_mutates_neither_argument():
    stored = {"prompt_overrides": {"planner": "P"}}
    incoming = {"prompt_overrides": {"critic": "C"}}
    merge_preferences(stored, incoming)
    assert stored == {"prompt_overrides": {"planner": "P"}}
    assert incoming == {"prompt_overrides": {"critic": "C"}}


def test_merging_onto_no_stored_preferences_works():
    assert merge_preferences(None, {"prompt_overrides": {"critic": "C"}}) == {
        "prompt_overrides": {"critic": "C"}
    }


# ── One implementation, both hosts ────────────────────────────────────────────────


def test_both_hosts_merge_through_the_same_function_object():
    """Unfakeable: two copies cannot be one object.

    The merge rule already had two homes before this field existed — the top-level
    `dict.update` was restated per host — and `prompt_overrides` adds a second level to it.
    A shared *name* proves nothing if each host imports its own; identity does.
    """
    from app.api.v1 import auth as server_route
    from app.services.preferences import merge_preferences as canonical
    from desktop import sidecar as desktop_host

    assert server_route.merge_preferences is canonical
    assert desktop_host.merge_preferences is canonical


def test_both_hosts_validate_through_the_same_model_class():
    """The server reaches it through `ProfileUpdate.preferences` and the desktop calls
    `model_validate` directly, because one parses a request model and the other parses raw
    JSON. Different routes to the same class — which is what makes the refusals identical."""
    import typing

    from app.schemas.auth import ProfileUpdate, UserPreferences
    from desktop import sidecar as desktop_host

    # `preferences` is optional on the request model, so the annotation is a union.
    annotated = ProfileUpdate.model_fields["preferences"].annotation
    members = typing.get_args(annotated) or (annotated,)
    assert UserPreferences in members, f"server validates through {annotated}, not the model"
    assert desktop_host.UserPreferences is UserPreferences


def test_neither_host_restates_the_validation_or_the_merge():
    """A second implementation would satisfy the identity tests above only until someone
    stopped importing — so this checks nobody has started defining their own."""
    import ast
    from pathlib import Path

    backend = Path(__file__).resolve().parents[2]
    for rel in ("app/api/v1/auth.py", "desktop/sidecar.py"):
        tree = ast.parse((backend / rel).read_text(encoding="utf-8"))
        defined = {
            n.name
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
        assert "merge_preferences" not in defined, f"{rel} defines its own merge"
        assert "UserPreferences" not in defined, f"{rel} defines its own preferences model"


# ── Where the stored value is allowed to go ───────────────────────────────────────


def _runtime_modules():
    """Every production module, i.e. not tests, not vendored, not build output."""
    backend = Path(__file__).resolve().parents[2]
    for path in sorted(backend.rglob("*.py")):
        rel = path.relative_to(backend).as_posix()
        if rel.startswith((".venv", "desktop/target", "alembic/")) or "test_" in path.name:
            continue
        yield rel, ast.parse(path.read_text(encoding="utf-8"))


def _calls(tree) -> set[str]:
    """Names actually *invoked* — not merely mentioned.

    A substring search cannot tell a call from a comment, which is the failure mode
    `AGENTS.md` records about this repository's own CI greps: prose naming a banned token
    failed the build as surely as using one. These tests name the functions they forbid, so
    they have to be able to tell the difference about themselves.
    """
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            if isinstance(n.func, ast.Name):
                out.add(n.func.id)
            elif isinstance(n.func, ast.Attribute):
                out.add(n.func.attr)
    return out


#: The modules allowed to put a stored override into a `RunConfig`, each with why.
#: Anywhere else is a second path from preferences to a prompt, and the second path is the
#: one that skips the snapshot — which is how a resumed run would come to be executing
#: instructions its first half never saw.
_MAY_DIAL_AN_OVERRIDE = {
    # Builds the chat turn's config: live by design, since chat has no run to be consistent
    # with. Also the one home for the run-time snapshot rules both hosts read.
    "app/services/run_config.py": "chat_run_config / the snapshot rules",
    # The server's run builder, reading the frozen row and never the live preference.
    "app/run_execution.py": "run_config_for_run, from the snapshot",
    # The desktop's in-process driver, through `run_execution`'s two functions.
    "desktop/sidecar.py": "_drive_run, from the same snapshot",
    # Not a stored override: the custom-spec eval's candidate, read from an explicit
    # `--candidate` file and installed only around `graph.ainvoke` (AgentSpec RFC §14.1).
    # This test cannot see what feeds that write; `test_eval_custom_spec::
    # test_the_candidate_never_comes_from_a_stored_row` is what keeps preferences out.
    "evals/harness.py": "_pipeline_scope, from an explicit candidate file",
}


def test_only_the_snapshot_path_dials_a_stored_override():
    """The hop exists now; what must not exist is a *second* one.

    `RunConfig.prompt_overrides` is written three syntactic ways, and all three are checked:
    a keyword to `replace()`/the constructor, an attribute assignment, and — how both run
    builders actually do it — a `"prompt_overrides"` key in a dict that is later splatted
    in. Catching only the first two would miss the shape most likely to be copied, since a
    new builder would be written by copying an existing one. Every writer is enumerated
    above with the reason it is allowed; an entry that stops being true fails this too.
    """
    writers = set()
    for rel, tree in _runtime_modules():
        for n in ast.walk(tree):
            wrote = (
                (isinstance(n, ast.Call) and any(kw.arg == "prompt_overrides" for kw in n.keywords))
                or (
                    isinstance(n, ast.Attribute)
                    and n.attr == "prompt_overrides"
                    and isinstance(getattr(n, "ctx", None), ast.Store)
                )
                or (
                    isinstance(n, ast.Dict)
                    and any(
                        isinstance(k, ast.Constant) and k.value == "prompt_overrides"
                        for k in n.keys
                    )
                )
            )
            if wrote:
                writers.add(rel)
    assert writers == set(_MAY_DIAL_AN_OVERRIDE), (
        f"unexpected: {sorted(writers - set(_MAY_DIAL_AN_OVERRIDE))}, "
        f"gone: {sorted(set(_MAY_DIAL_AN_OVERRIDE) - writers)}"
    )


def test_system_prompt_takes_only_a_purpose():
    """No call site may supply an override.

    An override parameter would make every caller a place the policy could be bypassed —
    which is the whole reason `system_prompt` reads the ambient config instead. The single
    enforcement point only holds if there is no way to hand it a body directly.
    """
    import inspect as _inspect

    from research_engine.prompt_composition import system_prompt

    assert list(_inspect.signature(system_prompt).parameters) == ["purpose"]


def test_the_preference_field_list_stays_free_of_prompt_overrides():
    """The five in `PREFERENCE_FIELDS` are re-read on every resume, which is right for them
    and wrong for this one. Adding it there would restore the live read the snapshot exists
    to remove, and every test of the snapshot would still pass — the run would simply take
    the newer value."""
    from app.services.run_config import PREFERENCE_FIELDS

    assert "prompt_overrides" not in PREFERENCE_FIELDS
