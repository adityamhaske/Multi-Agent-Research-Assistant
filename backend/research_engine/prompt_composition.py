"""
One home for "which system prompt does this call use" (`internal/rfcs/V3.0-scope-freeze.md` §17).

**Why this module exists.** Nine shipped prompts are selected at eight call sites in
`graph.py` and four more outside the engine, and five agent *roles* fan out across them —
three prompts resolve through the role literal `"critic"` alone. V3 lets a user replace the
prompt for a role, which means something has to decide *which* of a role's prompts an
override may reach. That decision needs one home, and this is it.

**Why here and nowhere else.** `graph.py` is engine code and may not import `app` or `evals`
(`tests/task/test_engine_boundary.py`), while the chat call sites live in `app/`, `desktop/`
and `evals/`. `research_engine/` is the only package all five can import, so the seam has to
sit inside it. `app/services/run_config.py` — where the *preference* contract lives — is
disqualified for exactly that reason.

**Why `prompts.py` stays a pure constants module.** `fakes.SCENARIO_BY_PROMPT` is keyed on
the prompt constant *objects*, so a scripted run finds its script by identity. Keeping the
constants inert preserves that, and `system_prompt()` below returns the same object rather
than a copy — a fake run resolves exactly as it did before this module existed.

**Override eligibility is a property of the purpose, never of the role.** Three purposes run
under `critic` and only one of them may be replaced, so a role is not enough information to
decide anything. `is_overridable()` therefore takes a purpose and never consults `role_of()`;
a test asserts that structurally, because the moment eligibility can be computed from a role
the citation verifier becomes reachable from the `critic` editor.

**What this module does NOT do yet.** It reads no override and consumes no `RunConfig`; every
purpose resolves to its shipped constant, byte for byte. `is_overridable()` is declared and
tested but nothing calls it — consuming an override is a later change, and so is the
untrusted-content recomposition: moving the note out of the six constants that carry it
inline *changes the string the model sees*, which belongs with the change that makes the body
user-authored, not with this one.
"""

from __future__ import annotations

from collections.abc import Mapping

from research_engine import prompts

#: Every shipped prompt, keyed by the purpose it serves. The key is `<role>.<purpose>`, so
#: the role a purpose belongs to is readable from the key and cannot drift from it.
#:
#: **Nine purposes, five roles.** `critic` owns three and `synthesizer` and `chat` two each —
#: which is the entire reason a purpose vocabulary exists rather than a role-keyed lookup.
PURPOSE_CONSTANTS: Mapping[str, str] = {
    "planner.main": prompts.PLANNER_PROMPT_V2,
    "executor.main": prompts.EXECUTOR_PROMPT,
    "critic.research": prompts.CRITIC_PROMPT_V2,
    "critic.citation_verify": prompts.CITATION_VERIFY_PROMPT,
    "critic.contradiction_detector": prompts.CONTRADICTION_DETECTOR_PROMPT,
    "synthesizer.main": prompts.SYNTHESIZER_PROMPT_V2,
    "synthesizer.repair": prompts.SYNTHESIZER_REPAIR_PROMPT,
    "chat.general": prompts.CHAT_PROMPT,
    "chat.project": prompts.PROJECT_CHAT_PROMPT,
}

#: The five model roles, derived from the purpose keys rather than restated, so a purpose
#: added under a sixth role is visible here immediately instead of silently ignored.
ROLES: tuple[str, ...] = tuple(dict.fromkeys(p.split(".", 1)[0] for p in PURPOSE_CONSTANTS))

#: The purposes a user may replace. An explicit allowlist of exact purpose strings, and the
#: only way anything becomes overridable.
#:
#: **Protection is the default, and that is load-bearing.** `PROTECTED_PURPOSES` below is the
#: *complement* of this set rather than a second hand-written list, so a purpose added to
#: `PURPOSE_CONSTANTS` and forgotten here is protected rather than exposed. Two lists kept in
#: step by discipline would eventually disagree, and the direction they disagreed in would be
#: the unsafe one.
OVERRIDABLE_PURPOSES: frozenset[str] = frozenset(
    {
        "planner.main",
        "executor.main",
        "critic.research",
        "synthesizer.main",
        "chat.general",
    }
)

#: Everything else. Derived, never enumerated — see above.
#:
#: Why each of these is not a user's to rewrite:
#:
#: * `critic.citation_verify` decides whether a citation is supported, which drives the ⚠
#:   chip and `citation_resolution_rate`. A user who can rewrite it grades their own work.
#: * `critic.contradiction_detector` can be told to find no conflicts.
#: * `synthesizer.repair` rewrites citations on a draft, so an override could make fabricated
#:   citations present as repaired ones — the failure the citation contract exists to prevent.
#: * `chat.project` carries a refusal line whose absence is how a grounded assistant starts
#:   answering from its own knowledge instead of saying "not in here".
PROTECTED_PURPOSES: frozenset[str] = frozenset(PURPOSE_CONSTANTS) - OVERRIDABLE_PURPOSES


def role_of(purpose: str) -> str:
    """The model role a purpose runs under — the same string `get_llm()` is called with."""
    return _checked(purpose).split(".", 1)[0]


def is_overridable(purpose: str) -> bool:
    """Whether a user's replacement text may be used for this purpose.

    Takes a **purpose**, and deliberately has no role-shaped counterpart. `critic` owns
    `critic.research` (overridable), `critic.citation_verify` and
    `critic.contradiction_detector` (both protected), so any answer computed from the role
    alone would have to be wrong for two of the three. Unknown purposes raise rather than
    returning `False`, because a typo that silently reads as "protected" hides the typo.
    """
    return _checked(purpose) in OVERRIDABLE_PURPOSES


def system_prompt(purpose: str) -> str:
    """The system prompt for this purpose.

    Returns the shipped constant itself, not a copy: `fakes.SCENARIO_BY_PROMPT` resolves a
    scripted run by object identity, and a copy would fall back to the role and lose the
    distinction between the three scenarios that share `critic`.
    """
    return PURPOSE_CONSTANTS[_checked(purpose)]


def _checked(purpose: str) -> str:
    """Fail loudly on an unknown purpose rather than resolving to something plausible.

    A typo here would otherwise surface as a graph that ran to completion on the wrong
    instructions, which is the failure mode `fakes` was rewritten to remove.
    """
    if purpose not in PURPOSE_CONSTANTS:
        raise KeyError(
            f"unknown prompt purpose {purpose!r}; known purposes: "
            f"{', '.join(sorted(PURPOSE_CONSTANTS))}"
        )
    return purpose
