"""Pure retrieval-quality metrics. No I/O, no models, no embeddings.

Separated from `evals/retrieval.py` for the reason `evals/metrics.py` is separated from
`evals/harness.py`: a number that decides whether a retrieval change ships has to be
unit-testable without a corpus, an embedder or a network.

**Granularity is document-level, and that is a finding rather than a convenience.**
`CorpusStore._search_sync` returns *at most one hit per document* — two chunks of one file
are not two independent sources, and the synthesizer counts URLs. Scoring gold at chunk
level would therefore cap recall below 1.0 for a retriever behaving exactly as designed,
which would misreport the thing being measured. Whether the right *span* inside a document
came back is a real question too, so it is measured separately as `span_accuracy` rather
than folded in here.

Every function returns `None` where it could not measure, never `0.0`. The distinction is
the same one `research_engine.citation_rate` and `evals.harness.judge_citation_support`
make, and for the same reason: a query with no gold documents and a query whose gold was
entirely missed are opposite findings.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

#: Bumped whenever a definition below changes. Results carry it, and two runs with
#: different versions are not comparable — the rule `evals/metrics.py` already states.
RETRIEVAL_METRICS_VERSION = 1

#: Graded relevance. 2 answers the query directly, 1 is related context, 0 is irrelevant.
#: Used by nDCG; recall and precision treat anything >= 1 as relevant.
RELEVANT_THRESHOLD = 1


def recall_at_k(retrieved: Sequence[str], gold: Sequence[str], k: int) -> float | None:
    """Fraction of gold documents present in the top `k` results.

    `None` when the query declares no gold documents: there is nothing to recall, which is
    not the same as recalling nothing.
    """
    if not gold:
        return None
    top = set(retrieved[:k])
    return len([g for g in set(gold) if g in top]) / len(set(gold))


def precision_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float | None:
    """Fraction of the top `k` results that are relevant — the plan's `evidence_precision`.

    The plan words this as "retrieved passages judged as supporting the task". The judgment
    here is the dataset's human label rather than a model's opinion, which is both cheaper
    and more reproducible; an LLM judge would make the baseline non-deterministic, and a
    baseline that moves on its own cannot be used to detect a regression.

    `None` when nothing was retrieved — precision over an empty result set is undefined,
    and reporting 0.0 would blame the ranking for a retriever that returned nothing.
    """
    top = list(retrieved[:k])
    if not top:
        return None
    relevant_set = set(relevant)
    return len([d for d in top if d in relevant_set]) / len(top)


def ndcg_at_k(retrieved: Sequence[str], grades: dict[str, int], k: int) -> float | None:
    """Normalised discounted cumulative gain over graded relevance.

    Gain is `2**rel - 1` so a directly-answering document outweighs two loosely related
    ones, and the discount is `log2(rank + 1)` — the standard formulation, stated here
    because a different gain function silently produces a different, incomparable number.

    `None` when no graded document exists, for the same reason as `recall_at_k`.
    """
    ideal_grades = sorted((g for g in grades.values() if g > 0), reverse=True)
    if not ideal_grades:
        return None

    def dcg(gains: Sequence[int]) -> float:
        return sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(gains))

    actual = [grades.get(doc_id, 0) for doc_id in retrieved[:k]]
    ideal = ideal_grades[:k]
    best = dcg(ideal)
    return dcg(actual) / best if best else None


def dedup_rate(retrieved: Sequence[str], duplicate_groups: Sequence[Sequence[str]]) -> float | None:
    """Fraction of duplicate groups from which at most one member was returned.

    The plan defines this as "duplicate passages removed / duplicates present". A group is
    a set of documents the dataset declares to hold the same content; retrieval collapsed
    that group if it surfaced no more than one of them.

    This measures a gap on purpose. `_search_sync` collapses chunks *within* a document,
    so intra-document redundancy is already handled; the same article ingested as two
    files is not collapsed at all, which `docs/01` states as a known limit and A3 targets.
    A baseline near 0.0 here is the honest starting point, not a bug in the metric.

    `None` when the dataset declares no duplicate groups reachable by this query.
    """
    present = [g for g in duplicate_groups if len(set(g)) > 1]
    if not present:
        return None
    top = list(retrieved)
    collapsed = sum(1 for group in present if len([d for d in top if d in set(group)]) <= 1)
    return collapsed / len(present)


def span_accuracy(hits: Sequence[dict], expected_spans: dict[str, list[int]]) -> float | None:
    """Of the gold documents returned, how many returned a span overlapping the gold span.

    Kept apart from `recall_at_k` deliberately: recall asks whether the right *document*
    was found, this asks whether the right *part* of it came back. Folding them together
    would let a retriever that finds every document but quotes the wrong paragraph score
    identically to one that quotes the right one — and the snippet is what becomes
    evidence, so the difference is the product's whole claim.

    `None` when no gold document was retrieved at all; there is nothing to locate within.
    """
    checked = [h for h in hits if h["doc_id"] in expected_spans]
    if not checked:
        return None
    hit = 0
    for h in checked:
        want_start, want_end = expected_spans[h["doc_id"]]
        # Any overlap counts: chunk boundaries are a property of the chunker, not of the
        # answer, so demanding an exact span would measure `chunk_document` instead.
        if h["start"] < want_end and want_start < h["end"]:
            hit += 1
    return hit / len(checked)


def mean_or_none(values: Sequence[float | None]) -> float | None:
    """Average the measured values, ignoring the unmeasured ones; `None` if none measured.

    The aggregation half of the unmeasured rule. Treating `None` as 0.0 here would let one
    unmeasurable query drag a corpus-wide number down and read as a quality collapse —
    the exact conflation `AGENTS.md` calls a P0.
    """
    measured = [v for v in values if v is not None]
    if not measured:
        return None
    return sum(measured) / len(measured)
