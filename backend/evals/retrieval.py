"""Retrieval-quality baseline (V2.1-a A2), measured against the real corpus retriever.

`docs/01`, `docs/10`, `docs/21` and `docs/33` all say retrieval quality is the ceiling on
report quality. Until now nothing measured it: a repository-wide search for `recall@` or
`ndcg` returned nothing. This harness is the gate A3 has to clear — no retrieval change
merges without a measured, committed result on either side of it.

**It measures; it does not rank.** Nothing here imports or reimplements a scorer. Queries
go through `CorpusStore.search`, the same call the executor makes, so what is measured is
production behaviour rather than a copy of it.

**A real embedder is required, and its absence is reported rather than filled in.**
`FakeEmbeddings` hashes text with blake2b: deterministic, and carrying no semantic signal
whatsoever. Recall computed over hash vectors would be a number with no meaning attached,
which is worse than no number — so when no embedding endpoint is reachable this harness
refuses and records `"status": "unmeasured"` with the reason. That is the same rule
`judge_citation_support` and `citation_rate.resolution_rate` follow, applied one level up.

    python -m evals.retrieval                    # measure, print, do not write
    python -m evals.retrieval --write            # also record a write-once result file

Environment: `OLLAMA_BASE_URL` (default http://localhost:11434/v1) and
`CORPUS_EMBEDDINGS_MODEL` (default nomic-embed-text) — the same two the desktop host reads,
so the baseline is taken on the embedder the product actually ships with.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from evals.retrieval_metrics import (
    RETRIEVAL_METRICS_VERSION,
    dedup_rate,
    mean_or_none,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    span_accuracy,
)
from research_engine.corpus import CorpusStore, parse_corpus_url
from research_engine.embeddings import LocalEmbeddings

DATASET_DIR = Path(__file__).resolve().parent / "datasets" / "retrieval"
RESULTS_DIR = Path(__file__).resolve().parent / "results"

#: Requested result count. Larger than the fixture corpus on purpose: nDCG@10 must be able
#: to see everything the retriever was willing to return, and truncating at the corpus size
#: would measure the dataset instead of the ranking.
TOP_K = 10

#: The k values reported for recall. 5 is what a run actually consumes
#: (`RunConfig.retrieval_k` defaults to 5); 1 and 3 are where ranking quality shows.
#: `@10` is deliberately absent: with a corpus this size it returns almost everything and
#: reads 1.000 for any retriever, which is a saturated number rather than a good one.
RECALL_KS = (1, 3, 5)

#: Precision is reported at two depths on purpose. `@5` is capped by how many relevant
#: documents a query has — a query with one relevant document cannot exceed 0.2 — so it
#: measures the dataset as much as the ranking. `@1` has no such cap and answers the
#: question a reader actually cares about: was the first thing returned worth reading.
PRECISION_KS = (1, 5)


class Unmeasurable(RuntimeError):
    """No honest measurement is possible. Never caught and turned into a zero."""


def dataset_fingerprint() -> str:
    """SHA-256 over every dataset byte, so a result names the data that produced it.

    Sorted by path, content only — a rename that preserves content deliberately changes
    the fingerprint, because a filename is a document identity in `duplicate_groups`.
    """
    h = hashlib.sha256()
    for path in sorted(DATASET_DIR.rglob("*")):
        if path.is_file():
            h.update(path.relative_to(DATASET_DIR).as_posix().encode())
            h.update(path.read_bytes())
    return h.hexdigest()


def load_dataset() -> dict[str, Any]:
    data = json.loads((DATASET_DIR / "queries.json").read_text())
    corpus = {p.name: p.read_text() for p in sorted((DATASET_DIR / "corpus").glob("*.md"))}
    if not corpus:
        raise Unmeasurable(f"no fixture documents under {DATASET_DIR / 'corpus'}")

    # Resolve each verbatim anchor to offsets now, so a dataset whose prose drifted from
    # its labels fails loudly here rather than quietly scoring span accuracy against a
    # span that no longer exists.
    for query in data["queries"]:
        spans: dict[str, list[int]] = {}
        for name, anchor in query.get("span_anchor", {}).items():
            start = corpus[name].find(anchor)
            if start < 0:
                raise Unmeasurable(f"{query['id']}: span anchor is no longer verbatim in {name}")
            spans[name] = [start, start + len(anchor)]
        query["_spans"] = spans
    data["_corpus"] = corpus
    return data


def make_embedder() -> LocalEmbeddings:
    """The production local embedder, or a refusal naming what is missing."""
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    model = os.environ.get("CORPUS_EMBEDDINGS_MODEL", "nomic-embed-text")
    try:
        probe = httpx.get(base_url.rsplit("/v1", 1)[0] + "/api/tags", timeout=5.0)
        probe.raise_for_status()
        installed = {m["name"].split(":")[0] for m in probe.json().get("models", [])}
    except Exception as exc:  # noqa: BLE001 — any failure means the same thing here
        raise Unmeasurable(
            f"no embedding endpoint at {base_url} ({type(exc).__name__}). Retrieval "
            "quality cannot be measured without real embeddings; a hash-based stand-in "
            "would produce numbers that mean nothing."
        ) from exc
    if model.split(":")[0] not in installed:
        raise Unmeasurable(
            f"embedding model '{model}' is not installed at {base_url} "
            f"(available: {sorted(installed) or 'none'}). Pull it with `ollama pull {model}`."
        )
    return LocalEmbeddings(model, base_url)


async def build_store(corpus: dict[str, str], embedder: LocalEmbeddings, root: Path) -> CorpusStore:
    """Ingest the fixture corpus through the real ingestion path.

    Deliberately not a hand-built table of vectors: chunking, offset bookkeeping and the
    `origin != 'generated'` exclusion are all part of what determines whether retrieval
    can find a passage, so a baseline that skipped them would measure a retriever this
    product does not have.
    """
    store = CorpusStore(root / "corpus.sqlite", embedder)
    for name, text in corpus.items():
        await store.ingest(name, text.encode())
    return store


async def evaluate_query(store: CorpusStore, query: dict, by_doc_id: dict[str, str]) -> dict:
    """One query through the real retriever, scored against its labels."""
    hits_raw = await store.search(query["query"], TOP_K)

    hits: list[dict] = []
    for hit in hits_raw:
        location = parse_corpus_url(hit["url"])
        if location is None:  # pragma: no cover — corpus search only emits corpus:// URLs
            continue
        filename = by_doc_id.get(location.doc_id)
        if filename is None:  # pragma: no cover
            continue
        hits.append({"doc_id": filename, "start": location.start, "end": location.end})

    ranked = [h["doc_id"] for h in hits]
    grades: dict[str, int] = query["grades"]
    relevant = [d for d, g in grades.items() if g >= 1]
    gold = [d for d, g in grades.items() if g == 2]

    groups = [g for g in query["_duplicate_groups"] if any(d in grades for d in g)]

    return {
        "id": query["id"],
        "kind": query["kind"],
        "query": query["query"],
        "retrieved": ranked,
        "recall": {f"@{k}": recall_at_k(ranked, gold, k) for k in RECALL_KS},
        "precision": {f"@{k}": precision_at_k(ranked, relevant, k) for k in PRECISION_KS},
        "ndcg@10": ndcg_at_k(ranked, grades, 10),
        "dedup_rate": dedup_rate(ranked, groups),
        "span_accuracy": span_accuracy(hits, query["_spans"]),
    }


def aggregate(rows: list[dict]) -> dict:
    """Corpus-wide numbers, and the same per `kind`.

    Split by kind because a single mean hides the finding: dense-only retrieval is
    expected to do well on paraphrase and badly on an exact rare token, and one averaged
    number would report neither.
    """

    def summarise(subset: list[dict]) -> dict:
        return {
            "queries": len(subset),
            **{
                f"recall@{k}": mean_or_none([r["recall"][f"@{k}"] for r in subset])
                for k in RECALL_KS
            },
            **{
                f"precision@{k}": mean_or_none([r["precision"][f"@{k}"] for r in subset])
                for k in PRECISION_KS
            },
            "ndcg@10": mean_or_none([r["ndcg@10"] for r in subset]),
            "dedup_rate": mean_or_none([r["dedup_rate"] for r in subset]),
            "span_accuracy": mean_or_none([r["span_accuracy"] for r in subset]),
        }

    kinds = sorted({r["kind"] for r in rows})
    return {
        "overall": summarise(rows),
        "by_kind": {k: summarise([r for r in rows if r["kind"] == k]) for k in kinds},
    }


async def run() -> dict:
    data = load_dataset()
    embedder = make_embedder()
    for query in data["queries"]:
        query["_duplicate_groups"] = data["duplicate_groups"]

    with tempfile.TemporaryDirectory() as tmp:
        store = await build_store(data["_corpus"], embedder, Path(tmp))
        by_doc_id = {d["id"]: d["filename"] for d in await store.documents()}
        rows = [await evaluate_query(store, q, by_doc_id) for q in data["queries"]]

    return {
        "status": "measured",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "retrieval_metrics_version": RETRIEVAL_METRICS_VERSION,
        "dataset_version": data["dataset_version"],
        "dataset_fingerprint": dataset_fingerprint(),
        "embedding_model": embedder.model_id,
        "retriever": "research_engine.corpus.CorpusStore.search",
        "top_k": TOP_K,
        "aggregate": aggregate(rows),
        "queries": rows,
    }


def _result_path(run_date: str, slug: str) -> Path:
    """Write-once, following `evals/harness._result_path`.

    A date is not a run identity — the rule this repository learned when a real ollama
    measurement was overwritten by a failed Gemini run and nothing warned.
    """
    candidate = RESULTS_DIR / f"retrieval-{run_date}-{slug}.json"
    n = 2
    while candidate.exists():
        candidate = RESULTS_DIR / f"retrieval-{run_date}-{slug}-run{n}.json"
        n += 1
    return candidate


def _fmt(value: float | None) -> str:
    return "n/a (unmeasured)" if value is None else f"{value:.3f}"


def show(result: dict) -> None:
    if result["status"] != "measured":
        print(f"UNMEASURED: {result['reason']}")
        return
    agg = result["aggregate"]
    print(f"\nretriever          {result['retriever']}")
    print(f"embedding model    {result['embedding_model']}")
    print(f"dataset            v{result['dataset_version']}  {result['dataset_fingerprint'][:12]}")
    print(f"metrics version    {result['retrieval_metrics_version']}\n")
    header = f"{'scope':<14}{'n':>3}  " + "".join(f"{f'recall@{k}':>10}" for k in RECALL_KS)
    header += "".join(f"{f'prec@{k}':>10}" for k in PRECISION_KS)
    header += f"{'ndcg@10':>10}{'dedup':>10}{'span':>10}"
    print(header)
    for scope, block in [("overall", agg["overall"])] + sorted(agg["by_kind"].items()):
        line = f"{scope:<14}{block['queries']:>3}  "
        line += "".join(f"{_fmt(block[f'recall@{k}']):>10}" for k in RECALL_KS)
        keys = [f"precision@{k}" for k in PRECISION_KS]
        for key in [*keys, "ndcg@10", "dedup_rate", "span_accuracy"]:
            line += f"{_fmt(block[key]):>10}"
        print(line)
    print()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="record a write-once result file")
    args = parser.parse_args()

    try:
        result = await run()
    except Unmeasurable as exc:
        # Exit 0: on a machine without an embedding endpoint this is a correct and
        # expected outcome, not a failure of the code under test. It becomes a failure
        # only where a baseline is required, and that gate names itself.
        print(f"UNMEASURED: {exc}")
        return 0

    show(result)
    if args.write:
        path = _result_path(datetime.now(UTC).date().isoformat(), "corpus-local")
        path.write_text(json.dumps(result, indent=2) + "\n")
        print(f"wrote {path.relative_to(Path(__file__).resolve().parent.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
