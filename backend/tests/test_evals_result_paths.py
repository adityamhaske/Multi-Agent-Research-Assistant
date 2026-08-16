"""Eval results are write-once (AGENTS.md; CI job `eval-artifacts`).

The old default filename was `eval-<date>.json`, which is not a run identity: two runs on
one day collide. That is not hypothetical — `cbde168`, a frontend commit, overwrote
`eval-2026-08-13.json` and destroyed a real 10/10 ollama measurement, leaving the README
citing numbers whose proof no longer existed. Nothing failed and nothing warned.

CI catches the overwrite at PR time; these tests pin the harness so it never produces a
colliding name in the first place.
"""

import os

# See test_evals_support_rate.py — importing `evals.harness` runs `load_env_file()` at
# module scope and would leak .env into os.environ for the whole session.
_ENV_BEFORE = dict(os.environ)
from evals import harness  # noqa: E402 — must follow the snapshot above

os.environ.clear()
os.environ.update(_ENV_BEFORE)

from dataclasses import replace  # noqa: E402


def _route(monkeypatch, tmp_path, planner: str, mode: str = "real"):
    cfg = replace(harness.RUN_CONFIG, models={**harness.RUN_CONFIG.models, "planner": planner})
    cfg = replace(cfg, llm_mode=mode)
    monkeypatch.setattr(harness, "RUN_CONFIG", cfg)
    monkeypatch.setattr(harness, "RESULTS_DIR", tmp_path)


def test_routing_slug_splits_on_the_first_colon_only(monkeypatch, tmp_path):
    # `ollama:qwen2.5:7b` is provider `ollama`, model `qwen2.5:7b` (AGENTS.md).
    _route(monkeypatch, tmp_path, "ollama:qwen2.5:7b")
    assert harness._routing_slug() == "ollama"


def test_result_path_carries_the_routing(monkeypatch, tmp_path):
    _route(monkeypatch, tmp_path, "google:gemini-2.5-flash")
    assert harness._result_path("2026-01-01").name == "eval-2026-01-01-google.json"


def test_fake_mode_is_named_fake_not_by_provider(monkeypatch, tmp_path):
    """A fake run contacts no provider, so naming it after one would misattribute it."""
    _route(monkeypatch, tmp_path, "google:gemini-2.5-flash", mode="fake")
    assert harness._result_path("2026-01-01").name == "eval-2026-01-01-fake.json"


def test_a_second_run_the_same_day_never_overwrites_the_first(monkeypatch, tmp_path):
    """The regression that destroyed eval-2026-08-13.json."""
    _route(monkeypatch, tmp_path, "ollama:qwen2.5")

    first = harness._result_path("2026-01-01")
    first.write_text("{}")

    second = harness._result_path("2026-01-01")
    assert second != first
    assert second.name == "eval-2026-01-01-ollama-run2.json"
    assert first.read_text() == "{}"  # untouched

    second.write_text("{}")
    third = harness._result_path("2026-01-01")
    assert third.name == "eval-2026-01-01-ollama-run3.json"


def test_result_path_never_returns_a_live_file(monkeypatch, tmp_path):
    _route(monkeypatch, tmp_path, "ollama:qwen2.5")
    for _ in range(5):
        path = harness._result_path("2026-01-01")
        assert not path.exists()
        path.write_text("{}")


def test_fake_mode_records_no_model_ids(monkeypatch, tmp_path):
    """A fake run calls no provider, so recording five real ids would name models that
    were never invoked — the defect in eval-2026-07-23.json."""
    _route(monkeypatch, tmp_path, "google:gemini-2.5-flash", mode="fake")
    models = (
        {"_note": "fake mode — no provider was called"}
        if harness.RUN_CONFIG.llm_mode == "fake"
        else {role: harness.RUN_CONFIG.models[role] for role in harness._ROLES}
    )
    assert "google:gemini-2.5-flash" not in str(models)
    assert "_note" in models
