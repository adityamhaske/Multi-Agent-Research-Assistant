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
from typing import Any

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage


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


class _ScriptedModel(FakeMessagesListChatModel):
    """A chat model whose reply depends on which agent role invoked it.

    Role is inferred from the system prompt. `usage_metadata` is populated so the
    cost accountant has non-zero tokens to sum. Structured-output (`with_structured_output`)
    is honored by returning JSON the schema can parse.
    """

    def __init__(self) -> None:
        super().__init__(responses=[AIMessage(content="")])

    def bind_tools(self, tools, **kwargs):
        # The scripted executor signals completion by emitting a submit_evidence tool
        # call (see _reply), matching the real executor contract in graph.py.
        return self

    def _reply(self, messages: list[BaseMessage]) -> AIMessage:
        system = ""
        human = ""
        for m in messages:
            role = getattr(m, "type", "")
            if role == "system":
                system += str(m.content) + "\n"
            elif role == "human":
                human += str(m.content) + "\n"

        if "Orchestration Planner" in system:
            content = json.dumps(
                {
                    "tasks": [
                        {"id": 1, "query": "background and definitions", "rationale": "context"},
                        {"id": 2, "query": "current state and data", "rationale": "evidence"},
                    ]
                }
            )
        elif "Research Executor" in system:
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
        elif "Quality Critic" in system:
            content = json.dumps(
                {"passed": True, "confidence": 0.9, "reasons": ["two independent sources"]}
            )
        elif "citation repair pass" in system:
            # Every assertive line carries a [n] marker so the repair pass converges
            # in one round (section headers stay under the 15-char claim threshold).
            content = (
                "# Fixture Report\n\n## Summary\nDeterministic summary [1].\n\n"
                "## Findings\nA citable fact [1]. A corroborating fact [2].\n\n"
                "## Analysis\nAnalysis grounded in evidence [1][2].\n\n"
                "## Limitations\nFixture data only.\n\n"
                "## Sources\n[1] https://example.com/fixture/1\n[2] https://example.com/fixture/2\n"
            )
        elif "verify whether claims are supported" in system:
            # The citation-fidelity verifier (graph._verify_citation_fidelity) asks for one
            # YES/NO line per claim. Fixture claims all resolve, so rule YES for as many
            # claims as the request carries — keeps fake-mode drafts byte-identical.
            n_claims = len(re.findall(r"Claim \d+:", human)) or 1
            content = "\n".join(f"Claim {i}: YES" for i in range(1, n_claims + 1))
        elif "Research Synthesizer" in system:
            content = (
                "# Fixture Report\n\n## Executive Summary\nDeterministic summary [1].\n\n"
                "## Key Findings\n- A citable fact [1]\n- A corroborating fact [2]\n\n"
                "## Detailed Analysis\nAnalysis grounded in evidence [1][2].\n\n"
                "## Limitations\nFixture data only.\n\n"
                "## Sources\n[1] https://example.com/fixture/1\n[2] https://example.com/fixture/2\n"
            )
        elif "analyst answering follow-up" in system:
            content = f"Based on the report, here is a grounded answer to: {human.strip()[:80]}"
        else:
            content = "{}"

        return AIMessage(
            content=content,
            usage_metadata={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        )

    def _generate(self, messages, stop=None, run_manager=None, **kwargs: Any):
        from langchain_core.outputs import ChatGeneration, ChatResult

        return ChatResult(generations=[ChatGeneration(message=self._reply(messages))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs: Any):
        from langchain_core.outputs import ChatGeneration, ChatResult

        return ChatResult(generations=[ChatGeneration(message=self._reply(messages))])


def fake_model() -> _ScriptedModel:
    return _ScriptedModel()
