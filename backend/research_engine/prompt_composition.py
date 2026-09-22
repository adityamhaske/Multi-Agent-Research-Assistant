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

**What this module does NOT do yet.** It reads no override and consumes no `RunConfig`; every
purpose resolves to its shipped constant, byte for byte. The override policy
(overridable vs protected) and the untrusted-content recomposition are later, deliberately
separate changes — moving the note out of the six constants that carry it inline *changes the
string the model sees*, and that is a behaviour change which belongs with the change that
makes the body user-authored, not with this one.
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


def role_of(purpose: str) -> str:
    """The model role a purpose runs under — the same string `get_llm()` is called with."""
    return _checked(purpose).split(".", 1)[0]


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
