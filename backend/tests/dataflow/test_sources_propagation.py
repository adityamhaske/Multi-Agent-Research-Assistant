"""
`RunOutcome` must carry the graph's sources out of **every** status branch.

The V2 release blocker this guards was a completed report rendering `0 claims,
0 evidence, 0 sources`. Sources are the root of that chain: `v2_execution.persist_outcome`
numbers `Source` rows from `outcome.sources`, and evidence and claims hang off them. Lose
sources at this boundary and the whole provenance graph reads empty while the run reports
success — the exact inversion this project exists to refuse.

**On the history, stated plainly.** The commit pair that introduced this file
(`980c020` "propagate sources from graph state to outcome", then `82463e2` "remove
redundant sources keyword arg") has an *empty* net diff against `runner.py`:
`git diff 980c020^ 82463e2 -- backend/research_engine/runner.py` returns nothing, and
`"sources": state.get("sources") or []` was already in `totals` before either landed. The
first commit added a duplicate keyword that could only ever raise `TypeError`; the second
took it back out. So this line was never the defect, and a test asserting only that it
works would pass identically on every revision in the repository's history — which is the
decorative-test failure mode `AGENTS.md` warns about, one level up from mocking.

**What actually can break, and is what this file pins.** `RunOutcome.sources` is
`field(default_factory=list)`, so a branch that stops spreading `**totals` does not raise —
it silently yields `[]`. There are four such branches, they are constructed independently,
and only one of them was covered. `awaiting_approval` is the branch a V2 run takes on its
way to the human gate, so dropping `**totals` there would persist zero sources for exactly
the runs the product is about, while a `completed`-only test stayed green.

Hence: every branch, one case each, asserted on the same non-empty input.
"""

from __future__ import annotations

import pytest

from research_engine.runner import _outcome

SOURCES = [
    {"url": "https://example.invalid/a", "title": "A", "n": 1},
    {"url": "https://example.invalid/b", "title": "B", "n": 2},
]


class _Interrupt:
    """Stands in for LangGraph's interrupt object, which exposes `.value`.

    A real `Interrupt` carries scheduling internals `_outcome` never reads; the payload is
    the entire contract between the graph and this function.
    """

    def __init__(self, value: dict) -> None:
        self.value = value


#: (case, result, state) covering each branch `_outcome` can return through. The state
#: always carries the same sources, so the only thing under test is whether the branch
#: propagates them.
BRANCHES = [
    ("awaiting_plan", {"__interrupt__": [_Interrupt({"type": "PLAN_READY", "tasks": []})]}, {}),
    ("awaiting_approval", {"__interrupt__": [_Interrupt({"type": "HITL_READY"})]}, {}),
    ("failed", {}, {"error": "provider quota exhausted"}),
    ("completed", {}, {"draft_report": "d", "final_report": "f"}),
]


@pytest.mark.parametrize(("expected_status", "result", "extra_state"), BRANCHES)
def test_every_outcome_branch_preserves_sources(expected_status, result, extra_state):
    outcome = _outcome(result, {"sources": SOURCES, **extra_state})

    assert outcome.status == expected_status, "the case no longer reaches the branch it names"
    assert outcome.sources == SOURCES, (
        f"the '{expected_status}' branch dropped the graph's sources. Because "
        "RunOutcome.sources defaults to an empty list this fails silently: V2 persists no "
        "Source rows, and the report renders with no evidence and no claims while "
        "reporting success."
    )


def test_absent_sources_are_an_empty_list_rather_than_none():
    """Downstream iterates `outcome.sources` directly, so `None` would be a TypeError.

    A graph that failed before its first search legitimately has no `sources` key at all;
    that is empty, not missing, and `persist_outcome` should record zero sources rather
    than crash on the way to writing the failure.
    """
    outcome = _outcome({}, {"error": "died before searching"})

    assert outcome.sources == []
    assert outcome.status == "failed"
