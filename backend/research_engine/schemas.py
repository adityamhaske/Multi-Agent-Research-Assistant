"""
Structured I/O contracts for the agent pipeline (docs/architecture/04_Agent_Design.md §2).

Every LLM boundary is validated against one of these models. Parse/validation
failure is a node failure — never a silent fallback (docs/11 §1 rule 2).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

TaskStatus = Literal["pending", "running", "passed", "failed"]


class ResearchTask(BaseModel):
    id: int
    query: str = Field(min_length=3, description="A concrete, independently searchable query")
    rationale: str = ""
    status: TaskStatus = "pending"


class PlannerOutput(BaseModel):
    tasks: list[ResearchTask]

    @field_validator("tasks")
    @classmethod
    def _bounded(cls, v: list[ResearchTask]) -> list[ResearchTask]:
        if not 2 <= len(v) <= 6:
            raise ValueError("planner must produce between 2 and 6 tasks")
        # Normalize ids to 1..n so downstream tagging is stable.
        for i, t in enumerate(v, start=1):
            t.id = i
        return v


class EvidenceChunk(BaseModel):
    task_id: int = 0
    source_url: str
    source_title: str = ""
    snippet: str = Field("", max_length=500, description="Verbatim supporting text")
    key_fact: str = Field("", description="The claim this snippet supports")
    retrieved_at: str = ""


class ExecutorOutput(BaseModel):
    task_id: int
    evidence: list[EvidenceChunk] = Field(default_factory=list)


class CriticVerdict(BaseModel):
    passed: bool
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)
    feedback_for_executor: str | None = None

    @field_validator("feedback_for_executor")
    @classmethod
    def _feedback_required_on_fail(cls, v: str | None, info) -> str | None:
        # When a verdict fails, the executor needs something actionable.
        if info.data.get("passed") is False and not (v and v.strip()):
            return "Insufficient evidence; gather more independent, well-cited sources."
        return v


class Source(BaseModel):
    """A numbered citation the UI renders (docs/05 §1 — sessions.sources).

    A single page routinely supports several distinct facts, and the executor extracts a
    separate verbatim snippet for each. Keeping only one of them — as this schema did
    until docs/12 M5 defect D3 — meant a citation chip could show a snippet that had
    nothing to do with the sentence it was attached to, since the same source is cited
    for ~8 different claims on average. That quietly broke the product's central promise:
    hover a citation, read the text that backs *this* claim.

    So `snippets` holds every distinct snippet extracted from the source. `snippet` is
    retained as the first one for backward compatibility with `sessions.sources` rows
    written before the fix and with any client reading the old shape.
    """

    index: int
    url: str
    title: str = ""
    snippet: str = ""
    snippets: list[str] = Field(default_factory=list)
