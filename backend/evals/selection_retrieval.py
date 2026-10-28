"""Selected-files retrieval: leakage, and the per-document hit cap before and after (RFC V3.1 §17).

Two questions about one thing, measured through the path a selected-files run takes:
`ScopedCorpus.search` over a real `CorpusStore`, on the real local embedder.

1. **Leakage.** For each query, the share of retrieved chunks that come from a document
   outside the selection. **The target is exactly 0**: any other value is a selection run that
   could cite a file the user did not choose. The dataset is built so a leak would have
   something to find. Unselected documents often answer the query better than the selected
   ones, and two selections exclude an identical copy of a selected document.
2. **The hit cap (§9.8).** A selection run takes `max(1, ceil(k / n))` hits per selected file,
   where it used to take one, so a two-file selection asking for five passages can get more
   than two. Ranking quality inside the selection is measured with today's cap and with
   `per_document=1`, on the same data and embedder. The cap's claim to help is measured,
   not assumed (docs/08).

**Unmeasured is reported as unmeasured** (`evals/retrieval.py`). No embedding endpoint means
no result. A query that retrieved nothing has no leakage share at all, `None` and never 0,
and is counted separately.

    python -m evals.selection_retrieval            # measure and print
    python -m evals.selection_retrieval --write    # also record a write-once result
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from evals.retrieval import (
    PRECISION_KS,
    RECALL_KS,
    RESULTS_DIR,
    Unmeasurable,
    _fmt,
    _result_path,
    make_embedder,
)
from evals.retrieval_metrics import (
    RETRIEVAL_METRICS_VERSION,
    mean_or_none,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)
from research_engine.corpus import CorpusStore, ScopedCorpus, parse_corpus_url

BACKEND = Path(__file__).resolve().parent.parent
DATASET = BACKEND / "evals" / "datasets" / "selection-retrieval" / "queries.json"
TOP_K = 5


def _corpus_files(data: dict) -> list[Path]:
    files: list[Path] = []
    for pattern in data["corpora"]:
        directory, glob = pattern.rsplit("/", 1)
        files += [p for p in sorted((BACKEND / directory).glob(glob)) if p.name != "goldens.json"]
    names = [p.name for p in files]
    if len(set(names)) != len(names):
        raise Unmeasurable("two corpus files share a name; a filename is a document identity")
    return files


def _anchor_spans(query: dict, texts: dict[str, str]) -> dict[str, list[list[int]]]:
    """Each verbatim anchor's offsets in the stored text; a dataset whose prose drifted from
    its anchors fails here rather than scoring passages that no longer exist."""
    spans: dict[str, list[list[int]]] = {}
    for name, anchors in query.get("passage_anchors", {}).items():
        for anchor in anchors:
            start = texts[name].find(anchor)
            if start < 0:
                raise Unmeasurable(f"{query['id']}: anchor is no longer verbatim in {name}")
            spans.setdefault(name, []).append([start, start + len(anchor)])
    return spans


def dataset_fingerprint(files: list[Path]) -> str:
    """SHA-256 over the query file and every corpus byte, so a result names its data."""
    h = hashlib.sha256(DATASET.read_bytes())
    for path in files:
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def _hits(raw: list[dict], filename_of: dict[str, str]) -> list[dict]:
    out = []
    for hit in raw:
        location = parse_corpus_url(hit["url"])
        if location is not None:
            out.append(
                {
                    "file": filename_of.get(location.doc_id, f"unknown:{location.doc_id}"),
                    "start": location.start,
                    "end": location.end,
                }
            )
    return out


def _passage_recall(hits: list[dict], anchors: dict[str, list[list[int]]]) -> float | None:
    """Share of the answer passages some returned chunk overlaps; `None` with no anchors."""
    wanted = [(name, span) for name, spans in anchors.items() for span in spans]
    if not wanted:
        return None
    found = sum(
        1
        for name, (start, end) in wanted
        if any(h["file"] == name and h["start"] < end and start < h["end"] for h in hits)
    )
    return found / len(wanted)


def _scores(hits: list[dict], grades: dict[str, int], anchors: dict) -> dict:
    # Document metrics read each file once, at its best rank: with the cap one file can
    # return several chunks, and counting it again would score a ranking above perfect.
    ranked = list(dict.fromkeys(h["file"] for h in hits))
    gold = [d for d, g in grades.items() if g == 2]
    relevant = [d for d, g in grades.items() if g >= 1]
    return {
        "retrieved": [f"{h['file']}#{h['start']}-{h['end']}" for h in hits],
        "passages": len(hits),
        "recall": {f"@{k}": recall_at_k(ranked, gold, k) for k in RECALL_KS},
        "precision": {f"@{k}": precision_at_k(ranked, relevant, k) for k in PRECISION_KS},
        "ndcg@5": ndcg_at_k(ranked, grades, TOP_K),
        "passage_recall": _passage_recall(hits, anchors),
    }


async def evaluate_query(store: CorpusStore, query: dict, id_of: dict, filename_of: dict) -> dict:
    missing = [name for name in query["selection"] if name not in id_of]
    if missing:
        raise Unmeasurable(f"{query['id']}: selection names files not in the corpus: {missing}")
    allowed = frozenset(id_of[name] for name in query["selection"])
    scoped = ScopedCorpus(store, allowed)

    capped = _hits(await scoped.search(query["query"], TOP_K), filename_of)
    one_each = _hits(
        await store.search(query["query"], TOP_K, document_ids=allowed, per_document=1),
        filename_of,
    )
    outside = [h["file"] for h in capped if h["file"] not in query["selection"]]
    anchors = query.get("_spans", {})
    return {
        "id": query["id"],
        "query": query["query"],
        "selection": query["selection"],
        "per_document_cap": max(1, -(-TOP_K // len(allowed))),
        # None, never 0, when nothing came back: there is no share of nothing.
        "leakage": (len(outside) / len(capped)) if capped else None,
        "outside_selection": outside,
        "with_cap": _scores(capped, query["grades"], anchors),
        "one_per_document": _scores(one_each, query["grades"], anchors),
    }


def _summary(rows: list[dict], variant: str) -> dict:
    return {
        **{
            f"recall@{k}": mean_or_none([r[variant]["recall"][f"@{k}"] for r in rows])
            for k in RECALL_KS
        },
        **{
            f"precision@{k}": mean_or_none([r[variant]["precision"][f"@{k}"] for r in rows])
            for k in PRECISION_KS
        },
        "ndcg@5": mean_or_none([r[variant]["ndcg@5"] for r in rows]),
        "passages_per_query": mean_or_none([r[variant]["passages"] for r in rows]),
        "passage_recall": mean_or_none([r[variant]["passage_recall"] for r in rows]),
    }


def aggregate(rows: list[dict]) -> dict:
    measured = [r["leakage"] for r in rows if r["leakage"] is not None]
    return {
        "queries": len(rows),
        "leakage": {
            "target": 0,
            "max": max(measured) if measured else None,
            "queries_measured": len(measured),
            "queries_with_no_hits": len(rows) - len(measured),
            "queries_leaking": sum(1 for v in measured if v > 0),
        },
        "hit_cap": {
            "after (max(1, ceil(k/n)) per file)": _summary(rows, "with_cap"),
            "before (one per file)": _summary(rows, "one_per_document"),
        },
    }


async def run() -> dict:
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    files = _corpus_files(data)
    embedder = make_embedder()
    with tempfile.TemporaryDirectory() as tmp:
        store = CorpusStore(Path(tmp) / "corpus.sqlite", embedder)
        for path in files:
            await store.ingest(path.name, path.read_bytes())
        docs = await store.documents()
        id_of = {d["filename"]: d["id"] for d in docs}
        filename_of = {d["id"]: d["filename"] for d in docs}
        texts = {p.name: (await store.extracted(id_of[p.name]))["text"] for p in files}
        for query in data["queries"]:
            query["_spans"] = _anchor_spans(query, texts)
        rows = [await evaluate_query(store, q, id_of, filename_of) for q in data["queries"]]
    return {
        "status": "measured",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "retrieval_metrics_version": RETRIEVAL_METRICS_VERSION,
        "dataset": "selection-retrieval",
        "dataset_version": data["dataset_version"],
        "dataset_fingerprint": dataset_fingerprint(files),
        "corpus_documents": len(files),
        "embedding_model": embedder.model_id,
        "retriever": "research_engine.corpus.ScopedCorpus.search",
        "top_k": TOP_K,
        "aggregate": aggregate(rows),
        "queries": rows,
    }


def show(result: dict) -> None:
    agg = result["aggregate"]
    leak = agg["leakage"]
    print(f"dataset            selection-retrieval v{result['dataset_version']}  "
          f"{result['dataset_fingerprint'][:12]}  ({result['corpus_documents']} documents)")  # fmt: skip
    print(f"embedder           {result['embedding_model']}")
    print(f"leakage            max {_fmt(leak['max'])} (target 0) — {leak['queries_leaking']} of "
          f"{leak['queries_measured']} measured queries leaked; "
          f"{leak['queries_with_no_hits']} retrieved nothing")  # fmt: skip
    for label, numbers in agg["hit_cap"].items():
        print(f"{label:<38} " + "  ".join(f"{k} {_fmt(v)}" for k, v in numbers.items()))


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="record a write-once result file")
    args = parser.parse_args()
    try:
        result = await run()
    except Unmeasurable as exc:
        print(f"UNMEASURED: {exc}")
        return 0
    show(result)
    if args.write:
        path = _result_path(datetime.now(UTC).date().isoformat(), "selection-local")
        path.write_text(json.dumps(result, indent=2) + "\n")
        print(f"wrote {path.relative_to(RESULTS_DIR.parent.parent)}")
    # A leak is the product failing its guarantee, so the command says so by its exit code.
    return 1 if (result["aggregate"]["leakage"]["max"] or 0) > 0 else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
