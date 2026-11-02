"""
How accurate the claim checker was measured to be on a checking route (RFC V3.1 §17, D-24).

A selection run's report is only as trustworthy as the model that checked it, and the G-6
benchmark measured that for a few routes only. A route below the threshold is **labelled,
not refused**, and a route never benchmarked says "not measured": the label must never imply
a number nobody measured (the unmeasured-vs-zero rule, applied to a whole model).

`MEASURED` is copied from the newest valid G-6 result for each route under
`backend/evals/results/`, and `tests/task/test_checker_accuracy.py` fails when the two
disagree. The engine cannot read that directory at run time — the desktop bundle does not
ship `evals/` — so the verdict is restated here and the test keeps it honest.
"""

from __future__ import annotations

MEETS = "meets_threshold"
BELOW = "below_threshold"
NOT_MEASURED = "not_measured"

#: route → (status, result file). Only valid runs count: one with more than 5% of claims
#: unmeasured is invalid by §17 and measured nothing.
MEASURED: dict[str, tuple[str, str]] = {
    "custom:auto/best-fast": (MEETS, "eval-2026-11-02-custom-auto-best-fast-grounding-run1.json"),
    "custom:agy/gemini-3-flash": (
        BELOW,
        "eval-2026-11-02-custom-agy-gemini-3-flash-grounding-run1.json",
    ),
}

_WORDS = {
    MEETS: "meets the measured threshold",
    BELOW: "below the measured threshold",
    NOT_MEASURED: "not measured",
}


def for_route(route: str | None) -> dict:
    """The recorded verdict for the route that checked a run, with the words to show for it.

    A `custom:` route is named by whoever runs the endpoint, so the same name on another
    gateway may be served by another model. Its verdict is kept, and the label says where it
    was measured rather than vouching for an endpoint nobody benchmarked.
    """
    status, result = MEASURED.get(route or "", (NOT_MEASURED, None))
    label = f"checker accuracy on this model: {_WORDS[status]}"
    if status != NOT_MEASURED and (route or "").startswith("custom:"):
        label += " (measured on the maintainers' gateway; a custom endpoint chooses its model)"
    return {"routing": route, "status": status, "result": result, "label": label}
