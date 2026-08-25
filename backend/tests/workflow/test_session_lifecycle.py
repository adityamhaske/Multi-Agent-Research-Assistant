"""
Archive / delete / per-run model routing (docs/05 §3).

Unit-level checks of the rules that must not regress. The live end-to-end path is
exercised against real Postgres in CI.
"""

import pytest
from pydantic import ValidationError

from app.schemas.research import ResearchStartRequest, SessionSummary


def test_start_request_accepts_no_routing():
    """Omitting model_routing means "use my saved settings" — not an error."""
    req = ResearchStartRequest(query="a" * 20, depth="fast")
    assert req.model_routing is None


def test_start_request_carries_per_run_routing():
    routing = {
        "planner": "ollama:qwen2.5",
        "executor": "ollama:qwen2.5",
        "critic": "ollama:qwen2.5",
        "synthesizer": "ollama:qwen2.5",
        "chat": "ollama:qwen2.5",
    }
    req = ResearchStartRequest(query="a" * 20, depth="balanced", model_routing=routing)
    assert req.model_routing == routing


def test_start_request_still_validates_query_length():
    with pytest.raises(ValidationError):
        ResearchStartRequest(query="too short", depth="fast")


def test_summary_exposes_archived_at():
    """The client distinguishes archived rows by this field alone."""
    assert "archived_at" in SessionSummary.model_fields


def test_archived_at_defaults_to_none():
    from datetime import UTC, datetime

    summary = SessionSummary(
        id="3f2504e0-4f89-11d3-9a0c-0305e82c3301",
        project_id="6ba7b810-9dad-11d1-80b4-00c04fd430c8",
        status="COMPLETED",
        prompt="q",
        research_depth="fast",
        total_cost_usd=0.0,
        total_tokens_input=0,
        total_tokens_output=0,
        created_at=datetime.now(UTC),
    )
    assert summary.archived_at is None
