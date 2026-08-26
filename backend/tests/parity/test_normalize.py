"""
The normalizer, which is the load-bearing part of the parity suite.

A parity suite is only worth what its normalizer refuses to discard. `AGENTS.md` records
the shape of the failure: `test_corpus_egress` asserted zero network calls while injecting
a fake embedder, so the suite was green because it had replaced the defect. The same trap
here would be a normalizer that quietly drops any field the two hosts disagree about —
every journey would pass and nothing would be measured.

So the rule these tests pin is: **a value may be redacted, a key never is.** A uuid becomes
`<uuid>`; the key it sat under stays, and `==` on the two dicts still catches a host that
omitted it entirely. And redaction is *shape-aware* — a key on the redaction list whose
value does not look volatile is left alone, because "the server sent a uuid and the desktop
sent the string 'skip'" is exactly the kind of difference this suite exists to find.
"""

from __future__ import annotations

from tests.parity.normalize import normalize, observe


class _Resp:
    """The two attributes `observe` reads. Real `httpx.Response` objects satisfy it."""

    def __init__(self, status_code: int, payload=None, text: str = "", ctype="application/json"):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = {"content-type": ctype}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


# ── Redaction replaces values, never keys ─────────────────────────────────────────


def test_a_uuid_under_an_id_key_is_redacted_but_the_key_survives():
    assert normalize({"id": "6f1b2c3d-4e5f-4a7b-8c9d-0e1f2a3b4c5d"}) == {"id": "<uuid>"}


def test_a_missing_key_is_still_a_difference_after_normalization():
    """The property the whole suite rests on: normalization must not make two different
    response shapes compare equal."""
    server = normalize({"id": "6f1b2c3d-4e5f-4a7b-8c9d-0e1f2a3b4c5d", "origin": "uploaded"})
    desktop = normalize({"id": "0e1f2a3b-4c5d-4e5f-8a7b-6f1b2c3d4e5f"})
    assert server != desktop


def test_a_null_id_is_not_redacted_into_a_present_one():
    """A host that returns `null` where the other returns an id has a real difference."""
    assert normalize({"id": None}) == {"id": None}
    assert normalize({"id": None}) != normalize({"id": "6f1b2c3d-4e5f-4a7b-8c9d-0e1f2a3b4c5d"})


def test_an_id_key_holding_something_that_is_not_an_id_is_left_alone():
    """`app/api/v1/corpus.py::upload_document` really does return `id="skip"` when the
    store skipped the document. Redacting it by key name would erase that."""
    assert normalize({"id": "skip"}) == {"id": "skip"}


def test_a_timestamp_is_redacted_and_a_non_timestamp_under_the_same_key_is_not():
    assert normalize({"created_at": "2026-08-26T12:00:00Z"}) == {"created_at": "<timestamp>"}
    assert normalize({"created_at": "never"}) == {"created_at": "never"}


def test_an_unknown_key_keeps_its_value_verbatim():
    assert normalize({"status": "AWAITING_APPROVAL", "chunks": 7}) == {
        "status": "AWAITING_APPROVAL",
        "chunks": 7,
    }


# ── Structure ─────────────────────────────────────────────────────────────────────


def test_nested_structures_are_normalized_recursively():
    got = normalize(
        {
            "runs": [
                {"id": "6f1b2c3d-4e5f-4a7b-8c9d-0e1f2a3b4c5d", "status": "COMPLETED"},
                {"id": "0e1f2a3b-4c5d-4e5f-8a7b-6f1b2c3d4e5f", "status": "FAILED"},
            ]
        }
    )
    assert got == {
        "runs": [{"id": "<uuid>", "status": "COMPLETED"}, {"id": "<uuid>", "status": "FAILED"}]
    }


def test_list_order_is_preserved_because_task_order_is_meaning():
    assert normalize([{"title": "b"}, {"title": "a"}]) == [{"title": "b"}, {"title": "a"}]


# ── Free text ─────────────────────────────────────────────────────────────────────


def test_report_markdown_is_reduced_to_a_shape_not_discarded():
    """A generated report differs run to run even in fake mode. Comparing the prose would
    be noise; dropping the field would hide a host that produced no report at all. So it
    reduces to something both measurable and stable: whether there is text, and which
    citation markers it carries."""
    assert normalize({"final_report": "Recall rose [1]. Also [2].\n\n## Sources\n1. x"}) == {
        "final_report": {"empty": False, "markers": [1, 2]}
    }
    assert normalize({"final_report": ""}) == {"final_report": {"empty": True, "markers": []}}
    assert normalize({"final_report": None}) == {"final_report": None}


# ── observe() ─────────────────────────────────────────────────────────────────────


def test_observe_records_the_status_code_alongside_the_body():
    assert observe(_Resp(201, {"id": "skip"})) == {"status": 201, "body": {"id": "skip"}}


def test_observe_keeps_an_error_detail_because_error_contracts_are_contracts():
    assert observe(_Resp(409, {"detail": "Session is not AWAITING_APPROVAL."})) == {
        "status": 409,
        "body": {"detail": "Session is not AWAITING_APPROVAL."},
    }


def test_observe_records_a_non_json_body_as_its_media_type_and_emptiness():
    resp = _Resp(200, None, text="# Findings\n", ctype="text/markdown; charset=utf-8")
    assert observe(resp) == {
        "status": 200,
        "body": {"media_type": "text/markdown", "empty": False},
    }


# ── What the harness pins, the normalizer must NOT redact ─────────────────────────
#
# Revision 2 of the plan (constraint 15) pins the same `MODEL_*` routing and injects the
# same deterministic embedder on BOTH hosts. Everything that pinning makes reproducible
# therefore has to be compared exactly — reducing it "just in case" would discard the
# product-visible state the suite exists to measure. A reduction is only honest where a
# host difference is genuine and deliberate.


def test_spend_is_compared_exactly_because_both_hosts_run_pinned_models():
    """Rounding a cost to a zero/positive class would hide a run that spent differently on
    one host — and spend is the number this repository treats as honesty-critical."""
    assert normalize({"total_cost_usd": 0.0031}) == {"total_cost_usd": 0.0031}
    assert normalize({"cost_usd": 0.0}) == {"cost_usd": 0.0}


def test_token_counts_are_compared_exactly_for_the_same_reason():
    assert normalize({"total_tokens_input": 812}) == {"total_tokens_input": 812}


def test_model_routing_is_compared_exactly_not_reduced_to_its_roles():
    """Which model each role actually dialled is the product's own attribution claim. The
    harness pins routing on both hosts, so a difference here is a defect, not noise."""
    routing = {"planner": "google:gemini-2.5-flash", "critic": "google:gemini-2.5-flash"}
    assert normalize({"model_routing": routing}) == {"model_routing": routing}


def test_a_null_routing_snapshot_is_not_the_same_as_an_empty_one():
    """`sidecar._drive_session` exists because every desktop session used to persist a null
    routing for a decision that had really been made. Normalization must not hide that."""
    assert normalize({"model_routing": None}) != normalize({"model_routing": {}})


def test_chunks_by_model_is_compared_exactly_because_the_embedder_is_pinned_too():
    """The embedder is a port with a real host difference — hosted on the server, local on
    the desktop. The harness injects the same deterministic one on both, which is what
    makes the corpus's own record of which model wrote each chunk comparable."""
    counts = {"fake:parity-embed": 12}
    assert normalize({"chunks_by_model": counts}) == {"chunks_by_model": counts}


def test_duration_is_still_redacted_because_nothing_can_pin_wall_clock():
    assert normalize({"elapsed_seconds": 4.21}) == {"elapsed_seconds": "<measure>"}


# ── Content hashes ────────────────────────────────────────────────────────────────


def test_a_content_hash_is_redacted_because_it_is_computed_over_host_assigned_ids():
    """A bundle hash covers a document containing run, revision and evidence ids, so its
    value cannot be equal across hosts however deterministic the pipeline is. Presence is
    still the contract — and the verifier's own integrity checks, which each host runs
    against its own bundle, are what prove the hash is right."""
    digest = "1f1fccb8ed6e4d863bd61cb9b2abcc38f71d88ea0aad29bb101c16d9782b60bb"
    assert normalize({"bundle_hash": digest}) == {"bundle_hash": "<hash>"}
    assert normalize({"report_hash": digest, "content_hash": digest}) == {
        "report_hash": "<hash>",
        "content_hash": "<hash>",
    }


def test_a_missing_hash_is_not_the_same_as_a_present_one():
    assert normalize({"bundle_hash": None}) != normalize(
        {"bundle_hash": "1f1fccb8ed6e4d863bd61cb9b2abcc38f71d88ea0aad29bb101c16d9782b60bb"}
    )


def test_something_under_a_hash_key_that_is_not_a_digest_survives():
    """A host answering `"unavailable"` where the other answers a digest is a difference,
    not a formatting detail."""
    assert normalize({"bundle_hash": "unavailable"}) == {"bundle_hash": "unavailable"}


# ── The id rule is structural, not a list someone has to keep guessing at ─────────


def test_any_key_ending_in_id_that_holds_a_uuid_is_redacted():
    """`plan_version_id` was not on the hand-written list, so a raw uuid reached the golden
    and the server disagreed with its own recording. A list of id keys is a list that will
    always be one field behind the schema."""
    assert normalize({"plan_version_id": "6f1b2c3d-4e5f-4a7b-8c9d-0e1f2a3b4c5d"}) == {
        "plan_version_id": "<uuid>"
    }


def test_a_key_ending_in_id_that_holds_a_name_is_left_alone():
    """`model_id` ends in `_id` and holds `claude-haiku-4-5`, which is the contract itself.
    Shape-awareness is what makes the structural rule safe to apply this widely."""
    assert normalize({"model_id": "claude-haiku-4-5"}) == {"model_id": "claude-haiku-4-5"}
    assert normalize({"task_id": "1"}) == {"task_id": "1"}


def test_any_key_ending_in_at_that_holds_an_instant_is_redacted():
    """Same lesson as the id rule: `archived_at` and `generated_at` were each missing in
    turn. The suffix is the schema's own convention, so match on it."""
    assert normalize({"generated_at": "2026-08-26T12:00:00Z"}) == {"generated_at": "<timestamp>"}
    assert normalize({"assembled_at": "2026-08-26T12:00:00"}) == {"assembled_at": "<timestamp>"}


def test_a_bare_timestamp_key_is_redacted_too():
    """`approval_chain[].timestamp` in the bundle does not use the `_at` convention."""
    assert normalize({"timestamp": "2026-08-26T20:20:37"}) == {"timestamp": "<timestamp>"}


def test_any_key_ending_in_hash_that_holds_a_digest_is_redacted():
    assert normalize(
        {"artifact_hash": "7168de26bcdb08fc099684abd50effbde802972cd2e7fa5813a70b1408e59952"}
    ) == {"artifact_hash": "<hash>"}


def test_a_key_ending_in_at_that_is_not_an_instant_survives():
    assert normalize({"looked_at": "the report"}) == {"looked_at": "the report"}


# ── The event trace ───────────────────────────────────────────────────────────────


def test_a_bundle_trace_reduces_to_whether_it_exists():
    """The trace is written by the `EventSink` port, and the harness substitutes that port
    on the server — so comparing the events would compare the test double, not the product.
    What survives is the load-bearing claim: a bundle that says `trace_available` must
    actually carry one."""
    assert normalize({"trace": [{"type": "agent_log", "message": "x"}]}) == {
        "trace": {"empty": False}
    }
    assert normalize({"trace": []}) == {"trace": {"empty": True}}


def test_an_absent_trace_is_not_the_same_as_an_empty_one():
    assert normalize({"trace": None}) != normalize({"trace": []})
