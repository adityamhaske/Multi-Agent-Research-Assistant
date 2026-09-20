"""Fake mode selects its script from the caller's role, not from prompt prose.

`_ScriptedModel` used to infer which agent was calling by searching the system message for
hand-typed fragments — `"Orchestration Planner"`, `"Quality Critic"`, and six more — with an
`else` that returned `"{}"`. Nothing tied those fragments to the prompts they were quoting,
so rewording a prompt's opening line silently routed every scripted test to the `else`
branch: not a failure naming its cause, but a graph that ran to completion on empty
structured output.

That is a live hazard today and a blocking one for the V3 agent platform, where a user may
supply the system prompt for any role. A scripted run must stay deterministic when the
prose changes underneath it.

These tests pin the mechanism rather than the prose: the same role must produce the same
script whatever the prompt says, and an unscriptable request must raise instead of
returning something that parses.
"""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from research_engine import prompts
from research_engine.demo_fixtures import demo_model
from research_engine.fakes import ScriptedScenario, fake_model


def _reply(model, system: str, human: str = "q"):
    return model._reply([SystemMessage(content=system), HumanMessage(content=human)])


# ── The mechanism ─────────────────────────────────────────────────────────────────


def test_the_role_is_carried_into_the_scripted_model_not_re_derived():
    """The root cause: `get_llm(role)` knew the role and discarded it."""
    assert fake_model("planner").role == "planner"
    assert demo_model("synthesizer").role == "synthesizer"


@pytest.mark.parametrize(
    ("role", "scenario"),
    [
        ("planner", ScriptedScenario.PLANNER),
        ("executor", ScriptedScenario.EXECUTOR),
        ("critic", ScriptedScenario.CRITIC),
        ("synthesizer", ScriptedScenario.SYNTHESIZER),
        ("chat", ScriptedScenario.CHAT),
    ],
)
def test_every_routed_role_has_a_script_without_consulting_any_prompt(role, scenario):
    """`runconfig.ROLES` is the closed set the product routes; each must be scriptable
    from the role alone, because a custom AgentSpec prompt carries no recognisable prose."""
    assert fake_model(role).scenario_for("a completely unrecognisable system prompt") is scenario


def test_a_reworded_prompt_does_not_change_what_the_planner_returns():
    """The regression. Rewording the opening line used to route to `else` and return `{}`."""
    model = fake_model("planner")
    canonical = _reply(model, prompts.PLANNER_PROMPT_V2)
    reworded = _reply(model, "You are the Planner. Decompose the question into subtopics.")

    assert canonical.content == reworded.content
    assert json.loads(reworded.content)["tasks"], "a reworded planner prompt returned no tasks"


def test_a_reworded_prompt_does_not_change_what_the_synthesizer_returns():
    model = fake_model("synthesizer")
    canonical = _reply(model, prompts.SYNTHESIZER_PROMPT_V2)
    reworded = _reply(model, "Write the report from the evidence provided.")

    assert canonical.content == reworded.content
    assert "[1]" in reworded.content, "a reworded synthesizer prompt produced an uncited draft"


def test_an_unscriptable_role_raises_instead_of_returning_something_that_parses():
    """`"{}"` is the failure this file exists to prevent: it parses, so the graph runs on
    empty structured output and fails somewhere else entirely."""
    with pytest.raises(ValueError, match="no scripted behaviour"):
        _reply(fake_model("nonexistent-role"), "anything")


# ── The scenarios that share a role ───────────────────────────────────────────────
#
# Three scenarios route through `critic` and two through `synthesizer`, so the role alone
# cannot separate them. The prompt *constant* does — and keying on the constant rather than
# on a fragment of its prose is what makes rewording safe.


@pytest.mark.parametrize(
    ("role", "prompt", "scenario"),
    [
        ("critic", prompts.CRITIC_PROMPT_V2, ScriptedScenario.CRITIC),
        (
            "critic",
            prompts.CONTRADICTION_DETECTOR_PROMPT,
            ScriptedScenario.CONTRADICTION_DETECTOR,
        ),
        ("critic", prompts.CITATION_VERIFY_PROMPT, ScriptedScenario.CITATION_VERIFY),
        ("synthesizer", prompts.SYNTHESIZER_PROMPT_V2, ScriptedScenario.SYNTHESIZER),
        ("synthesizer", prompts.SYNTHESIZER_REPAIR_PROMPT, ScriptedScenario.SYNTHESIZER_REPAIR),
        ("chat", prompts.CHAT_PROMPT, ScriptedScenario.CHAT),
        ("chat", prompts.PROJECT_CHAT_PROMPT, ScriptedScenario.CHAT),
    ],
)
def test_a_shared_role_is_separated_by_the_prompt_constant(role, prompt, scenario):
    assert fake_model(role).scenario_for(prompt) is scenario


def test_the_repair_prompt_is_not_mistaken_for_the_synthesis_prompt():
    """`SYNTHESIZER_REPAIR_PROMPT` opens "You are the Research Synthesizer performing a
    citation repair pass", so the old ladder depended on branch order to tell them apart.
    Keying on the whole constant removes the ordering hazard — this asserts it stayed
    removed."""
    model = fake_model("synthesizer")
    assert model.scenario_for(prompts.SYNTHESIZER_REPAIR_PROMPT) is (
        ScriptedScenario.SYNTHESIZER_REPAIR
    )
    assert model.scenario_for(prompts.SYNTHESIZER_PROMPT_V2) is ScriptedScenario.SYNTHESIZER


def test_no_registered_prompt_contains_another():
    """The table resolves by containment, so one prompt being a substring of another would
    make resolution depend on iteration order — the ordering hazard, reintroduced."""
    from research_engine.fakes import SCENARIO_BY_PROMPT

    for a in SCENARIO_BY_PROMPT:
        for b in SCENARIO_BY_PROMPT:
            if a is not b:
                assert a not in b, "one registered prompt contains another; resolution is ambiguous"


def test_every_registered_prompt_is_a_real_prompt_constant():
    """Anti-rot: a table entry that no longer matches `prompts.py` is a mapping that has
    silently stopped applying — the class of failure this whole file exists for."""
    from research_engine.fakes import SCENARIO_BY_PROMPT

    live = {
        v
        for k, v in vars(prompts).items()
        if k.isupper() and isinstance(v, str) and not k.startswith("_")
    }
    for registered in SCENARIO_BY_PROMPT:
        assert registered in live, "a registered prompt is no longer defined in prompts.py"
