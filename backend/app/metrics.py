"""
Operational counters, and the closed vocabulary they are allowed to carry.

A sibling of `app/logconfig.py` and the same kind of module: process-wide observability,
imported by both hosts, reaching no infrastructure. It imports `prometheus_client` and two
dependency-free engine modules and nothing else — `corpus_ingest.py` is a domain module the
packaged sidecar imports, so anything reachable from here reaches the desktop bundle.

**A private registry, not the library's global default.** `prometheus_client.REGISTRY` is a
process-wide collector any imported package may write to. Rendering it would put series on
an unauthenticated endpoint that this repository never declared and cannot vouch for, and
would make the exposition depend on import order. `Metrics` owns its own registry, which is
also what lets a test observe its own increments and nobody else's.

**Two recording functions, because a run has two terminal boundaries.** A run reaches
COMPLETED at the approval route — `submit_report_review` sets the status and freezes the
artifact in one transaction, and the engine is never resumed with `approved=True` because
`RunDispatcher.rework` hard-codes `False` on both hosts. FAILED and CANCELLED arrive at
`run_execution.persist_outcome`. Instrumenting one of those and assuming it saw the other
is how a counter ends up permanently zero, so each boundary has a function that names it.

**No run-duration metric.** `runner._outcome` sets `elapsed_seconds` only on its `completed`
branch, which the runs pipeline never reaches, so the column is NULL on every run and every
bundle — there is no measured compute duration in this product to expose. Deriving one from
`created_at` would measure how long the reviewer took, which is a different quantity wearing
the same name. Recorded as deferred debt rather than invented here.

**Every label value comes from a closed table in this file.** No identifier, filename, URL,
question or error message can reach `.labels()`, which is what bounds the cardinality of a
permanently exposed endpoint and keeps research content off it.
"""

from __future__ import annotations

from collections.abc import Mapping

import prometheus_client
from prometheus_client import CollectorRegistry, Counter, Gauge

from research_engine.build_info import build_info
from research_engine.routing_rules import ENDPOINT_DEFINED_PROVIDERS

#: A run that finished. `AWAITING_PLAN` and `AWAITING_REVIEW` are pauses and are absent on
#: purpose: a gate is not an outcome, and `RunOutcome`'s spend is cumulative across resumes,
#: so counting at a pause would both mislabel the run and double-count its dollars.
RUN_OUTCOMES = ("completed", "failed", "cancelled")

#: How much this run's recorded cost can be trusted. Three values rather than a boolean,
#: because "priced or not" is not exhaustive: `research_runs.model_routing` is NULL whenever
#: the request named no routing, and the deployment default that applied instead is not
#: visible from a module that may not read `app.config`.
COST_CONFIDENCE = ("priced", "unpriced", "unstamped")

TOKEN_DIRECTIONS = ("input", "output")

#: What one upload did. `skipped` is a success the store reports for a document it already
#: holds; `rejected` is the caller's mistake and `unavailable` is not — the distinction
#: `corpus_ingest` already draws for the client, kept here so an operator sees the same one.
INGEST_OUTCOMES = ("ingested", "skipped", "rejected", "unavailable")

#: The whole contract: metric family → label name → the values that label may take.
#:
#: Keys are the family names `prometheus_client` reports, which for a counter is the name
#: **without** its `_total` suffix — `Counter("x_total", …)` collects as family `x` and
#: exposes sample `x_total`. Tests compare against `collect()`, so the keys follow it.
DECLARED: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    "research_run_outcomes": {"outcome": RUN_OUTCOMES},
    "research_run_cost_usd": {},
    "research_run_cost_confidence": {"confidence": COST_CONFIDENCE},
    "research_run_tokens": {"direction": TOKEN_DIRECTIONS},
    "corpus_ingest_documents": {"outcome": INGEST_OUTCOMES},
    "corpus_ingest_bytes": {},
    "research_build_info": {"version": (), "git_sha": ()},
}

#: The one family whose labels are not an enum. They are this build's own identity, so the
#: bound is that a process is one build — a single series — rather than a list of values.
IDENTITY_METRICS = frozenset({"research_build_info"})

#: `PersistResult.status` → the outcome label, for the two terminal states that boundary
#: owns. COMPLETED is deliberately absent: completion is the approval route's to record, and
#: leaving it out here is what makes exactly-once structural rather than a coincidence. If a
#: run ever reaches COMPLETED through the engine instead, this table is what has to change —
#: `test_the_persistence_adapter_does_not_record_completion` is the alarm.
_PERSISTED_TERMINAL = {"FAILED": "failed", "CANCELLED": "cancelled"}


def cost_confidence(model_routing: Mapping[str, str] | None) -> str:
    """How far `research_run_cost_usd_total` can be trusted for this run.

    `estimate_cost()` returns `0.0` for the endpoint-defined providers, so their spend is
    real and unrecorded — `routing_rules` states the rule in prose ("never render an
    unpriced run's cost as a measured `$0.00`") and this is that rule as a number.

    Split on the **first** colon only: `ollama:qwen2.5:7b` is provider `ollama`, and a naive
    split would misread it as priced, which is the direction that misleads.
    """
    if not model_routing:
        return "unstamped"
    for route in model_routing.values():
        if str(route).partition(":")[0] in ENDPOINT_DEFINED_PROVIDERS:
            return "unpriced"
    return "priced"


class Metrics:
    """One registry and the seven families it carries.

    A class rather than module-level collectors so a test can hold an isolated instance;
    production uses the module-level `_default` through the functions below.
    """

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self._outcomes = Counter(
            "research_run_outcomes_total",
            "Research runs that reached a terminal state, by outcome. Counts finished runs, "
            "not started ones: a run waiting at a gate is not counted until it terminates.",
            ["outcome"],
            registry=self.registry,
        )
        self._cost = Counter(
            "research_run_cost_usd_total",
            "Estimated spend of terminated research runs, in USD. Under-reports whenever "
            'research_run_cost_confidence_total{confidence!="priced"} is moving: cost '
            "estimation returns 0 for endpoint-defined providers. Cap spend at the provider.",
            registry=self.registry,
        )
        self._confidence = Counter(
            "research_run_cost_confidence_total",
            "Terminated runs by how far their recorded cost can be trusted. 'unstamped' "
            "means the run carried no routing snapshot, so this is unknown rather than fine.",
            ["confidence"],
            registry=self.registry,
        )
        self._tokens = Counter(
            "research_run_tokens_total",
            "Tokens attributed to terminated research runs, by direction.",
            ["direction"],
            registry=self.registry,
        )
        self._ingest = Counter(
            "corpus_ingest_documents_total",
            "Corpus upload attempts by what happened to them.",
            ["outcome"],
            registry=self.registry,
        )
        self._ingest_bytes = Counter(
            "corpus_ingest_bytes_total",
            "Bytes actually indexed into a corpus. A skipped or refused upload indexed "
            "nothing and does not count here.",
            registry=self.registry,
        )
        info = build_info()
        Gauge(
            "research_build_info",
            "Which build is answering. Always 1; the labels carry the value.",
            ["version", "git_sha"],
            registry=self.registry,
        ).labels(version=info.version, git_sha=info.git_sha).set(1)

    # ── Runs ──────────────────────────────────────────────────────────────────────

    def observe_completed_run(
        self,
        *,
        cost_usd,
        tokens_input: int,
        tokens_output: int,
        model_routing: Mapping[str, str] | None,
    ) -> None:
        """A run the reviewer approved. Called from `submit_report_review`."""
        self._record_terminal(
            "completed",
            cost_usd=cost_usd,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            model_routing=model_routing,
        )

    def observe_persisted_run(
        self,
        status: str,
        *,
        cost_usd,
        tokens_input: int,
        tokens_output: int,
        model_routing: Mapping[str, str] | None,
    ) -> None:
        """What `persist_outcome` wrote. Anything that is not one of its two terminal
        states — a gate, a status this module does not know — records nothing."""
        outcome = _PERSISTED_TERMINAL.get(status)
        if outcome is None:
            return
        self._record_terminal(
            outcome,
            cost_usd=cost_usd,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            model_routing=model_routing,
        )

    def _record_terminal(
        self, outcome: str, *, cost_usd, tokens_input, tokens_output, model_routing
    ) -> None:
        """One terminal run. Spend and its confidence move together, always — a counted run
        whose cost figure went uncharacterised is how `$0.00` starts reading as free."""
        self._outcomes.labels(outcome=outcome).inc()
        # `research_runs.cost_usd` is Numeric, so the approval route hands over a Decimal.
        self._cost.inc(float(cost_usd or 0))
        self._confidence.labels(confidence=cost_confidence(model_routing)).inc()
        self._tokens.labels(direction="input").inc(int(tokens_input or 0))
        self._tokens.labels(direction="output").inc(int(tokens_output or 0))

    # ── Corpus ────────────────────────────────────────────────────────────────────

    def observe_ingest(self, outcome: str, *, byte_count: int = 0) -> None:
        """One upload attempt. `byte_count` is counted only for a document that was indexed.

        Refuses an undeclared outcome rather than passing it to `.labels()`: the call sites
        pass literals, so this cannot fire at runtime, and it is what stops a future caller
        turning a message or a filename into a label.
        """
        if outcome not in INGEST_OUTCOMES:
            raise ValueError(f"unknown ingest outcome {outcome!r}; declared: {INGEST_OUTCOMES}")
        self._ingest.labels(outcome=outcome).inc()
        if outcome == "ingested":
            self._ingest_bytes.inc(byte_count)

    # ── Exposition ────────────────────────────────────────────────────────────────

    def render(self) -> tuple[bytes, str]:
        """The scrape payload and its content type."""
        return (
            prometheus_client.generate_latest(self.registry),
            prometheus_client.CONTENT_TYPE_LATEST,
        )


_default = Metrics()


def observe_completed_run(
    *, cost_usd, tokens_input: int, tokens_output: int, model_routing: Mapping[str, str] | None
) -> None:
    _default.observe_completed_run(
        cost_usd=cost_usd,
        tokens_input=tokens_input,
        tokens_output=tokens_output,
        model_routing=model_routing,
    )


def observe_persisted_run(
    status: str,
    *,
    cost_usd,
    tokens_input: int,
    tokens_output: int,
    model_routing: Mapping[str, str] | None,
) -> None:
    _default.observe_persisted_run(
        status,
        cost_usd=cost_usd,
        tokens_input=tokens_input,
        tokens_output=tokens_output,
        model_routing=model_routing,
    )


def observe_ingest(outcome: str, *, byte_count: int = 0) -> None:
    _default.observe_ingest(outcome, byte_count=byte_count)


def render() -> tuple[bytes, str]:
    return _default.render()
