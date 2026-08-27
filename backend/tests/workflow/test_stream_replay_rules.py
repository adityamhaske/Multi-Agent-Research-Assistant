"""
All four streams run one loop, and hand it the right two lists.

**The defect this file was written for.** A stream's stop-list answers "when may the
connection close?". A graph suspended at `PLAN_READY`/`HITL_READY` publishes nothing more
until a human acts, so the live tail closes there — correct, and why both gates are on
`_TERMINAL_EVENTS`. Applying that same list to the *backlog* says something different and
wrong: "stop reading history at the first gate". A client that reconnects **without** a
`Last-Event-ID` — which is what a fresh `EventSource` is, and a status change creates one —
replays from id 0, hits the `PLAN_READY` row the design gate left behind, and returns.
Everything the run did after the gate is never delivered, and the live tail is never
reached either.

**Why this file changed shape.** There were four copies of that loop — the server's session
and run streams, the desktop's two — and the rule was right in one and copied from the tail's
list in the other three. None of them could be called: each was a closure inside a route,
over a Redis subscription or an in-process bus. So this file used to assert the rule by
*reading their source*, finding the backlog loop with a regex and checking which names were
compared inside it. That is an honest response to untestable code, and it can only ever
assert what the source looks like.

The loop is now `app/services/event_stream.py`, and `test_sse_frames.py` drives it: replay
past a gate, tail stopping at one, dedup, and an unstored event delivered without a cursor
are all *behaviour* now. What is left for this file is the part behaviour cannot show —
that every route actually uses that loop, and hands it the two correct lists rather than one
list twice.
"""

from __future__ import annotations

import ast
import inspect

from app.services.event_stream import sse_frames


def _calls_to(source: str, name: str) -> list[ast.Call]:
    tree = ast.parse(inspect.cleandoc(source))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name
    ]


def _stop_lists(route) -> tuple[str, str]:
    """The `replay_stop` and `terminal_stop` arguments one route hands the generator."""
    calls = _calls_to(inspect.getsource(route), "sse_frames")
    assert len(calls) == 1, f"{route.__qualname__} does not call sse_frames exactly once"
    kwargs = {kw.arg: ast.unparse(kw.value) for kw in calls[0].keywords}
    assert "replay_stop" in kwargs and "terminal_stop" in kwargs, (
        f"{route.__qualname__} does not pass both stop-lists"
    )
    return kwargs["replay_stop"], kwargs["terminal_stop"]


def _routes() -> dict[str, object]:
    import tempfile

    from app.api.v1 import research, runs
    from desktop.sidecar import create_sidecar_app

    desktop = create_sidecar_app(data_dir=tempfile.mkdtemp(), token="streams", fake=True)
    found = {
        "server session": research.stream_events,
        "server run": runs.stream_run,
    }
    for route in desktop.routes:
        endpoint = getattr(route, "endpoint", None)
        if endpoint is not None and endpoint.__name__ in ("stream_events", "v2_stream_run"):
            found[f"desktop {endpoint.__name__}"] = endpoint
    # The desktop's routes live on an included router; walk it if the flat scan missed them.
    if len(found) < 4:
        from tests.workflow.test_one_canonical_owner import _endpoints

        endpoints = _endpoints(desktop)
        found["desktop session"] = endpoints["GET /research/{session_id}/stream"]
        found["desktop run"] = endpoints["GET /runs/{run_id}/stream"]
    return found


def test_all_four_streams_use_the_one_generator():
    """The anti-duplication check. A fifth copy of the loop would pass every behavioural
    test in `test_sse_frames` and still be a fifth copy."""
    routes = _routes()
    assert len(routes) == 4, f"expected four streams, found {sorted(routes)}"
    for name, route in routes.items():
        assert _calls_to(inspect.getsource(route), "sse_frames"), (
            f"{name} does not use the shared frame generator — it has its own loop"
        )


def test_no_stream_passes_the_same_list_twice():
    """The original defect, stated where it can still be made: the two lists are different
    lists, and a route that passes one for both has recreated the bug inside the new
    structure."""
    for name, route in _routes().items():
        replay, terminal = _stop_lists(route)
        assert replay != terminal, (
            f"{name} hands the same stop-list to replay and to the live tail — replay would "
            "stop at the design gate and hide everything the run did afterwards"
        )


def test_the_generator_is_the_only_place_the_rule_is_written():
    """`sse_frames` takes both lists as arguments and never names an event type itself.

    If it did, a route's lists would be advisory and the real rule would be hidden inside
    the generator — which is how this got wrong in the first place, four times over.
    """
    source = inspect.getsource(sse_frames)
    for event in ("PLAN_READY", "HITL_READY", "COMPLETED", "FAILED"):
        assert f'"{event}"' not in source, (
            f"sse_frames hard-codes {event}; the stop-lists are the caller's to state"
        )
