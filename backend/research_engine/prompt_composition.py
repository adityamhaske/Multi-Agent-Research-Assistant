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

**The shipped path is untouched.** With no override in force — and for every protected
purpose — this returns the shipped constant *itself*, the same object, byte for byte. That
is not an optimisation: `fakes.SCENARIO_BY_PROMPT` resolves a scripted run by prompt
identity, so a copy would collapse the three scenarios that share `critic` into one.

**The note is sandwiched only around a user's body.** The six constants that carry
`UNTRUSTED_CONTENT_NOTE` interleave it, 41-88% of the way in and followed by further
instructions in four of the six. Wrapping a *shipped* prompt would change what every run sees for no benefit,
so it is not done. A user-authored body has no such framing, so it is wrapped on both
sides — before, so the model is told what to distrust before reading the instructions, and
after, because a body ending in an instruction would otherwise have the last word.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar

from research_engine import prompts
from research_engine.runconfig import get_run_config

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

#: Purposes whose shipped prompt carries the untrusted-content framing, and which therefore
#: need it restored around a replacement body.
#:
#: **Derived, never enumerated.** A prompt that gains the note and is not added to a
#: hand-written list would lose the framing the moment a user replaced it — the failure
#: would be silent, in the one place silence is least affordable. Six today; an anti-rot
#: test pins that this stays computed.
NOTE_CARRYING_PURPOSES: frozenset[str] = frozenset(
    p for p, constant in PURPOSE_CONSTANTS.items() if prompts.UNTRUSTED_CONTENT_NOTE in constant
)

#: Which purposes a **research run** actually executes, and which it does not.
#:
#: Applicability, not policy. Nothing here decides what may be overridden — that is
#: `OVERRIDABLE_PURPOSES` above and it is untouched by this partition. This answers a
#: different question, asked by the bundle producer: *did this prompt take part in the run
#: whose artifact I am assembling?* A run artifact that claimed provenance for `chat.general`
#: would be naming a prompt nothing in that run called, which is the same dishonesty class as
#: a bundle naming models that never answered.
#:
#: **An explicit partition, because neither default is safe.** Elsewhere a new purpose falls
#: to PROTECTED and that fails closed. Here it cannot: defaulting a new purpose *out* of the
#: run set silently drops provenance for a prompt that did run, and defaulting it *in* claims
#: provenance for one that did not. Both are silent and both are wrong, so an unclassified
#: purpose fails the anti-rot test instead of picking a side.
RUN_PURPOSES: frozenset[str] = frozenset(
    {
        "planner.main",
        "executor.main",
        "critic.research",
        "critic.citation_verify",
        "critic.contradiction_detector",
        "synthesizer.main",
        "synthesizer.repair",
    }
)

#: The complement, spelled out rather than derived, so the partition is checkable in both
#: directions. Chat runs against a finished report; it is not part of a run's execution.
NON_RUN_PURPOSES: frozenset[str] = frozenset({"chat.general", "chat.project"})


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
    """The effective system prompt for this purpose, override applied if one is in force.

    **The single runtime enforcement point.** A protected purpose returns before any
    override is read — not after a check, not filtered afterwards — so no reordering or
    later edit can let one through. API validation refuses purpose-shaped keys, but that is
    a separate concern: this must hold even for a `RunConfig` built by hand, or restored
    from a row that bypassed validation entirely.
    """
    p = _checked(purpose)
    shipped = PURPOSE_CONSTANTS[p]

    if p not in OVERRIDABLE_PURPOSES:
        # Protected: the override is never consulted at all. `_observed` runs *after* the
        # decision and cannot reach the config, so recording cannot weaken this ordering.
        return _observed(p, shipped, overridden=False)

    # Last-resort defence for a config assembled outside the host builders, which validate
    # all-or-nothing before a run ever starts. Anything that is not usable text — including a
    # container that is not a mapping at all — reads as "no override", which is the shipped
    # prompt, never a partially applied one. Falling back rather than raising because this
    # runs per model call inside a graph node: the honest failure is a run on shipped prompts
    # (recorded as `UNUSABLE` on the row), not a half-written report.
    stored = get_run_config().prompt_overrides
    body = stored.get(role_of(p)) if isinstance(stored, Mapping) else None
    if not isinstance(body, str) or not body.strip():
        return _observed(p, shipped, overridden=False)

    if p in NOTE_CARRYING_PURPOSES:
        note = prompts.UNTRUSTED_CONTENT_NOTE
        body = f"{note}\n\n{body}\n\n{note}"
    return _observed(p, body, overridden=True)


class PromptProvenanceConflict(RuntimeError):
    """One purpose composed two different prompts inside a single run.

    Impossible while the run's overrides stay frozen, which is why it raises rather than
    picking a winner: the recovery is to fix whatever unfroze them, not to publish one of
    two prompts as though it were the only one.
    """


#: Where `system_prompt` reports what it just composed, when anyone is listening.
#:
#: **Observation, not a second composer.** The bundle has to state the prompt a run actually
#: sent to the model, and the only moment that string exists is the one below — the config
#: that produced it is torn down when the run ends, and rebuilding it later would report
#: what *today's* code would compose, which for a protected purpose is the currently shipped
#: constant rather than the one that ran. So the composer is watched rather than replayed.
#:
#: A `ContextVar` holding a **mutable dict**: child tasks inherit a copy of the context, and
#: that copy holds the same dict, so a node running in its own task still records into the
#: caller's collection. Nothing is rebound after the run starts.
_provenance: ContextVar[dict[str, dict] | None] = ContextVar("_prompt_provenance", default=None)


def _observed(purpose: str, text: str, *, overridden: bool) -> str:
    """Record what was composed and hand it back untouched.

    Returns its argument by identity — `fakes.SCENARIO_BY_PROMPT` resolves a scripted run by
    `is`, so the shipped path must still yield the constant object itself.

    **`overridden` is the decision, not a comparison.** It comes from the branch that just
    ran, so a user whose override happens to equal the shipped text is still recorded as
    having overridden, and a protected purpose can never be recorded as overridden at all.

    **A repeat must be identical, and a conflict raises.** `executor.main` composes at two
    call sites, and one entry per purpose is only honest because `system_prompt` is pure over
    (purpose, the run's frozen overrides) — so within one recorder scope the two cannot
    differ. Silently keeping the first would make a bundle assert one of two prompts while
    the model saw both, which is the class of quiet wrongness this column exists to remove.
    Raising instead is loud in the only situation that can produce it: a code change that
    broke the frozen-config invariant, in which case no provenance is trustworthy anyway.
    """
    records = _provenance.get()
    if records is None:
        return text

    record = {
        "purpose": purpose,
        "role": role_of(purpose),
        "policy": "OVERRIDABLE" if purpose in OVERRIDABLE_PURPOSES else "PROTECTED",
        "overridden": overridden,
        "effective_prompt": text,
    }
    existing = records.get(purpose)
    if existing is not None and existing != record:
        raise PromptProvenanceConflict(
            f"{purpose} composed twice within one run and the results differ — the run's "
            "prompt overrides are supposed to be frozen for its whole life, so this means "
            "that invariant is broken and no provenance for this run can be trusted"
        )
    records[purpose] = record
    return text


@contextmanager
def recording_provenance(into: dict[str, dict] | None = None) -> Iterator[dict[str, dict]]:
    """Collect every prompt composed inside this block, keyed by purpose.

    Scoped rather than always-on: composition happens on chat turns and in tests too, and a
    process-wide accumulator would mix runs together. `into` lets a resumed run keep adding
    to what its earlier segments already recorded — a run that pauses at the design gate
    composes the planner's prompt in one invocation and the synthesizer's in the next, and
    the bundle needs both.

    Only purposes that actually executed appear. A run whose draft cited everything never
    composes `synthesizer.repair`, and the absence is the honest record — the frozen RFC asks
    for "each applicable purpose", not for all seven.
    """
    records: dict[str, dict] = {} if into is None else into
    token = _provenance.set(records)
    try:
        yield records
    finally:
        _provenance.reset(token)


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
