"""
Product facts a journey must observe, on both hosts. **Not a test module.**

Comparing two hosts to a golden proves they agree. It does not prove anything *happened*:
two implementations that both return `[]`, measured against a golden recorded from a run
that also returned `[]`, agree perfectly and mean nothing. An empty result is a valid
response shape, so no amount of shape comparison catches it.

What catches it is a journey stating, in its own product terms, what must be true when it
worked — and stating it *once*, so the same facts are asserted against both hosts. A
journey that declares no checks is reported as a failure rather than passing vacuously,
which is what stops the guard from being opted out of by omission.
"""

from __future__ import annotations

from typing import Any

#: The steps a journey recorded, as `journeys.drive()` returns them: `step`, `status`,
#: `body`, already normalized.
Observations = list[dict]


def body_at(observations: Observations, step: str) -> Any:
    """The normalized body recorded for `step`.

    Raises rather than returning `None` for a step the journey never reached. A check that
    reads `None` for a missing step is a check that passes when the journey broke, which is
    the failure mode this whole module exists to prevent.
    """
    for observed in observations:
        if observed["step"] == step:
            return observed["body"]
    raise KeyError(step)


def status_at(observations: Observations, step: str) -> int:
    for observed in observations:
        if observed["step"] == step:
            return observed["status"]
    raise KeyError(step)


def _has_content(value: Any) -> bool:
    """Whether a normalized body carries anything at all, recursively.

    `{}`, `[]`, `None`, `""` and any nesting of those are emptiness. A `{"runs": []}` is
    emptiness wearing a key, and is exactly the shape a broken list endpoint returns.
    """
    if value is None:
        return False
    if isinstance(value, dict):
        return any(_has_content(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_content(v) for v in value)
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, bool):
        return value
    return True


def at_least_one_nonempty_body(observations: Observations) -> bool:
    """The floor beneath every journey: at least one *successful* step carried content.

    Only 2xx bodies count. A journey that produced nothing but populated 4xx bodies has
    exercised its error contract rather than the product — legitimate for an
    error-contract journey, which declares its own checks, and a defect for any other.
    """
    return any(
        200 <= observed["status"] < 300 and _has_content(observed["body"])
        for observed in observations
    )


def failing_checks(journey, observations: Observations) -> list[str]:
    """The labels of every declared product fact that does not hold.

    A check that raises is reported as a failed fact rather than propagating: it has almost
    always read a step the journey never reached, which is a finding about the product, not
    a crash in the harness.
    """
    if not journey.checks:
        return [
            f"journey {journey.name!r} declares no checks — "
            "a journey that asserts nothing cannot fail"
        ]

    failed: list[str] = []
    for label, predicate in journey.checks:
        try:
            holds = bool(predicate(observations))
        except Exception as exc:  # noqa: BLE001 — see docstring: a finding, not an error
            failed.append(f"{label} (raised {type(exc).__name__}: {exc})")
            continue
        if not holds:
            failed.append(label)
    return failed
