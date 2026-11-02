"""The checker-accuracy label states what G-6 measured, and nothing it did not (D-24)."""

from __future__ import annotations

import json
from pathlib import Path

from research_engine import checker_accuracy as ca

RESULTS = Path(__file__).resolve().parents[2] / "evals" / "results"


def _newest_valid_runs() -> dict[str, tuple[str, str]]:
    """route → (status, file) from the newest valid, full G-6 run for each route."""
    newest: dict[str, tuple[tuple, str, str]] = {}
    for path in sorted(RESULTS.glob("eval-*-grounding-run*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        result = data["result"]
        if data.get("preflight") or result.get("status") != "measured":
            continue  # an invalid run measured nothing; a preflight is not the benchmark
        status = ca.MEETS if result.get("meets_threshold") else ca.BELOW
        key = (data["generated_at"], path.name)
        route = data["critic_routing"]
        if route not in newest or key > newest[route][0]:
            newest[route] = (key, status, path.name)
    return {route: (status, name) for route, (_, status, name) in newest.items()}


def test_the_recorded_verdicts_are_the_newest_valid_benchmark_runs():
    assert ca.MEASURED == _newest_valid_runs()


def test_a_route_never_benchmarked_says_not_measured():
    entry = ca.for_route("ollama:qwen2.5:7b")
    assert entry["status"] == ca.NOT_MEASURED and entry["result"] is None
    assert entry["label"] == "checker accuracy on this model: not measured"
    assert ca.for_route(None)["status"] == ca.NOT_MEASURED


def test_a_measured_custom_route_says_where_it_was_measured(monkeypatch):
    monkeypatch.setattr(
        ca, "MEASURED", {"custom:x": (ca.BELOW, "r.json"), "google:y": (ca.MEETS, "s.json")}
    )
    custom = ca.for_route("custom:x")
    assert custom["label"].startswith(
        "checker accuracy on this model: below the measured threshold"
    )
    assert "maintainers' gateway" in custom["label"]
    assert ca.for_route("google:y")["label"] == (
        "checker accuracy on this model: meets the measured threshold"
    )
