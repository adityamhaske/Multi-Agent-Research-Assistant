"""Content for the seeded demo session (docs/17 §6.1).

Deliberately NOT `fakes.py`. Those are the *test* fixtures: their output is
deterministic filler ("A citable fact [1]" citing "Fixture Source 1") because tests
assert on it, and it must stay that way. Pointing a stranger's first launch at them
made the product introduce itself with placeholder data — the one thing a tool whose
claim is verifiability cannot afford.

**The evidence here is real.** Both sources exist, and each `snippet` is verbatim text
fetched from the URL it is attributed to (arXiv abstracts, retrieved 2026-08-15). That
matters because the UI presents a snippet as the verbatim quote supporting a claim: an
invented snippet under a real DOI would be a fabricated citation, which is the exact
failure this product exists to make impossible. If you edit a snippet, re-fetch it —
do not paraphrase.

Every claim in `DEMO_REPORT` is supported by the snippet it cites and carries no number
absent from that snippet, so the graph's own citation-fidelity pass leaves the draft
untouched. `tests/test_demo_fixtures.py` enforces both properties.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage

from research_engine.fakes import _ScriptedModel

DEMO_QUERY = "What is retrieval-augmented generation, and when does it beat fine-tuning?"

# Verbatim abstracts, fetched from the URLs below. Kept under the 500-char EvidenceChunk
# cap (schemas.py) so they survive the executor contract unmodified.
DEMO_SOURCES: list[dict[str, Any]] = [
    {
        "index": 1,
        "url": "https://arxiv.org/abs/2005.11401",
        "title": "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
        "snippet": (
            "Large pre-trained language models have been shown to store factual knowledge "
            "in their parameters, and achieve state-of-the-art results when fine-tuned on "
            "downstream NLP tasks. However, their ability to access and precisely "
            "manipulate knowledge is still limited, and hence on knowledge-intensive "
            "tasks, their performance lags behind task-specific architectures. "
            "Additionally, providing provenance for their decisions and updating their "
            "world knowledge remain open research problems."
        ),
        "key_fact": (
            "Parametric knowledge is hard to access precisely, and provenance and updates "
            "remain open problems."
        ),
    },
    {
        "index": 2,
        "url": "https://arxiv.org/abs/2312.10997",
        "title": "Retrieval-Augmented Generation for Large Language Models: A Survey",
        "snippet": (
            "Retrieval-Augmented Generation (RAG) has emerged as a promising solution by "
            "incorporating knowledge from external databases. This enhances the accuracy "
            "and credibility of the generation, particularly for knowledge-intensive "
            "tasks, and allows for continuous knowledge updates and integration of "
            "domain-specific information."
        ),
        "key_fact": (
            "External-database knowledge improves accuracy and credibility and allows "
            "continuous updates."
        ),
    },
]

# No claim carries a digit: the graph's `_numbers_grounded` check requires every
# number-like token to appear verbatim in a cited snippet, so a stray year would strip
# the markers off an otherwise supported sentence. Dates belong in the source titles.
DEMO_REPORT = """# Retrieval-augmented generation versus fine-tuning

## Summary
Retrieval-augmented generation and fine-tuning address different problems: fine-tuning \
adapts a model's parameters, while retrieval supplies knowledge the model can cite at \
answer time [1][2].

## Findings
Large pre-trained language models store factual knowledge in their parameters and \
achieve state-of-the-art results when fine-tuned on downstream NLP tasks [1].
Their ability to access and precisely manipulate that knowledge is still limited, and on \
knowledge-intensive tasks their performance lags behind task-specific architectures [1].
Providing provenance for a model's decisions and updating its world knowledge remain \
open research problems [1].
Incorporating knowledge from external databases enhances the accuracy and credibility of \
the generation, particularly for knowledge-intensive tasks [2].
Because the knowledge sits outside the parameters, retrieval allows for continuous \
knowledge updates and integration of domain-specific information [2].

## Analysis
Retrieval is the stronger choice where knowledge changes or must be attributable, since \
it updates continuously and carries provenance that parametric memory does not [1][2].
Fine-tuning remains the mechanism for adapting a model to a downstream task rather than \
for teaching it facts it must later be able to cite [1].

## Limitations
This is a demonstration run on scripted models over two sources captured in advance. A \
real run searches the live web, may surface contradicting sources, and will not \
reproduce this report.

## Sources
[1] https://arxiv.org/abs/2005.11401
[2] https://arxiv.org/abs/2312.10997
"""


def demo_search(query: str, max_results: int) -> list[dict]:
    """Search results for the demo: the real sources, never invented ones."""
    return [
        {"title": s["title"], "url": s["url"], "snippet": s["snippet"]}
        for s in DEMO_SOURCES[:max_results]
    ]


def demo_read_webpage(url: str) -> dict:
    """Page read for the demo. Returns the stored verbatim text for a known source and
    fails closed for anything else — a demo must not invent a page body for a URL whose
    content nobody captured."""
    for source in DEMO_SOURCES:
        if source["url"] == url:
            return {
                "url": url,
                "title": source["title"],
                "text": source["snippet"],
                "error": None,
            }
    return {"url": url, "title": "", "text": "", "error": "not part of the demo corpus"}


class _DemoModel(_ScriptedModel):
    """The scripted model with demo content in place of test filler.

    Subclasses rather than copies `_ScriptedModel`: the roles that are pure contract
    plumbing (critic, contradiction detector, citation verifier) are inherited, so a
    change to the graph's node contract updates both at once. Only the roles a user
    actually reads are overridden.
    """

    def _reply(self, messages: list[BaseMessage]) -> AIMessage:
        system = "\n".join(str(m.content) for m in messages if getattr(m, "type", "") == "system")

        if "Orchestration Planner" in system:
            return self._usage(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": 1,
                                "query": "what retrieval-augmented generation is",
                                "rationale": "define the mechanism before comparing it",
                            },
                            {
                                "id": 2,
                                "query": "when retrieval beats fine-tuning",
                                "rationale": "the comparison the question actually asks for",
                            },
                        ]
                    }
                )
            )

        if "Research Executor" in system:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "submit_evidence",
                        "args": {
                            "evidence": [
                                {
                                    "task_id": 1,
                                    "source_url": s["url"],
                                    "source_title": s["title"],
                                    "snippet": s["snippet"],
                                    "key_fact": s["key_fact"],
                                    "retrieved_at": "2026-08-15T00:00:00Z",
                                }
                                for s in DEMO_SOURCES
                            ]
                        },
                        "id": "demo-submit-evidence-1",
                    }
                ],
                usage_metadata={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
            )

        if "Research Synthesizer" in system or "citation repair pass" in system:
            return self._usage(DEMO_REPORT)

        return super()._reply(messages)

    @staticmethod
    def _usage(content: str) -> AIMessage:
        return AIMessage(
            content=content,
            usage_metadata={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        )


def demo_model() -> _DemoModel:
    return _DemoModel()
