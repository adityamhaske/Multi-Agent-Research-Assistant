"""
The rules that decide what a run actually dials — shared by both hosts.

Building a `RunConfig` is host-specific: the server reads pydantic settings and a decrypted
BYOK column, the desktop reads environment plus the OS keychain, and the CLI reads `os.environ`.
Those stay three builders. What must not be three — or four, as it was — are the *rules*
applied on top of whatever a host built.

Two rules live here: which preferences a run honours, and whether a run is scripted.

Nothing here may import FastAPI, `app.config`, `app.db` or anything reaching them: the
desktop imports this module on every run. That is also why the preference rule below takes
a structural type rather than importing the `User` model — the rule is about the mapping,
not about a table.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Protocol

from research_engine.runconfig import RunConfig


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
