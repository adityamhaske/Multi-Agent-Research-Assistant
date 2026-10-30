"""
`evals/grounding_benchmark.py` measures what §17 defines (RFC V3.1 G-6, D-23).

The benchmark itself needs a person's labels and a real model. These pin the parts that
must already be right:
- the arithmetic: false-accept over negatives, false-reject over positives, the Wilson bound;
- unmeasured claims kept out of every denominator, and a run above 5% unmeasured being
  invalid rather than a score;
- a claim's verdict from its atomic claims;
- each set item becoming a draft whose citations the real validator resolves.

The last runs the shipped `grounding.validate` on real items with the competent scripted
checker from `test_grounding_validator`. That checker proves the plumbing, never accuracy.
"""

from __future__ import annotations

import pytest

from evals import grounding_benchmark as gb
from research_engine import grounding
from research_engine.runconfig import RunConfig, reset_run_config, set_run_config
from tests.dataflow.test_grounding_validator import Judge


def _rows(pairs):
    return [{"id": f"x{i}", "verdict": v} for i, (_, v) in enumerate(pairs)], {
        f"x{i}": label for i, (label, _) in enumerate(pairs)
    }


def test_wilson_upper_bound_matches_the_closed_form():
    assert gb.wilson_upper(0, 0) is None
    assert gb.wilson_upper(5, 250) == pytest.approx(0.0460, abs=5e-4)
    assert gb.wilson_upper(3, 160) == pytest.approx(0.0537, abs=5e-4)


def test_false_accept_and_reject_use_their_own_denominators():
    rows, labels = _rows(
        [("not_supported", "supported")]  # a false accept
        + [("not_supported", "not_supported")] * 9
        + [("supported", "not_supported")]  # a false reject
        + [("supported", "supported")] * 3
        + [("contradicted", "contradicted"), ("contradicted", "not_supported")]
    )
    r = gb.score(rows, labels)
    assert r["false_accept"] == pytest.approx(1 / 12)
    assert r["false_reject"] == pytest.approx(1 / 4)
    assert r["contradicted_recall"] == pytest.approx(1 / 2)
    assert r["confusion"]["not_supported"]["supported"] == 1


def test_unmeasured_claims_are_outside_every_denominator():
    rows, labels = _rows(
        [("supported", "supported")] * 40
        + [("not_supported", "not_supported")] * 59
        + [("not_supported", "unmeasured")]
    )
    r = gb.score(rows, labels)
    assert r["unmeasured"] == 1
    assert r["false_accept_counts"]["negatives_measured"] == 59
    assert r["false_reject_counts"]["positives_measured"] == 40
    assert r["status"] == "measured"


def test_above_five_percent_unmeasured_the_run_is_invalid_not_a_score():
    rows, labels = _rows([("supported", "supported")] * 18 + [("not_supported", "unmeasured")] * 2)
    r = gb.score(rows, labels)
    assert r["status"] == "invalid"
    assert r["meets_threshold"] is None


class _V:
    def __init__(self, states, unparsed=()):
        self.claims = [
            grounding.Claim(unit=0, sentence="s", text=f"c{i}", span=(0, 1), cites=[1], state=s)
            for i, s in enumerate(states)
        ]
        self.unparsed_lines = list(unparsed)


@pytest.mark.parametrize(
    "states,want",
    [
        ([grounding.SUPPORTED, grounding.SUPPORTED], "supported"),
        ([grounding.SUPPORTED, grounding.NOT_SUPPORTED], "not_supported"),
        ([grounding.SUPPORTED, grounding.CONTRADICTED], "contradicted"),
        ([grounding.SUPPORTED, grounding.UNMEASURED], "unmeasured"),
        ([], "unmeasured"),
    ],
)
def test_a_claim_is_judged_by_all_of_its_atomic_claims(states, want):
    assert gb.claim_verdict(_V(states))[0] == want


@pytest.fixture
def scripted_checker(monkeypatch):
    holder = {"judge": Judge()}
    monkeypatch.setattr(grounding, "get_llm", lambda role: holder["judge"])
    monkeypatch.setattr(grounding, "RETRY_BACKOFF_SECONDS", 0)
    token = set_run_config(RunConfig(llm_mode="real"))
    yield holder
    reset_run_config(token)


async def test_set_items_reach_a_verdict_through_the_real_validator(scripted_checker):
    items = [i for i in gb.load_items() if len(i["snippets"]) in (1, 2)][:12]
    verdicts = [await gb.judge(item) for item in items]
    assert all(v["verdict"] in gb.VERDICTS for v in verdicts)
    assert all(v["calls"] >= 1 for v in verdicts), "every claim reached a model call"
    assert any(v["verdict"] != "unmeasured" for v in verdicts), "the drafts parse and cite"


def test_without_labels_there_is_no_measurement(tmp_path, monkeypatch):
    monkeypatch.setattr(gb, "SET", tmp_path)
    (tmp_path / "items.json").write_text('{"items": [{"id": "g001"}]}', encoding="utf-8")
    with pytest.raises(gb.Unmeasurable, match="no labels.json"):
        gb.load()
