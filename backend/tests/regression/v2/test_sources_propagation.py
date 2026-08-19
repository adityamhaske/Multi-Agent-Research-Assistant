# Regression coverage for the original V2 release blocker:
# sources were present in LangGraph state but were lost while constructing
# RunOutcome, causing downstream evidence persistence to silently produce
# an empty evidence graph.

from research_engine.runner import _outcome


def test_outcome_preserves_sources_from_graph_state():
    mock_sources = [{"url": "https://example.com/a"}]
    state = {"draft_report": "d", "sources": mock_sources}
    outcome = _outcome({}, state)
    assert outcome.sources == mock_sources, "RunOutcome must preserve sources from LangGraph state"
