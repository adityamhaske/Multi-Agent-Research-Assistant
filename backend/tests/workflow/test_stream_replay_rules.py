"""
Replay stops at the true terminals; only the *live tail* stops at a gate.

**The defect.** A stream's stop-list answers "when may the connection close?". A graph
suspended at `PLAN_READY`/`HITL_READY` publishes nothing more until a human acts, so the
live tail closes there — correct, and why both gates are on `_TERMINAL_EVENTS`.

Applying that same list to the *backlog* says something different and wrong: "stop reading
history at the first gate". A client that reconnects **without** a `Last-Event-ID` — which
is what a fresh `EventSource` is, and a status change creates one — replays from id 0, hits
the `PLAN_READY` row the design gate left behind, and returns. Everything the run did after
the gate is never delivered, and the live tail is never reached either. Symptom: after
approving an edited plan, the activity log sometimes never shows the executor working the
edited query.

The server's V1 stream always drew this distinction (`("COMPLETED", "FAILED")` in the
replay loop, the wider list in the tail). Both V2 streams and the desktop host's V1 stream
copied the tail's list into both places. This pins all four.
"""

from __future__ import annotations

import ast
import inspect
import re


def _replay_stop_names(source: str) -> list[str]:
    """The names compared against inside every `for ... in <backlog>` loop.

    AST rather than a substring scan: the constants are also *named* in comments and in
    the tail loop, and a prose mention must not be able to satisfy this test.
    """
    tree = ast.parse(inspect.cleandoc(source) if source.startswith('"') else source)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        # A replay loop iterates a materialised backlog list of (id, payload) pairs.
        if not isinstance(node.target, ast.Tuple):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Compare) and any(isinstance(op, ast.In) for op in inner.ops):
                for comparator in inner.comparators:
                    if isinstance(comparator, ast.Name):
                        found.append(comparator.id)
    return found


def test_v2_server_stream_replays_past_the_gates():
    from app.api.v1 import v2_runs

    assert v2_runs._REPLAY_STOP_EVENTS == ("COMPLETED", "FAILED")
    assert "PLAN_READY" in v2_runs._TERMINAL_EVENTS, "the tail must still close at a gate"

    src = inspect.getsource(v2_runs.stream_run)
    assert "_REPLAY_STOP_EVENTS" in _replay_stop_names(src), (
        "the V2 replay loop must stop only at the true terminals"
    )


def test_desktop_streams_replay_past_the_gates():
    import desktop.sidecar as sidecar

    assert sidecar._REPLAY_STOP_EVENTS == ("COMPLETED", "FAILED")
    assert "PLAN_READY" in sidecar._TERMINAL_EVENTS

    src = inspect.getsource(sidecar)
    # Both of this host's streams: the V1-equivalent one and the V2 one.
    for marker, expected in (
        ("async def stream_events", "_REPLAY_STOP_EVENTS"),
        ("async def v2_stream_run", "V2_REPLAY_STOP"),
    ):
        idx = src.find(marker)
        assert idx != -1, f"{marker} not found in the sidecar"
        body = src[idx : idx + 4000]
        assert re.search(rf"in {expected}:\s*\n\s*return", body), (
            f"{marker}'s replay loop must stop only at the true terminals"
        )


def test_the_two_hosts_agree_on_the_replay_rule():
    """One rule, two homes — the trap AGENTS.md keeps naming."""
    import desktop.sidecar as sidecar
    from app.api.v1 import v2_runs

    assert sidecar._REPLAY_STOP_EVENTS == v2_runs._REPLAY_STOP_EVENTS
    assert sidecar._TERMINAL_EVENTS == v2_runs._TERMINAL_EVENTS


def test_v1_server_stream_was_already_correct_and_stays_that_way():
    """The reference implementation. If this regresses, the others followed it wrongly."""
    from app.api.v1 import research

    src = inspect.getsource(research)
    idx = src.find("async def stream_events")
    body = src[idx : idx + 4000]
    assert re.search(r'in \("COMPLETED", "FAILED"\):\s*\n\s*return', body), (
        "the V1 replay loop must stop only at the true terminals"
    )


def test_a_stream_on_a_suspended_run_still_closes_after_replay():
    """The other half of the rule — and the half that is easy to break while fixing the first.

    Removing the gates from the replay stop-list is only safe because the decision moved to
    the run's *current* status. Without that, a client reconnecting to a run parked at a
    gate would replay the backlog and then block on a channel nothing will ever write to —
    exactly what the gates were on the stop-list to prevent. Both hosts must hold both
    halves.
    """
    import desktop.sidecar as sidecar
    from app.api.v1 import v2_runs

    for gate in ("AWAITING_PLAN", "AWAITING_REVIEW"):
        assert gate in v2_runs._SUSPENDED_STATUSES, f"{gate} must end a V2 stream after replay"
    for terminal in ("COMPLETED", "FAILED", "CANCELLED"):
        assert terminal in v2_runs._SUSPENDED_STATUSES

    src = inspect.getsource(v2_runs.stream_run)
    assert re.search(r"if run\.status in _SUSPENDED_STATUSES:\s*\n\s*return", src), (
        "the V2 stream must stop before tailing when the run is suspended"
    )

    # The desktop host expresses the same rule through `already_done`.
    sidecar_src = inspect.getsource(sidecar)
    for marker in ("async def stream_events", "async def v2_stream_run"):
        idx = sidecar_src.find(marker)
        body = sidecar_src[idx : idx + 4500]
        assert re.search(r"if already_done:\s*\n\s*return", body), (
            f"{marker} must end after replay when the run is suspended"
        )
    # And both gates must be in that predicate, not just the terminals.
    v1_guard = sidecar_src[sidecar_src.find("already_done = session.status in (") :][:400]
    assert "AWAITING_PLAN" in v1_guard and "AWAITING_APPROVAL" in v1_guard
    v2_guard = sidecar_src[sidecar_src.find("already_done = run.status in (") :][:400]
    assert "AWAITING_PLAN" in v2_guard and "AWAITING_REVIEW" in v2_guard
