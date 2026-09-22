"""
The rules that decide what a run actually dials — shared by both hosts.

Building a `RunConfig` is host-specific: the server reads pydantic settings and a decrypted
BYOK column, the desktop reads environment plus the OS keychain, and the CLI reads `os.environ`.
Those stay three builders. What must not be three — or four, as it was — are the *rules*
applied on top of whatever a host built.

Three rules live here: which preferences a run honours, whether a run is scripted, and
what a stored prompt-override snapshot is allowed to become at execution time.

Nothing here may import FastAPI, `app.config`, `app.db` or anything reaching them: the
desktop imports this module on every run. That is also why the preference rule below takes
a structural type rather than importing the `User` model — the rule is about the mapping,
not about a table.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from typing import Any, Protocol

from research_engine.runconfig import (
    RunConfig,
    get_run_config,
    reset_run_config,
    set_run_config,
)


class HasPreferences(Protocol):
    """A user row on either host: the server's decrypted-column `User`, or the desktop's
    single local one. Only the preferences mapping is read."""

    preferences: Mapping[str, Any] | None


#: Preference keys that map 1:1 onto a `RunConfig` field of the same name
#: (internal/07 Phase 3). `None`/absent means "use the deployment default" — the class
#: default already
#: is that default, so an unset preference contributes nothing to `replace()`.
#:
#: **One tuple, four builders.** `pipeline_runner._run_config_for`,
#: `run_execution.run_config_for_run`, `sidecar._drive_session` and `sidecar._drive_run`
#: all read this. It was previously private to `pipeline_runner`, imported by
#: `run_execution`, restated as a literal in `_drive_session`, and absent entirely from
#: `_drive_run` — so the desktop's primary pipeline silently honoured none of it. A list
#: that three call sites share by discipline is a list the fourth can be written without.
PREFERENCE_FIELDS: tuple[str, ...] = (
    "retrieval_k",
    "min_sources_per_task",
    "snippet_max_chars",
    "tavily_api_key",
    "brave_api_key",
)


def preference_overrides(user: HasPreferences | None) -> dict[str, Any]:
    """The `replace()` kwargs this user's saved preferences contribute, and nothing else.

    Absent and `None` are both "unset" and yield no key, which is what keeps a user who
    set one preference from resetting the other four to an explicit null.
    """
    prefs = (user.preferences if user else None) or {}
    return {k: prefs[k] for k in PREFERENCE_FIELDS if prefs.get(k) is not None}


def is_scripted(*, row_demo: bool, host_is_scripted: bool) -> bool:
    """Whether this run reaches a real provider. The rule itself, on its own.

    Exposed separately because the desktop needs the answer *before* it can build a
    config at all: `sidecar_run_config` takes a different branch for a scripted run and
    raises when a real one has no provider key. Deciding it inline there would have been a
    fifth home for the one line that matters.
    """
    return row_demo or host_is_scripted


def apply_demo_rule(
    base: RunConfig, *, row_demo: bool, host_is_scripted: bool
) -> tuple[RunConfig, bool]:
    """Decide whether this run is scripted, and whether the row has to be corrected.

    Returns `(config, needs_stamp)`. `needs_stamp` is True when the run *is* a demo and the
    row does not yet say so — the caller writes that back, because only the caller knows
    which row and which transaction.

    **The row records what actually ran, not what was requested.** There are two ways into
    a scripted run — the requester asked for a demo, or the deployment itself is in fake
    mode — and they mean the same thing, so they share one branch. `start.sh` exports
    `LLM_MODE=fake` for `--fake` *and* silently as a fallback when `.env` has no provider
    key, which makes a fake deployment the commonest first-run setup. A run that reached no
    provider used to record `demo = false`: its bundle named models nothing had called at a
    real-looking cost, its `.md` export skipped the demo stamp, and `verify_bundle` printed
    PASS with no warning. That is the P0 honesty class, not a cosmetic one.

    Deciding both ways in one branch is also what keeps the answer **stable across a
    resume**. `demo` selects the seeded content (docs/17 §6.1) while `llm_mode` keeps the
    run offline, so a flag that flipped False→True between a run and its resume would
    change what the run researches halfway through. Feeding this function's own output back
    in is a no-op, and a test pins that.

    Note the asymmetry: a row that says `demo` stays scripted even on a host that is not.
    A recorded demo that started calling a real provider on resume would be the same
    dishonesty in the other direction.
    """
    if not is_scripted(row_demo=row_demo, host_is_scripted=host_is_scripted):
        return base, False
    return replace(base, llm_mode="fake", demo=True), not row_demo


#: What a run's recorded prompt overrides turned out to be. Stored on the row rather than
#: inferred, for the same reason `evidence_outcome` is: "no overrides" and "overrides that
#: could not be used" are different facts about a run, and a reader cannot tell them apart
#: from an empty result.
OVERRIDES_NONE = "NONE"
OVERRIDES_APPLIED = "APPLIED"
OVERRIDES_UNUSABLE = "UNUSABLE"

#: The column's whole vocabulary, defined beside the rule that produces it so the check
#: constraint and the resolver cannot drift. `app/models/research.py` imports this rather
#: than restating the three strings; the dependency points that way because this module
#: holds no host machinery at all — see the note at the top about what it may import.
PROMPT_OVERRIDE_STATUSES = (OVERRIDES_NONE, OVERRIDES_APPLIED, OVERRIDES_UNUSABLE)


def snapshot_overrides(user: HasPreferences | None) -> tuple[dict[str, str], str]:
    """`(overrides, status)` to freeze onto a run at start. Read once, never again.

    Separate from `preference_overrides` on purpose: those five are dialled live and are
    re-read on every resume, which is existing behaviour and stays. Prompt overrides are
    not, because a report whose first half was written under one instruction and second half
    under another is exactly the incoherence the `model_routing` snapshot already prevents.
    """
    return usable_overrides(((user.preferences if user else None) or {}).get("prompt_overrides"))


def usable_overrides(raw: Any) -> tuple[dict[str, str], str]:
    """`(overrides, status)` for a stored snapshot — all of it, or none of it.

    **No partial application, deliberately.** Honouring the three well-formed roles out of
    four would produce a report written under a configuration nobody chose and nothing
    records; shipped prompts throughout is at least a state the run can name. So a single
    bad entry discards the lot and the run is marked `UNUSABLE`.

    Validated here rather than trusted from the row because this is the execution boundary.
    `UserPreferences` refuses these shapes at the API, but a snapshot can also arrive from a
    hand-edited database or a future migration, and prompt overrides sit directly on the
    protected-purpose boundary — so the runtime re-checks rather than assuming.

    Roles are checked against the canonical set, which keeps *role* validation here and
    *purpose* authorization in `prompt_composition`: two questions, two homes, so a gap in
    one cannot open the other.
    """
    from research_engine.prompt_composition import ROLES

    if not raw:
        return {}, OVERRIDES_NONE
    if not isinstance(raw, dict):
        return {}, OVERRIDES_UNUSABLE
    out: dict[str, str] = {}
    for role, text in raw.items():
        if role not in ROLES or not isinstance(text, str) or not text.strip():
            return {}, OVERRIDES_UNUSABLE
        out[role] = text
    return (out, OVERRIDES_APPLIED) if out else ({}, OVERRIDES_NONE)


@contextmanager
def chat_prompt_context(user: HasPreferences | None) -> Iterator[None]:
    """Install a user's prompt overrides for the length of one chat turn. Both hosts.

    Scoped rather than set-and-forget: a chat route runs on the request's own task, and a
    config left installed would answer whatever that event loop picked up next under someone
    else's instructions.
    """
    token = set_run_config(chat_run_config(get_run_config(), user))
    try:
        yield
    finally:
        reset_run_config(token)


def chat_run_config(base: RunConfig, user: HasPreferences | None) -> RunConfig:
    """`base` with this user's prompt overrides applied, for one chat turn.

    Chat has no run, so there is nothing to snapshot and nothing to resume: a turn reads the
    preferences as they stand. Both hosts build their chat config through this function so
    the answer cannot differ between them — the server installed no per-request config at
    all before this, and the desktop installed one that carried no preferences.
    """
    usable, status = usable_overrides(
        ((user.preferences if user else None) or {}).get("prompt_overrides")
    )
    if status != OVERRIDES_APPLIED:
        return base
    return replace(base, prompt_overrides=usable)
