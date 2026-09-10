"""
The metric registry is closed, private, and cannot be made to carry an identifier.

A metrics endpoint is a permanent, unauthenticated read of whatever the process decided to
put in it, so the interesting properties are all *negative*: what can never appear. Three of
them are load-bearing here.

**Private registry.** `prometheus_client` ships a process-global default that any imported
library may write to. Rendering that would mean `/metrics` exposes series this repository
never declared and cannot vouch for — and it would make these tests depend on import order.
`Metrics` owns its own `CollectorRegistry`, which is also what makes per-test isolation
possible at all.

**Closed names and labels.** `DECLARED` is the whole contract. A metric or label that is not
in it fails this file rather than appearing silently on a public endpoint.

**No identifier can become a label.** Every label value is mapped through a closed table
inside the module, so a run id, user id or filename has no path to `.labels()`. The
cardinality test is the same claim measured from the outside: drive many distinct ids and
the series count must not move.

**Two recording functions, because there are two terminal boundaries.** A run reaches
`COMPLETED` at the approval route and `FAILED`/`CANCELLED` in the persistence adapter — see
`tests/workflow/test_metrics_recording.py` for the evidence. `observe_completed_run` and
`observe_persisted_run` name those two situations rather than sharing one entry point that
each caller would have to know the rules of.
"""

from __future__ import annotations

import re
import uuid

import pytest

from app import metrics as m

#: Anything shaped like an id we must never leak: a uuid, or a long bare hex string.
_IDENTIFIER = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-|^[0-9a-f]{32,}$", re.IGNORECASE)

PRICED = {"planner": "google:gemini-2.5-flash"}


@pytest.fixture()
def registry(monkeypatch):
    """A fresh `Metrics` installed as the module default, torn down after."""
    fresh = m.Metrics()
    monkeypatch.setattr(m, "_default", fresh)
    return fresh


def _series(reg) -> int:
    """Every distinct label combination currently carried, `_created` samples excluded.

    `_created` is `prometheus_client`'s own per-counter timestamp sample, not a series this
    module declares, so counting it would make the cardinality assertion measure the
    library instead of the code under test.
    """
    return sum(
        1
        for family in reg.registry.collect()
        for sample in family.samples
        if not sample.name.endswith("_created")
    )


def _value(reg, name: str, labels: dict | None = None) -> float:
    return reg.registry.get_sample_value(name, labels) or 0.0


def _complete(reg, *, cost=0.5, tin=100, tout=50, routing=None) -> None:
    reg.observe_completed_run(
        cost_usd=cost, tokens_input=tin, tokens_output=tout, model_routing=routing
    )


def _persist(reg, status, *, cost=0.5, tin=100, tout=50, routing=None) -> None:
    reg.observe_persisted_run(
        status, cost_usd=cost, tokens_input=tin, tokens_output=tout, model_routing=routing
    )


# ── The registry is private ───────────────────────────────────────────────────────


def test_metrics_use_a_private_registry():
    assert m._default.registry is not m.prometheus_client.REGISTRY


def test_the_global_registry_cannot_leak_into_exposition(registry):
    """A series on `prometheus_client`'s default registry must not reach our endpoint."""
    from prometheus_client import Counter

    Counter(
        f"unrelated_library_total_{uuid.uuid4().hex}",
        "a third-party collector on the global default registry",
    )

    payload, _ = registry.render()

    assert b"unrelated_library_total" not in payload


def test_each_test_starts_from_a_clean_registry(registry):
    """The isolation this file's own fixture provides, asserted rather than assumed.

    Without it every counter in this suite would be cumulative across tests, and a
    "did it increment" assertion would pass on someone else's increment."""
    assert _value(registry, "research_run_outcomes_total", {"outcome": "completed"}) == 0.0

    _complete(registry)

    assert _value(registry, "research_run_outcomes_total", {"outcome": "completed"}) == 1.0
    assert (
        m.Metrics().registry.get_sample_value(
            "research_run_outcomes_total", {"outcome": "completed"}
        )
        is None
    ), "a second Metrics observed the first one's state"


# ── The declaration is the contract ───────────────────────────────────────────────


def test_metric_names_are_closed(registry):
    """Every family the registry carries is one this module declared, and vice versa."""
    assert {family.name for family in registry.registry.collect()} == set(m.DECLARED)


def test_the_declared_set_is_the_seven_families_a8_ships(registry):
    """Named here so a metric cannot be added without a reviewer seeing this list move.

    `research_run_wallclock_seconds` is deliberately absent: `runner._outcome` sets
    `elapsed_seconds` only on the `completed` branch, which the runs pipeline never reaches
    (approval finalizes at the route), so the value is NULL on every run and every bundle.
    A duration metric here would be permanently empty, and deriving one from timestamps
    would measure how long the reviewer took."""
    assert set(m.DECLARED) == {
        "research_run_outcomes",
        "research_run_cost_usd",
        "research_run_cost_confidence",
        "research_run_tokens",
        "corpus_ingest_documents",
        "corpus_ingest_bytes",
        "research_build_info",
    }


def test_metric_label_names_are_closed(registry):
    for family in registry.registry.collect():
        declared = set(m.DECLARED[family.name])
        for sample in family.samples:
            present = set(sample.labels)
            assert present <= declared, f"{family.name} carries undeclared label(s) {present}"


def test_label_values_come_only_from_declared_enums(registry):
    """Drive every recording path, then check every label value against its enum."""
    _complete(registry)
    for status in ("FAILED", "CANCELLED"):
        _persist(registry, status)
    for outcome in m.INGEST_OUTCOMES:
        registry.observe_ingest(outcome, byte_count=10)

    for family in registry.registry.collect():
        if family.name in m.IDENTITY_METRICS:
            continue
        for sample in family.samples:
            for label, value in sample.labels.items():
                assert value in m.DECLARED[family.name][label], (
                    f"{family.name}{{{label}={value!r}}} is not a declared value"
                )


def test_an_undeclared_ingest_outcome_is_refused(registry):
    """The guard exists in code, not only in this file's assertions."""
    with pytest.raises(ValueError):
        registry.observe_ingest("something-new")


def test_build_info_is_this_build_and_one_series(registry):
    """The one metric whose labels are not an enum: they are the build's own identity, so
    they are bounded by there being exactly one build per process rather than by a list."""
    from research_engine.build_info import build_info

    info = build_info()
    assert (
        _value(registry, "research_build_info", {"version": info.version, "git_sha": info.git_sha})
        == 1.0
    )
    assert sum(1 for f in registry.registry.collect() if f.name == "research_build_info") == 1


# ── Nothing that identifies anyone ────────────────────────────────────────────────


def test_no_identifier_can_become_a_label(registry):
    """No user, run, project or document identity in any label.

    `research_build_info` is exempt and only it: its `git_sha` is a 40-character hex string
    and so is identifier-*shaped*, but it identifies this build rather than anybody's data,
    it is one constant series per process, and
    `test_build_info_is_this_build_and_one_series` holds it to exactly that."""
    for _ in range(5):
        _complete(registry, routing=PRICED)
    registry.observe_ingest("ingested", byte_count=1)

    payload, _ = registry.render()
    for family in registry.registry.collect():
        if family.name in m.IDENTITY_METRICS:
            continue
        for sample in family.samples:
            for value in sample.labels.values():
                assert not _IDENTIFIER.search(value), f"identifier-shaped label {value!r}"
    assert b"@" not in payload, "an email address reached the exposition"


def test_cardinality_is_invariant_under_load(registry):
    """Fifty runs across a hundred distinct routings add no series.

    The baseline is taken with **every declared label value already touched**, so what this
    measures is the thing that matters: distinct ids and routings create nothing. A
    narrower baseline would fail merely because a later run used an enum value the first
    one had not."""
    for routing in ({"planner": "google:x"}, {"planner": "ollama:x"}, None):
        _complete(registry, routing=routing)
    for status in ("FAILED", "CANCELLED"):
        _persist(registry, status)
    for outcome in m.INGEST_OUTCOMES:
        registry.observe_ingest(outcome, byte_count=1)
    baseline = _series(registry)

    for i in range(50):
        routing = {
            "planner": f"google:model-{uuid.uuid4().hex}",
            "critic": f"custom:{uuid.uuid4().hex}",
        }
        _complete(registry, cost=i, tin=i, tout=i, routing=routing)
        _persist(registry, "FAILED", cost=i, routing=None)
        registry.observe_ingest("ingested", byte_count=i)

    assert _series(registry) == baseline


# ── Cost confidence: the three-valued classification ──────────────────────────────


@pytest.mark.parametrize(
    ("routing", "expected"),
    [
        (None, "unstamped"),
        ({}, "unstamped"),
        ({"planner": "google:gemini-2.5-pro"}, "priced"),
        ({"planner": "anthropic:claude-sonnet-4-5"}, "priced"),
        ({"planner": "openrouter:whatever"}, "unpriced"),
        ({"planner": "custom:whatever"}, "unpriced"),
        # `ollama:qwen2.5:7b` is provider `ollama`, model `qwen2.5:7b` — split on the FIRST
        # colon only. A naive split gets this wrong in the direction that matters: it would
        # report an unpriced local model as priced.
        ({"planner": "ollama:qwen2.5:7b"}, "unpriced"),
        # One unpriced role is enough: the run's total is already incomplete.
        ({"planner": "google:gemini-2.5-pro", "executor": "ollama:qwen2.5:7b"}, "unpriced"),
    ],
)
def test_cost_confidence_classification(routing, expected):
    assert m.cost_confidence(routing) == expected


def test_unstamped_routing_is_never_reported_as_priced(registry):
    """The rule `routing_rules.py` states in prose — never present unpriced or unknown
    spend as a measured figure — expressed as a metric. A run with no routing snapshot ran
    on the deployment default, which this observation point cannot see."""
    _complete(registry, cost=0.0, routing=None)

    assert (
        _value(registry, "research_run_cost_confidence_total", {"confidence": "unstamped"}) == 1.0
    )
    assert _value(registry, "research_run_cost_confidence_total", {"confidence": "priced"}) == 0.0


# ── Terminal means terminal ───────────────────────────────────────────────────────


@pytest.mark.parametrize("status", ["AWAITING_PLAN", "AWAITING_REVIEW"])
def test_a_paused_run_records_nothing(registry, status):
    """A gate is a pause, not an outcome, and `outcome.cost_usd` is cumulative across
    resumes — so recording at a pause would both mislabel the run and double-count its
    spend when it later finishes."""
    before = _series(registry)

    _persist(registry, status)

    assert _series(registry) == before
    assert _value(registry, "research_run_cost_usd_total") == 0.0


def test_an_unknown_status_records_nothing(registry):
    """Fail closed: a status this module does not recognise is not a terminal outcome, and
    must not be invented into one."""
    before = _series(registry)

    _persist(registry, "RUNNING")

    assert _series(registry) == before


def test_the_persistence_adapter_does_not_record_completion(registry):
    """Completion belongs to the approval route, and only there.

    `submit_report_review` sets `run.status = "COMPLETED"` itself; the engine is never
    resumed with `approved=True` for a run (`RunDispatcher.rework` hard-codes `False` on
    both hosts). Should that ever change, this assertion is what stops the same run being
    counted twice — and its failure is the signal to move the observation, not to delete
    the guard."""
    before = _series(registry)

    _persist(registry, "COMPLETED")

    assert _series(registry) == before
    assert _value(registry, "research_run_outcomes_total", {"outcome": "completed"}) == 0.0


@pytest.mark.parametrize(("status", "label"), [("FAILED", "failed"), ("CANCELLED", "cancelled")])
def test_the_persistence_adapter_records_what_it_owns(registry, status, label):
    _persist(registry, status, cost=0.25, tin=10, tout=5)

    assert _value(registry, "research_run_outcomes_total", {"outcome": label}) == 1.0
    assert _value(registry, "research_run_cost_usd_total") == 0.25
    assert _value(registry, "research_run_tokens_total", {"direction": "input"}) == 10.0


def test_a_cancelled_run_still_records_its_spend(registry):
    """Tokens burned between the stop and the pipeline noticing are real, and
    `persist_outcome` already commits them deliberately. Dropping them here would make the
    totals disagree with the rows."""
    _persist(registry, "CANCELLED", cost=0.5)

    assert _value(registry, "research_run_cost_usd_total") == 0.5
    assert _value(registry, "research_run_outcomes_total", {"outcome": "cancelled"}) == 1.0


def test_every_terminal_run_is_classified_for_cost(registry):
    """`sum(cost_confidence) == sum(outcomes)` — the invariant that stops a run being
    counted without its cost figure being characterised."""
    _complete(registry, routing=PRICED)
    _complete(registry, routing=None)
    _persist(registry, "FAILED")
    _persist(registry, "CANCELLED")

    outcomes = sum(
        _value(registry, "research_run_outcomes_total", {"outcome": v})
        for v in m.DECLARED["research_run_outcomes"]["outcome"]
    )
    confidence = sum(
        _value(registry, "research_run_cost_confidence_total", {"confidence": v})
        for v in m.DECLARED["research_run_cost_confidence"]["confidence"]
    )
    assert outcomes == confidence == 4


def test_tokens_are_recorded_by_direction(registry):
    _complete(registry, cost=0.25, tin=1200, tout=340, routing=PRICED)

    assert _value(registry, "research_run_tokens_total", {"direction": "input"}) == 1200.0
    assert _value(registry, "research_run_tokens_total", {"direction": "output"}) == 340.0
    assert _value(registry, "research_run_cost_usd_total") == 0.25


def test_decimal_run_values_are_accepted(registry):
    """`research_runs.cost_usd` is `Numeric(12, 6)`, so the approval route hands this a
    `Decimal`, not a float."""
    from decimal import Decimal

    _complete(registry, cost=Decimal("0.000315"), tin=1400, tout=700, routing=PRICED)

    assert _value(registry, "research_run_cost_usd_total") == pytest.approx(0.000315)


# ── Ingest ────────────────────────────────────────────────────────────────────────


def test_ingest_counts_documents_and_indexed_bytes(registry):
    registry.observe_ingest("ingested", byte_count=2048)
    registry.observe_ingest("skipped", byte_count=99)

    assert _value(registry, "corpus_ingest_documents_total", {"outcome": "ingested"}) == 1.0
    assert _value(registry, "corpus_ingest_documents_total", {"outcome": "skipped"}) == 1.0
    assert _value(registry, "corpus_ingest_bytes_total") == 2048.0, (
        "bytes counts what was indexed, so a skipped upload must not inflate throughput"
    )


# ── Exposition ────────────────────────────────────────────────────────────────────


def test_render_answers_the_prometheus_text_content_type(registry):
    payload, content_type = registry.render()

    assert content_type.startswith("text/plain")
    assert b"# TYPE research_run_outcomes_total counter" in payload
