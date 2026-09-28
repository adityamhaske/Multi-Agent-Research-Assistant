"""
The citation judge is named, independent of what it grades, and disclosed (RG-5).

RG-5 asks for "a committed write-once eval result clearing `MIN_CITATION_SUPPORT` with a
disclosed independent judge that actually answered". Until V3 the harness judged with
`get_llm("critic")` — the pipeline's own critic grading the pipeline's own citations — and
wrote no judge into the result at all. The best qualifying number on record (0.90) is
therefore self-judged, and nothing in its file says so.

These tests pin the four properties the gate needs, each on its own:

- **Named, never defaulted.** Judging refuses when no judge is configured, rather than
  falling back to the critic; a real-mode report eval refuses to start without `--judge`,
  before a single query spends anything.
- **Independent.** A judge that is any route the harness runs, the same model reached
  through another provider, or a router alias that could resolve to either, is refused.
- **Disclosed.** The result carries a `judge` block beside `models`: the route, the routes it
  was checked against, and what it actually did for baseline and candidate.
- **Actually answered.** Which model served each ruling is read from the provider's
  response, never copied from the route — so a judge that answered as something else, or
  not at all, shows it. Through a gateway (OmniRoute), the connection and routing decision
  it reports are recorded the same way: observed per ruling, null when absent, and nothing
  else from the response headers is kept.

Thresholds, eval isolation and write-once results are pinned elsewhere and untouched here;
the last test only confirms a judged run still cannot land on an existing file.
"""

from __future__ import annotations

import json
import os
import sys
import types
from dataclasses import replace

import pytest

_ENV_BEFORE = dict(os.environ)
from evals import harness  # noqa: E402
from research_engine.runconfig import get_run_config  # noqa: E402

os.environ.clear()
os.environ.update(_ENV_BEFORE)

#: The routes the harness runs — the system under evaluation, read rather than assumed.
PIPELINE = {role: harness.RUN_CONFIG.models[role] for role in harness._ROLES}
PIPELINE_ROUTE = PIPELINE["critic"]
JUDGE = "anthropic:claude-sonnet-4-6"

REPORT = (
    "# R\n\n## Key Findings\n"
    "- The first substantive finding stated here [1]\n"
    "- The second substantive finding stated here [2]\n\n"
    "## Sources\n[1] https://example.com/1\n[2] https://example.com/2\n"
)
SOURCES = [
    {"index": 1, "url": "https://example.com/1", "title": "S1", "snippet": "alpha"},
    {"index": 2, "url": "https://example.com/2", "title": "S2", "snippet": "beta"},
]


class _Reply:
    def __init__(self, content: str, served: str | None, headers: dict | None = None) -> None:
        self.content = content
        self.response_metadata = {"model_name": served} if served else {}
        if headers is not None:
            self.response_metadata["headers"] = headers


class _Judge:
    """Answers every batch, and records which route the factory was building for."""

    def __init__(
        self,
        served: str | None = "claude-sonnet-4-6-20260101",
        headers: dict | None = None,
        reply: str = "Claim 1: YES\nClaim 2: NO",
    ) -> None:
        self.served = served
        self.headers = headers
        self.reply = reply
        self.calls = 0

    async def ainvoke(self, messages):  # noqa: ANN001 — mirrors langchain's signature
        self.calls += 1
        return _Reply(self.reply, self.served, self.headers)


@pytest.fixture(autouse=True)
def _no_judge_leaks(monkeypatch):
    """`configure_judge` assigns a module global; this restores it after every test."""
    monkeypatch.setattr(harness, "JUDGE_ROUTE", None)


@pytest.fixture
def factory(monkeypatch):
    """The engine factory, spied on: what it was asked for, and under which routing."""
    built: list[str] = []
    judge = _Judge()

    def get_llm(role):
        built.append(get_run_config().models[role])
        return judge

    monkeypatch.setattr("research_engine.llm_factory.get_llm", get_llm)
    return built, judge


# ── Named, never defaulted ────────────────────────────────────────────────────────


async def test_judging_refuses_without_a_named_judge_rather_than_using_the_critic(factory):
    built, judge = factory
    with pytest.raises(harness.JudgeConfigError, match="never falls back"):
        await harness.judge_citation_support(REPORT, SOURCES)
    assert built == [], "the factory was asked for a model — the critic fallback is back"
    assert judge.calls == 0


async def test_the_named_judge_is_what_gets_built(factory):
    built, _ = factory
    harness.configure_judge(JUDGE)
    await harness.judge_citation_support(REPORT, SOURCES)
    assert built == [JUDGE]
    # Borrowing the critic's slot to build the judge must not outlive the build.
    assert get_run_config().models["critic"] != JUDGE


# ── Independent ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("judge", "why"),
    [
        (PIPELINE_ROUTE, "cannot also be its judge"),  # the pipeline's own route
        (  # the same model reached through another provider
            "openrouter:google/" + PIPELINE_ROUTE.partition(":")[2],
            "cannot also be its judge",
        ),
        # A router alias could resolve to anything, the pipeline's own model included.
        ("custom:auto/best-fast", "router alias"),
        ("openrouter:openrouter/auto", "router alias"),
        ("gemini-2.5-pro", "provider:model"),  # no provider
        ("anthropic:", "provider:model"),  # no model
    ],
)
def test_a_judge_that_is_not_independent_is_refused(judge, why):
    with pytest.raises(harness.JudgeConfigError, match=why):
        harness.configure_judge(judge)
    assert harness.JUDGE_ROUTE is None


def test_one_model_under_two_spellings_is_one_model():
    pipeline = {"planner": "ollama:qwen2.5:latest"}
    with pytest.raises(harness.JudgeConfigError, match="planner"):
        harness.validate_judge("ollama:qwen2.5", pipeline)


def test_a_pipeline_on_a_router_alias_cannot_be_shown_independent_of_anything():
    """If the pipeline's own model is unknown, no judge can be proved different from it."""
    with pytest.raises(harness.JudgeConfigError, match="Pin the model"):
        harness.validate_judge(JUDGE, {"synthesizer": "custom:auto/best-fast"})


def test_a_different_pinned_model_is_accepted():
    assert harness.configure_judge(JUDGE) == JUDGE == harness.JUDGE_ROUTE


# ── Disclosed, and actually answered ──────────────────────────────────────────────


async def test_every_ruling_records_the_model_that_served_it(factory):
    _, judge = factory
    harness.configure_judge(JUDGE)
    rate, rows = await harness.judge_citation_support(REPORT, SOURCES)
    assert rate == 0.5
    assert [r["judged_by"] for r in rows] == [judge.served, judge.served]


async def test_an_undisclosed_server_is_recorded_as_undisclosed_not_as_the_route(monkeypatch):
    judge = _Judge(served=None)
    monkeypatch.setattr("research_engine.llm_factory.get_llm", lambda role: judge)
    harness.configure_judge(JUDGE)
    _, rows = await harness.judge_citation_support(REPORT, SOURCES)
    assert [r["judged_by"] for r in rows] == [None, None]
    assert harness.judge_tally([{"claim_verdicts": rows}])["served_models"] == []


def test_the_tally_counts_only_what_the_judge_ruled_on():
    rows = [
        {"claim_verdicts": [{"judged": True, "judged_by": "m1"}, {"judged": False}]},
        {"claim_verdicts": [{"judged": True, "judged_by": "m2"}]},
        {"completed": False},  # a query that never reached the judge
    ]
    assert harness.judge_tally(rows) == {
        "claims_judged": 2,
        "claims_unjudged": 1,
        "served_models": ["m1", "m2"],
        # These rulings carried no gateway routing, and the tally says so rather than
        # leaving the question unanswered.
        "routing": {"providers": [], "models": [], "strategies": [], "rulings_without_routing": 2},
    }


def test_a_judge_that_ruled_on_nothing_did_not_answer():
    section = harness.judge_section(JUDGE, [{"claim_verdicts": [{"judged": False}]}], None)
    assert section["answered"] is False
    assert "candidate" not in section


# ── The command line, end to end ──────────────────────────────────────────────────


#: What OmniRoute reported for the judge validated before the release run (kiro, strategy
#: single). The tests only need its shape; the values are the real ones for readability.
ROUTED = {
    "provider": "kr",
    "model": "claude-sonnet-4.5",
    "decision": "strategy=single; provider=kr; latency_ms=1805",
}


def _row(query_id: str, *, served: str = "claude-sonnet-4-6-20260101") -> dict:
    return {
        "id": query_id,
        "completed": True,
        "error": None,
        "latency_s": 0.0,
        "citation_support_rate": 1.0,
        "claim_verdicts": [
            {
                "claim": "c",
                "supported": True,
                "judged": True,
                "judged_by": served,
                "judge_routing": dict(ROUTED),
            }
        ],
    }


@pytest.fixture
def real_mode(monkeypatch, tmp_path):
    """`main()` in real mode with nothing leaving the process: a scripted `run_one`, no
    sleeps, and results written to a temporary directory."""
    calls: list[dict | None] = []

    async def run_one(query, *, prompt_overrides=None):
        calls.append(prompt_overrides)
        return _row(query["id"])

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(harness, "RUN_CONFIG", replace(harness.RUN_CONFIG, llm_mode="real"))
    monkeypatch.setattr(harness, "run_one", run_one)
    monkeypatch.setattr(harness, "asyncio", types.SimpleNamespace(sleep=no_sleep))
    monkeypatch.setattr(harness, "RESULTS_DIR", tmp_path)
    return calls


async def _main(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["harness", "--limit", "2", "--date", "2026-09-27", *argv])
    await harness.main()


async def test_a_real_run_without_a_judge_refuses_before_any_query(monkeypatch, real_mode):
    with pytest.raises(SystemExit) as exc:
        await _main(monkeypatch)
    assert exc.value.code == 2
    assert real_mode == [], "a query ran — the refusal came after money was spent"


async def test_a_real_run_with_a_self_judge_refuses_before_any_query(monkeypatch, real_mode):
    with pytest.raises(SystemExit) as exc:
        await _main(monkeypatch, "--judge", PIPELINE_ROUTE)
    assert exc.value.code == 2
    assert real_mode == []


async def test_a_scripted_run_rejects_a_judge_it_would_never_call(monkeypatch, tmp_path):
    monkeypatch.setattr(harness, "RESULTS_DIR", tmp_path)
    with pytest.raises(SystemExit) as exc:
        await _main(monkeypatch, "--judge", JUDGE)
    assert exc.value.code == 2


async def test_the_result_discloses_its_judge_beside_the_models_it_graded(
    monkeypatch, tmp_path, real_mode
):
    await _main(monkeypatch, "--judge", JUDGE)
    (written,) = tmp_path.glob("eval-*.json")
    payload = json.loads(written.read_text())

    assert payload["models"] == PIPELINE
    assert payload["judge"] == {
        "route": JUDGE,
        "independent_of": payload["models"],
        "baseline": {
            "claims_judged": 2,
            "claims_unjudged": 0,
            "served_models": ["claude-sonnet-4-6-20260101"],
            "routing": {
                "providers": ["kr"],
                "models": ["claude-sonnet-4.5"],
                "strategies": ["single"],
                "rulings_without_routing": 0,
            },
        },
        "answered": True,
    }
    # Thresholds are the fixed ones; naming a judge changes who grades, not the bar.
    assert payload["release_criteria"]["thresholds"] == {
        "min_completion_rate": harness.MIN_COMPLETION_RATE,
        "min_citation_support": harness.MIN_CITATION_SUPPORT,
    }


async def test_baseline_and_candidate_are_judged_by_the_same_judge_and_both_tallied(
    monkeypatch, tmp_path, real_mode
):
    spec = tmp_path / "spec"
    spec.mkdir()
    (spec / "c.json").write_text(json.dumps({"planner": "Plan in exactly two tasks."}))
    await _main(monkeypatch, "--judge", JUDGE, "--candidate", str(spec / "c.json"))
    (written,) = tmp_path.glob("eval-*-custom.json")
    judge = json.loads(written.read_text())["judge"]

    candidate = {"planner": "Plan in exactly two tasks."}
    assert real_mode == [None, None, candidate, candidate]  # the same two queries, twice
    assert judge["route"] == JUDGE
    assert judge["baseline"]["claims_judged"] == judge["candidate"]["claims_judged"] == 2
    # One judge configuration for both halves, and the gateway saw it that way too.
    assert judge["baseline"]["routing"] == judge["candidate"]["routing"]


async def test_a_judged_run_is_still_write_once(monkeypatch, tmp_path, real_mode):
    await _main(monkeypatch, "--judge", JUDGE)
    (first,) = tmp_path.glob("eval-*.json")
    before = first.read_bytes()
    await _main(monkeypatch, "--judge", JUDGE)
    assert sorted(p.name for p in tmp_path.glob("eval-*.json")) == [
        "eval-2026-09-27-google-run2.json",
        "eval-2026-09-27-google.json",
    ]
    assert first.read_bytes() == before
    with pytest.raises(SystemExit, match="write-once"):
        await _main(monkeypatch, "--judge", JUDGE, "--out", str(first))


# ── Gateway routing provenance ────────────────────────────────────────────────────

GATEWAY_JUDGE = "custom:kiro/claude-sonnet-4.5"
SECRET = "sk-must-never-reach-a-result"


def _gateway_headers(**extra) -> dict:
    """What an OmniRoute response carries, plus headers that must never be persisted."""
    return {
        "X-OmniRoute-Provider": "kr",
        "X-OmniRoute-Model": "claude-sonnet-4.5",
        "X-OmniRoute-Decision": "strategy=single; provider=kr; latency_ms=12",
        "Authorization": f"Bearer {SECRET}",
        "Set-Cookie": f"session={SECRET}",
        "x-api-key": SECRET,
        **extra,
    }


async def test_gateway_routing_is_recorded_for_every_ruling(monkeypatch):
    judge = _Judge(served="claude-sonnet-4.5", headers=_gateway_headers())
    monkeypatch.setattr("research_engine.llm_factory.get_llm", lambda role: judge)
    harness.configure_judge(GATEWAY_JUDGE)
    _, rows = await harness.judge_citation_support(REPORT, SOURCES)
    assert [r["judge_routing"] for r in rows] == [
        {
            "provider": "kr",
            "model": "claude-sonnet-4.5",
            "decision": "strategy=single; provider=kr; latency_ms=12",
        }
    ] * 2


async def test_no_other_response_header_is_ever_persisted(monkeypatch):
    """Only three headers are read, by name — a credential a gateway echoes back, a cookie,
    anything else, cannot reach the rows, the tally, or the file built from them."""
    judge = _Judge(served="claude-sonnet-4.5", headers=_gateway_headers())
    monkeypatch.setattr("research_engine.llm_factory.get_llm", lambda role: judge)
    harness.configure_judge(GATEWAY_JUDGE)
    _, rows = await harness.judge_citation_support(REPORT, SOURCES)
    persisted = json.dumps({"rows": rows, "tally": harness.judge_tally([{"claim_verdicts": rows}])})
    assert SECRET not in persisted
    assert "authorization" not in persisted.lower()
    assert "cookie" not in persisted.lower()


async def test_a_missing_routing_header_stays_null_and_is_never_filled_from_the_route(monkeypatch):
    judge = _Judge(served="claude-sonnet-4.5", headers={"X-OmniRoute-Provider": "kr"})
    monkeypatch.setattr("research_engine.llm_factory.get_llm", lambda role: judge)
    harness.configure_judge(GATEWAY_JUDGE)
    _, rows = await harness.judge_citation_support(REPORT, SOURCES)
    assert rows[0]["judge_routing"] == {"provider": "kr", "model": None, "decision": None}


async def test_a_client_that_reports_no_routing_records_nulls_not_the_route(monkeypatch):
    """A direct provider client, or a test double, sends no gateway headers at all."""
    judge = _Judge(served="claude-sonnet-4-6-20260101")
    monkeypatch.setattr("research_engine.llm_factory.get_llm", lambda role: judge)
    harness.configure_judge(JUDGE)
    _, rows = await harness.judge_citation_support(REPORT, SOURCES)
    assert [r["judge_routing"] for r in rows] == [
        {"provider": None, "model": None, "decision": None}
    ] * 2
    tally = harness.judge_tally([{"claim_verdicts": rows}])
    assert tally["routing"]["rulings_without_routing"] == 2
    assert tally["routing"]["providers"] == []


async def test_a_claim_nothing_ruled_on_carries_no_routing(monkeypatch):
    judge = _Judge(served="claude-sonnet-4.5", headers=_gateway_headers(), reply="Claim 1: YES")
    monkeypatch.setattr("research_engine.llm_factory.get_llm", lambda role: judge)
    harness.configure_judge(GATEWAY_JUDGE)
    _, rows = await harness.judge_citation_support(REPORT, SOURCES)
    assert rows[0]["judged"] and rows[0]["judge_routing"]["provider"] == "kr"
    assert not rows[1]["judged"] and rows[1]["judge_routing"] is None


async def test_the_recorded_judge_model_is_the_one_that_answered_not_the_route(monkeypatch):
    judge = _Judge(served="claude-sonnet-4-5-20250929", headers=_gateway_headers())
    monkeypatch.setattr("research_engine.llm_factory.get_llm", lambda role: judge)
    harness.configure_judge(GATEWAY_JUDGE)
    _, rows = await harness.judge_citation_support(REPORT, SOURCES)
    assert {r["judged_by"] for r in rows} == {"claude-sonnet-4-5-20250929"}
    assert GATEWAY_JUDGE.partition(":")[2] not in {r["judged_by"] for r in rows}


def test_the_judges_own_client_is_asked_for_response_headers():
    """Headers are opted into on the judge's instance, built for the judge's route — the
    factory still builds it, so the no-fallback rule above is untouched."""
    from langchain_openai import ChatOpenAI

    from research_engine.runconfig import reset_run_config, set_run_config

    harness.configure_judge(GATEWAY_JUDGE)
    # The test process runs scripted models; building a real client needs real mode. No call
    # is made — the client is only constructed and inspected.
    token = set_run_config(replace(get_run_config(), llm_mode="real"))
    try:
        llm = harness._judge_llm()
    finally:
        reset_run_config(token)
    assert isinstance(llm, ChatOpenAI)
    assert llm.model_name == "kiro/claude-sonnet-4.5"
    assert llm.include_response_headers is True


def test_a_client_without_the_option_is_left_as_built(factory):
    _, judge = factory
    harness.configure_judge(JUDGE)
    assert harness._judge_llm() is judge
    assert not hasattr(judge, "include_response_headers")


async def test_routing_is_read_through_the_real_openai_client_end_to_end():
    """A real `ChatOpenAI` against a loopback stand-in for the gateway, so the whole chain —
    the opt-in, the client placing headers in `response_metadata`, the read by name — is
    exercised rather than asserted piecewise. The stub also checks the key was sent, and
    the rows are checked for it afterwards."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from research_engine.runconfig import reset_run_config, set_run_config

    seen_auth: list[str] = []
    body = json.dumps(
        {
            "id": "chatcmpl-stub",
            "object": "chat.completion",
            "created": 0,
            "model": "claude-sonnet-4.5",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Claim 1: YES\nClaim 2: NO"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    ).encode()

    class Gateway(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 — http.server's name
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            seen_auth.append(self.headers.get("Authorization", ""))
            self.send_response(200)
            for name, value in _gateway_headers().items():
                self.send_header(name, value)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # silence the stub
            pass

    server = HTTPServer(("127.0.0.1", 0), Gateway)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = get_run_config()
    token = set_run_config(
        replace(
            base,
            provider_keys={
                **base.provider_keys,
                "custom": SECRET,
                "custom_base_url": f"http://127.0.0.1:{server.server_port}/v1",
            },
            enforce_ssrf_guards=False,
            llm_mode="real",
        )
    )
    try:
        harness.configure_judge(GATEWAY_JUDGE)
        rate, rows = await harness.judge_citation_support(REPORT, SOURCES)
    finally:
        reset_run_config(token)
        server.shutdown()

    assert seen_auth == [f"Bearer {SECRET}"], "the stub was not reached the way the app calls it"
    assert rate == 0.5
    assert {r["judged_by"] for r in rows} == {"claude-sonnet-4.5"}
    assert rows[0]["judge_routing"] == {
        "provider": "kr",
        "model": "claude-sonnet-4.5",
        "decision": "strategy=single; provider=kr; latency_ms=12",
    }
    assert SECRET not in json.dumps(rows)
