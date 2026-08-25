"""Regression tests for the citation-support judge (docs/08 §5).

The judge must distinguish "we could not measure this claim" from "this claim is not
supported". `benchmark.py::calc_support_rate` already draws that line — it filters the
denominator to claims carrying a real verdict and returns None when none do. The harness
did not: a provider error, a partial model reply, and an unparseable answer each counted
as UNSUPPORTED against the full claim count, dragging a *published* rate toward zero.

That is the failure mode AGENTS.md calls a P0 ("never print 0.0 for something you could
not measure"), and it was live in the same file that produced every committed
`citation_support_rate`.
"""

import os

import pytest

# `evals.harness` runs `load_env_file()` and `set_process_default()` at *import* time
# (harness.py §module docstring explains why mode is read before .env loads). Importing it
# therefore leaks the repo's .env into os.environ for the whole session, and
# `test_local_host.py::test_local_config_reads_env` asserts on an exact provider-key dict —
# so a stray OPENROUTER_API_KEY in .env would fail a test this file never touches.
# Snapshot and restore around the import; collection runs before any test, so this is
# deterministic regardless of file order.
_ENV_BEFORE = dict(os.environ)
from evals import harness  # noqa: E402 — must follow the snapshot above

os.environ.clear()
os.environ.update(_ENV_BEFORE)

# Four cited claims — one batch at harness.BATCH_SIZE == 4, so a single scripted reply
# covers the whole report and each test controls exactly one judge call.
REPORT = (
    "# Fixture Report\n\n## Key Findings\n"
    "- The first substantive finding stated here [1]\n"
    "- The second substantive finding stated here [2]\n"
    "- The third substantive finding stated here [1]\n"
    "- The fourth substantive finding stated here [2]\n\n"
    "## Sources\n[1] https://example.com/1\n[2] https://example.com/2\n"
)
SOURCES = [
    {"index": 1, "url": "https://example.com/1", "title": "S1", "snippet": "alpha"},
    {"index": 2, "url": "https://example.com/2", "title": "S2", "snippet": "beta"},
]


class _Reply:
    def __init__(self, content: str) -> None:
        self.content = content


class _ScriptedLLM:
    """One scripted item per batch: a string is returned, an Exception is raised."""

    def __init__(self, items: list) -> None:
        self._items = list(items)
        self.calls = 0

    async def ainvoke(self, messages):  # noqa: ANN001 — mirrors langchain's signature
        item = self._items[self.calls]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return _Reply(item)


@pytest.fixture
def scripted_judge(monkeypatch):
    """Install a scripted judge. `get_llm` is imported inside the function under test,
    so patching the factory module is what takes effect."""

    def _install(items: list) -> _ScriptedLLM:
        llm = _ScriptedLLM(items)
        monkeypatch.setattr("research_engine.llm_factory.get_llm", lambda role: llm)
        return llm

    return _install


async def test_rate_is_supported_over_judged_claims(scripted_judge):
    scripted_judge(["Claim 1: YES\nClaim 2: NO\nClaim 3: YES\nClaim 4: YES"])
    rate, rows = await harness.judge_citation_support(REPORT, SOURCES)
    assert rate == 0.75
    assert len(rows) == 4


async def test_provider_error_returns_none_not_zero(scripted_judge):
    """The whole point: an exhausted quota is not a quality signal."""
    scripted_judge([RuntimeError("429 RESOURCE_EXHAUSTED")])
    rate, rows = await harness.judge_citation_support(REPORT, SOURCES)
    # `is None` and `== 0.0` must be asserted distinctly — `assert not rate` passes
    # for both and is how this discipline silently regresses.
    assert rate is None
    assert rate != 0.0
    assert all(r["supported"] is None for r in rows)


async def test_partial_reply_excludes_unanswered_claims_from_denominator(scripted_judge):
    """The model answered 2 of 4. The other 2 were not measured, not refuted."""
    scripted_judge(["Claim 1: YES\nClaim 2: NO"])
    rate, rows = await harness.judge_citation_support(REPORT, SOURCES)
    assert rate == 0.5  # 1 supported / 2 judged — not 1/4
    assert [r["supported"] for r in rows] == [True, False, None, None]


async def test_unparseable_reply_returns_none(scripted_judge):
    scripted_judge(["I cannot comply with this request."])
    rate, _ = await harness.judge_citation_support(REPORT, SOURCES)
    assert rate is None


async def test_genuine_zero_is_still_reported_as_zero(scripted_judge):
    """The inverse guard: a real all-NO verdict must stay 0.0, never become None."""
    scripted_judge(["Claim 1: NO\nClaim 2: NO\nClaim 3: NO\nClaim 4: NO"])
    rate, _ = await harness.judge_citation_support(REPORT, SOURCES)
    assert rate == 0.0
    assert rate is not None


async def test_report_without_cited_claims_returns_none(scripted_judge):
    scripted_judge([])
    rate, rows = await harness.judge_citation_support("No citations at all here.", SOURCES)
    assert rate is None
    assert rows == []
