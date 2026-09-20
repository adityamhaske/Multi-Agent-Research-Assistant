"""The retrieval metrics compute what they claim, on cases with a hand-checkable answer.

A number that decides whether a retrieval change ships has to be trustworthy before the
retrieval change exists. These are synthetic ranked lists with arithmetic anyone can redo
on paper — no corpus, no embedder, no network — so a metric that quietly starts scoring
something else fails here rather than in a baseline nobody re-derives.

The `None` cases are not edge-case housekeeping. `AGENTS.md` calls unmeasured-reported-as-
zero a P0, and every one of these functions has a path where returning 0.0 would report a
quality collapse that did not happen.
"""

from __future__ import annotations

import math

from evals.retrieval_metrics import (
    dedup_rate,
    mean_or_none,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    span_accuracy,
)

# ── recall ────────────────────────────────────────────────────────────────────────


def test_recall_counts_gold_documents_inside_the_cut():
    assert recall_at_k(["a", "b", "c"], ["a", "c"], 3) == 1.0
    assert recall_at_k(["a", "b", "c"], ["a", "c"], 2) == 0.5
    assert recall_at_k(["b", "d"], ["a", "c"], 5) == 0.0


def test_recall_is_none_when_the_query_declares_no_gold():
    """Nothing to recall is not the same as recalling nothing."""
    assert recall_at_k(["a"], [], 5) is None


def test_recall_does_not_double_count_a_repeated_gold_document():
    assert recall_at_k(["a", "a", "a"], ["a", "b"], 3) == 0.5


# ── precision ─────────────────────────────────────────────────────────────────────


def test_precision_is_measured_over_what_was_returned():
    assert precision_at_k(["a", "b", "c", "d"], ["a", "c"], 4) == 0.5
    assert precision_at_k(["a", "b"], ["a", "b"], 2) == 1.0


def test_precision_is_none_when_nothing_was_returned():
    """0.0 would blame the ranking for a retriever that returned nothing at all."""
    assert precision_at_k([], ["a"], 5) is None


def test_precision_at_five_is_capped_by_how_many_relevant_documents_exist():
    """Documents the harness's own comment: with one relevant document, precision@5
    cannot exceed 0.2 however perfect the ranking. This is why precision@1 is reported
    beside it rather than instead of it."""
    assert precision_at_k(["a", "b", "c", "d", "e"], ["a"], 5) == 0.2
    assert precision_at_k(["a", "b", "c", "d", "e"], ["a"], 1) == 1.0


# ── nDCG ──────────────────────────────────────────────────────────────────────────


def test_ndcg_is_one_for_the_ideal_ordering():
    grades = {"a": 2, "b": 1}
    assert ndcg_at_k(["a", "b"], grades, 10) == 1.0


def test_ndcg_penalises_a_swapped_ordering_by_the_documented_formula():
    """Hand-checkable: gains 2**rel - 1 are 3 and 1, discounts log2(2) and log2(3)."""
    grades = {"a": 2, "b": 1}
    ideal = 3 / math.log2(2) + 1 / math.log2(3)
    swapped = 1 / math.log2(2) + 3 / math.log2(3)
    assert ndcg_at_k(["b", "a"], grades, 10) == swapped / ideal


def test_ndcg_ignores_irrelevant_documents_rather_than_crediting_them():
    grades = {"a": 2}
    assert ndcg_at_k(["a", "zzz"], grades, 10) == 1.0


def test_ndcg_is_none_when_nothing_is_graded_relevant():
    assert ndcg_at_k(["a"], {"a": 0}, 10) is None


# ── dedup ─────────────────────────────────────────────────────────────────────────


def test_dedup_rate_counts_groups_that_were_collapsed():
    groups = [["a", "a2"], ["b", "b2"]]
    assert dedup_rate(["a", "b"], groups) == 1.0
    assert dedup_rate(["a", "a2", "b"], groups) == 0.5
    assert dedup_rate(["a", "a2", "b", "b2"], groups) == 0.0


def test_dedup_rate_ignores_a_group_with_only_one_member():
    """A one-document 'group' has no duplicate to remove, so counting it as collapsed
    would inflate the rate with cases that could not have failed."""
    assert dedup_rate(["a"], [["a"]]) is None


def test_dedup_rate_is_none_when_no_duplicates_are_reachable():
    assert dedup_rate(["a", "b"], []) is None


# ── span accuracy ─────────────────────────────────────────────────────────────────


def test_span_accuracy_accepts_any_overlap_with_the_labelled_passage():
    """Chunk boundaries belong to the chunker, not the answer. Demanding an exact span
    would measure `chunk_document` instead of retrieval."""
    hits = [{"doc_id": "a", "start": 90, "end": 200}]
    assert span_accuracy(hits, {"a": [100, 150]}) == 1.0


def test_span_accuracy_rejects_a_disjoint_span():
    hits = [{"doc_id": "a", "start": 0, "end": 50}]
    assert span_accuracy(hits, {"a": [100, 150]}) == 0.0


def test_span_accuracy_only_scores_documents_it_has_a_label_for():
    hits = [
        {"doc_id": "a", "start": 100, "end": 150},
        {"doc_id": "unlabelled", "start": 0, "end": 9},
    ]
    assert span_accuracy(hits, {"a": [100, 150]}) == 1.0


def test_span_accuracy_is_none_when_no_labelled_document_came_back():
    assert span_accuracy([{"doc_id": "b", "start": 0, "end": 9}], {"a": [0, 5]}) is None


# ── aggregation ───────────────────────────────────────────────────────────────────


def test_the_mean_skips_unmeasured_values_rather_than_scoring_them_zero():
    """The aggregation half of the unmeasured rule. Treating None as 0.0 here lets one
    unmeasurable query read as a corpus-wide quality collapse."""
    assert mean_or_none([1.0, None, 0.0]) == 0.5
    assert mean_or_none([None, None]) is None
    assert mean_or_none([]) is None
