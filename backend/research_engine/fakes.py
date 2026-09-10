"""
Deterministic fakes for LLM_MODE=fake (docs/08 §2).

These let the whole pipeline run with no network, no API keys, and predictable
output so the golden E2E and pipeline tests are fast and free. The scripted chat
model inspects the system prompt to decide which node is calling and returns a
schema-valid response for that node.
"""

from __future__ import annotations

import json
import re
from enum import StrEnum
from typing import Any

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage

from research_engine import prompts


def fake_search(query: str, max_results: int) -> list[dict]:
    return [
        {
            "title": f"Fixture source {i} for {query[:40]}",
            "url": f"https://example.com/{re.sub(r'[^a-z0-9]+', '-', query.lower())[:30]}/{i}",
            "snippet": f"Fixture snippet {i}: authoritative-sounding fact about {query[:40]}.",
        }
        for i in range(1, max_results + 1)
    ]


def fake_read_webpage(url: str) -> dict:
    return {
        "url": url,
        "title": f"Fixture page at {url}",
        "text": f"Fixture body for {url}. Contains a citable fact and figures like 42%.",
        "error": None,
    }


class ScriptedScenario(StrEnum):
    """What a scripted call is standing in for.

    Named separately from `runconfig.ROLES` because the two are not the same set: three
    scenarios route through the `critic` role (grading, contradiction detection, citation
    verification) and two through `synthesizer` (drafting, citation repair). Collapsing
    them would make the fake model answer the wrong contract for two of every five calls.
    """

    PLANNER = "planner"
    EXECUTOR = "executor"
    CRITIC = "critic"
    CONTRADICTION_DETECTOR = "contradiction_detector"
    CITATION_VERIFY = "citation_verify"
    SYNTHESIZER = "synthesizer"
    SYNTHESIZER_REPAIR = "synthesizer_repair"
    CHAT = "chat"


#: The prompt a call carries, when it is one of ours. Keyed on the **prompt constants
#: themselves** rather than on fragments of their prose: rewording a prompt moves its key
#: with it, where a hand-typed `"Orchestration Planner"` silently stopped matching. This is
#: what separates the scenarios that share a role.
SCENARIO_BY_PROMPT: dict[str, ScriptedScenario] = {
    prompts.PLANNER_PROMPT_V2: ScriptedScenario.PLANNER,
    prompts.EXECUTOR_PROMPT: ScriptedScenario.EXECUTOR,
    prompts.CRITIC_PROMPT_V2: ScriptedScenario.CRITIC,
    prompts.CONTRADICTION_DETECTOR_PROMPT: ScriptedScenario.CONTRADICTION_DETECTOR,
    prompts.CITATION_VERIFY_PROMPT: ScriptedScenario.CITATION_VERIFY,
    prompts.SYNTHESIZER_PROMPT_V2: ScriptedScenario.SYNTHESIZER,
    prompts.SYNTHESIZER_REPAIR_PROMPT: ScriptedScenario.SYNTHESIZER_REPAIR,
    prompts.CHAT_PROMPT: ScriptedScenario.CHAT,
    prompts.PROJECT_CHAT_PROMPT: ScriptedScenario.CHAT,
}

#: The fallback, and the reason this indirection exists at all: under a configurable agent
#: platform the system prompt is the user's, so it matches nothing above. The role is what
#: the caller stated and cannot be reworded away.
SCENARIO_BY_ROLE: dict[str, ScriptedScenario] = {
    "planner": ScriptedScenario.PLANNER,
    "executor": ScriptedScenario.EXECUTOR,
    "critic": ScriptedScenario.CRITIC,
    "synthesizer": ScriptedScenario.SYNTHESIZER,
    "chat": ScriptedScenario.CHAT,
}


class _ScriptedModel(FakeMessagesListChatModel):
    """A chat model whose reply depends on which agent role invoked it.

    The role is **passed in**, not inferred: `get_llm(role)` already knows it, and the
    version of this class that re-derived it by searching the system prompt for
    `"Orchestration Planner"` returned `"{}"` the moment that line was reworded — a graph
    that ran to completion on empty structured output rather than a failure naming its
    cause. `usage_metadata` is populated so the cost accountant has non-zero tokens to sum.
    Structured output (`with_structured_output`) is honored by returning parseable JSON.
    """

    #: Required, with no default. A default would restore the implicit path this class was
    #: changed to remove — a caller that forgets to say which agent it is would silently
    #: get someone else's script.
    role: str

    def __init__(self, role: str) -> None:
        super().__init__(responses=[AIMessage(content="")], role=role)

    def scenario_for(self, system: str) -> ScriptedScenario:
        """Which script answers this call: the prompt if we recognise it, else the role.

        Raises rather than falling back to `"{}"`. An unscriptable request must fail where
        it happens; empty structured output parses, so it surfaces several nodes later as
        something unrelated.
        """
        for prompt, scenario in SCENARIO_BY_PROMPT.items():
            if prompt in system:
                return scenario
        try:
            return SCENARIO_BY_ROLE[self.role]
        except KeyError:
            raise ValueError(
                f"no scripted behaviour for role {self.role!r}: add it to SCENARIO_BY_ROLE "
                "or route the call through a role that has one"
            ) from None

    def bind_tools(self, tools, **kwargs):
        # The scripted executor signals completion by emitting a submit_evidence tool
        # call (see _reply), matching the real executor contract in graph.py.
        return self

    def _reply(self, messages: list[BaseMessage]) -> AIMessage:
        system = ""
        human = ""
        for m in messages:
            kind = getattr(m, "type", "")
            if kind == "system":
                system += str(m.content) + "\n"
            elif kind == "human":
                human += str(m.content) + "\n"

        scenario = self.scenario_for(system)

        if scenario is ScriptedScenario.PLANNER:
            content = json.dumps(
                {
                    "tasks": [
                        {"id": 1, "query": "background and definitions", "rationale": "context"},
                        {"id": 2, "query": "current state and data", "rationale": "evidence"},
                    ]
                }
            )
        elif scenario is ScriptedScenario.EXECUTOR:
            # Evidence is only accepted through the submit_evidence tool call
            # (docs/12 M7, commit 6ea7f21), so the scripted executor speaks that contract.
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "submit_evidence",
                        "args": {
                            "evidence": [
                                {
                                    "task_id": 1,
                                    "source_url": "https://example.com/fixture/1",
                                    "source_title": "Fixture Source 1",
                                    "snippet": "Fixture snippet supporting the claim.",
                                    "key_fact": "A citable fact.",
                                    "retrieved_at": "2026-01-01T00:00:00Z",
                                },
                                {
                                    "task_id": 1,
                                    "source_url": "https://example.com/fixture/2",
                                    "source_title": "Fixture Source 2",
                                    "snippet": "A second independent snippet.",
                                    "key_fact": "A corroborating fact.",
                                    "retrieved_at": "2026-01-01T00:00:00Z",
                                },
                            ]
                        },
                        "id": "fake-submit-evidence-1",
                    }
                ],
                usage_metadata={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
            )
        elif scenario is ScriptedScenario.CRITIC:
            content = json.dumps(
                {"passed": True, "confidence": 0.9, "reasons": ["two independent sources"]}
            )
        elif scenario is ScriptedScenario.CONTRADICTION_DETECTOR:
            content = self._contradiction_reply(human)
        elif scenario is ScriptedScenario.SYNTHESIZER_REPAIR:
            # Every assertive line carries a [n] marker so the repair pass converges
            # in one round (section headers stay under the 15-char claim threshold).
            content = (
                "# Fixture Report\n\n## Summary\nDeterministic summary [1].\n\n"
                "## Findings\nA citable fact [1]. A corroborating fact [2].\n\n"
                "## Analysis\nAnalysis grounded in evidence [1][2].\n\n"
                "## Limitations\nFixture data only.\n\n"
                "## Sources\n[1] https://example.com/fixture/1\n[2] https://example.com/fixture/2\n"
            )
        elif scenario is ScriptedScenario.CITATION_VERIFY:
            # The citation-fidelity verifier (graph._verify_citation_fidelity) asks for one
            # YES/NO line per claim. Fixture claims all resolve, so rule YES for as many
            # claims as the request carries — keeps fake-mode drafts byte-identical.
            n_claims = len(re.findall(r"Claim \d+:", human)) or 1
            content = "\n".join(f"Claim {i}: YES" for i in range(1, n_claims + 1))
        elif scenario is ScriptedScenario.SYNTHESIZER:
            content = (
                "# Fixture Report\n\n## Executive Summary\nDeterministic summary [1].\n\n"
                "## Key Findings\n- A citable fact [1]\n- A corroborating fact [2]\n\n"
                "## Detailed Analysis\nAnalysis grounded in evidence [1][2].\n\n"
                "## Limitations\nFixture data only.\n\n"
                "## Sources\n[1] https://example.com/fixture/1\n[2] https://example.com/fixture/2\n"
            )
        else:  # ScriptedScenario.CHAT
            content = f"Based on the report, here is a grounded answer to: {human.strip()[:80]}"

        return AIMessage(
            content=content,
            usage_metadata={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        )

    @staticmethod
    def _contradiction_reply(human: str) -> str:
        """Scripted contradiction detector (docs/12 M11).

        Default: no conflicts — the fixture evidence is consistent, and keeping fake-mode
        reports contradiction-free keeps the golden outputs byte-identical. A test that
        wants the surfaced-conflict path plants the CONTRADICTION-FIXTURE sentinel in the
        evidence text; the reply then pairs the first two sources the detector was shown,
        quoting their actual snippets, so the validated pairs survive the graph's URL
        check and the report block renders for real.
        """
        if "CONTRADICTION-FIXTURE" not in human:
            return json.dumps({"pairs": []})
        # One block per source, exactly as contradictions.build_detector_input shapes it.
        blocks = re.findall(
            r"Source: (\S+)\n<untrusted_web_content>\n(.*?)\n</untrusted_web_content>",
            human,
            re.S,
        )
        seen: dict[str, str] = {}
        for url, body in blocks:
            if url not in seen:
                quoted = re.findall(r'- "([^"]*)"', body)
                seen[url] = quoted[0] if quoted else ""
        distinct = [u for u in seen if seen[u]]
        if len(distinct) < 2:
            return json.dumps({"pairs": []})
        a, b = distinct[0], distinct[1]
        return json.dumps(
            {
                "pairs": [
                    {
                        "claim_a": "the measured output was 42 units",
                        "snippet_a": seen[a],
                        "source_a": a,
                        "claim_b": "the measured output was 17 units",
                        "snippet_b": seen[b],
                        "source_b": b,
                        "nature": "The two sources report incompatible values for the same measurement.",
                    }
                ]
            }
        )

    def _generate(self, messages, stop=None, run_manager=None, **kwargs: Any):
        from langchain_core.outputs import ChatGeneration, ChatResult

        return ChatResult(generations=[ChatGeneration(message=self._reply(messages))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs: Any):
        from langchain_core.outputs import ChatGeneration, ChatResult

        message = await self._reply_async(messages)
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _reply_async(self, messages: list[BaseMessage]) -> AIMessage:
        """Async-first reply: only the corpus-mode executor needs an await."""
        from research_engine.runconfig import get_run_config

        system = "\n".join(str(m.content) for m in messages if getattr(m, "type", "") == "system")
        if "Research Executor" in system and get_run_config().corpus_mode:
            return await self._corpus_evidence(messages)
        return self._reply(messages)

    async def _corpus_evidence(self, messages: list[BaseMessage]) -> AIMessage:
        """Corpus-mode executor: search, then submit exactly what came back.

        The real executor's contract in one line — and it keeps a fake corpus run
        HONEST: the submitted evidence carries real `corpus://` locations from the
        installed store, so the synthesized source list's citations resolve to exact
        document positions (docs/12 M10 DoD). Fixture URLs would prove nothing here.
        """
        from research_engine.retrievers import search

        task_id, query = 1, ""
        for m in messages:
            if getattr(m, "type", "") == "human":
                match = re.match(r"Task (\d+): (.+)", str(m.content).strip())
                if match:
                    task_id, query = int(match.group(1)), match.group(2)
        try:
            results = await search(query or "corpus", max_results=2)
        except Exception:  # noqa: BLE001 — fail closed: empty evidence, not fake URLs
            results = []
        evidence = [
            {
                "task_id": task_id,
                "source_url": r["url"],
                "source_title": r["title"],
                # EvidenceChunk caps snippets at 500 chars (schemas.py).
                "snippet": r["snippet"][:480],
                "key_fact": r["snippet"][:80],
                "retrieved_at": "2026-01-01T00:00:00Z",
            }
            for r in results
        ]
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "submit_evidence",
                    "args": {"evidence": evidence},
                    "id": "fake-submit-evidence-corpus",
                }
            ],
            usage_metadata={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        )


def fake_model(role: str) -> _ScriptedModel:
    return _ScriptedModel(role)
