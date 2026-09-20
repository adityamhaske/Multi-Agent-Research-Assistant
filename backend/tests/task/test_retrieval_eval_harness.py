"""The retrieval harness measures the real retriever, or says it could not.

Two distinct properties, and the second is the one with teeth.

The dataset has to stay internally consistent: labels naming documents that exist, span
anchors that are still verbatim in the prose they point at, and a duplicate group whose
members are actually identical. A golden set that has drifted from its own corpus scores
something, and what it scores is not what it claims.

And the harness has to refuse rather than improvise. `FakeEmbeddings` hashes text with
blake2b — deterministic, and carrying no semantic signal at all — so recall computed over
it would be a number with nothing behind it. When no embedding endpoint is reachable the
harness must report `unmeasured`, not a score. That is the same rule
`judge_citation_support` follows, one level up.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from evals import retrieval

DATASET = retrieval.DATASET_DIR


def _dataset() -> dict:
    return json.loads((DATASET / "queries.json").read_text())


def _corpus() -> dict[str, str]:
    return {p.name: p.read_text() for p in (DATASET / "corpus").glob("*.md")}


# ── The dataset is internally consistent ──────────────────────────────────────────


def test_every_graded_document_exists_in_the_corpus():
    corpus = _corpus()
    for query in _dataset()["queries"]:
        for name in query["grades"]:
            assert name in corpus, f"{query['id']} grades a document that is not there: {name}"


def test_every_span_anchor_is_still_verbatim():
    """The anti-rot check. Editing a fixture document without moving its anchor would
    leave span accuracy scoring against a passage that no longer exists."""
    corpus = _corpus()
    for query in _dataset()["queries"]:
        for name, anchor in query.get("span_anchor", {}).items():
            assert anchor in corpus[name], f"{query['id']}: anchor no longer in {name}"


def test_the_declared_duplicate_group_is_actually_duplicated():
    """`dedup_rate` means nothing if the documents it calls duplicates differ."""
    corpus = _corpus()
    groups = _dataset()["duplicate_groups"]
    assert groups, "the dataset must declare at least one duplicate group"
    for group in groups:
        assert len({corpus[name] for name in group}) == 1, f"{group} are not identical"


def test_the_dataset_exercises_both_lexical_and_semantic_retrieval():
    """A set of paraphrase queries alone would not notice a retriever that cannot find an
    exact rare token, which is precisely the weakness A3's lexical index addresses."""
    kinds = [q["kind"] for q in _dataset()["queries"]]
    assert kinds.count("semantic") >= 3
    assert kinds.count("lexical") >= 3
    assert "distractor" in kinds


def test_the_fingerprint_changes_when_the_data_changes(tmp_path, monkeypatch):
    """A result file names the data that produced it. If the fingerprint ignored a
    document's contents, two different corpora would claim the same identity."""
    before = retrieval.dataset_fingerprint()
    staged = tmp_path / "retrieval"
    staged.mkdir()
    (staged / "corpus").mkdir()
    for name, text in _corpus().items():
        (staged / "corpus" / name).write_text(text)
    (staged / "queries.json").write_text((DATASET / "queries.json").read_text())
    monkeypatch.setattr(retrieval, "DATASET_DIR", staged)
    assert retrieval.dataset_fingerprint() == before

    (staged / "corpus" / "photovoltaics.md").write_text("different")
    assert retrieval.dataset_fingerprint() != before


def test_loading_refuses_a_dataset_whose_anchor_has_drifted(tmp_path, monkeypatch):
    """Planted failure: the guard fires rather than scoring against a missing span."""
    staged = tmp_path / "retrieval"
    (staged / "corpus").mkdir(parents=True)
    for name, text in _corpus().items():
        (staged / "corpus" / name).write_text(text)
    data = _dataset()
    data["queries"][0]["span_anchor"] = {"photovoltaics.md": "a sentence that is not there"}
    (staged / "queries.json").write_text(json.dumps(data))
    monkeypatch.setattr(retrieval, "DATASET_DIR", staged)

    with pytest.raises(retrieval.Unmeasurable, match="no longer verbatim"):
        retrieval.load_dataset()


# ── The harness refuses rather than improvising ───────────────────────────────────


def test_no_embedding_endpoint_is_reported_as_unmeasured_not_as_zero(monkeypatch):
    """The load-bearing test. A hash-based stand-in would let this return numbers, and
    numbers with nothing behind them are worse than an honest gap."""

    def refuse(*_a, **_k):
        raise OSError("connection refused")

    monkeypatch.setattr(retrieval.httpx, "get", refuse)
    with pytest.raises(retrieval.Unmeasurable, match="no embedding endpoint"):
        retrieval.make_embedder()


def test_a_missing_embedding_model_names_what_to_pull(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"models": [{"name": "llama3.2:latest"}]}

    monkeypatch.setattr(retrieval.httpx, "get", lambda *a, **k: _Resp())
    monkeypatch.setenv("CORPUS_EMBEDDINGS_MODEL", "nomic-embed-text")
    with pytest.raises(retrieval.Unmeasurable, match="ollama pull nomic-embed-text"):
        retrieval.make_embedder()


def test_the_harness_scores_the_production_retriever_not_a_copy():
    """`CorpusStore.search` is the same call the executor makes. A harness that scored its
    own scorer would measure nothing about what ships."""
    source = pathlib.Path(retrieval.__file__).read_text()
    assert "store.search(" in source
    assert "argsort" not in source, "the harness must not implement ranking of its own"
    assert "cosine" not in source.lower(), "the harness must not implement scoring of its own"


# ── End to end, where an embedder exists ──────────────────────────────────────────


def _embedder_or_skip():
    try:
        return retrieval.make_embedder()
    except retrieval.Unmeasurable as exc:
        pytest.skip(f"no local embedding endpoint: {exc}")


async def test_a_real_run_produces_measured_metrics_for_every_query():
    """Runs the whole harness against the real corpus store and the real embedder.

    Skipped loudly where no embedder exists — which is the harness's own contract, and is
    why this cannot be the only test of it.
    """
    _embedder_or_skip()
    result = await retrieval.run()

    assert result["status"] == "measured"
    assert result["retriever"] == "research_engine.corpus.CorpusStore.search"
    assert len(result["queries"]) == len(_dataset()["queries"])

    overall = result["aggregate"]["overall"]
    assert overall["recall@1"] is not None
    assert overall["ndcg@10"] is not None
    # A retriever that returned nothing would satisfy "not None"; this is the liveness
    # half — the fixture corpus is small and unambiguous, so anything below this is a
    # broken harness rather than a weak retriever.
    assert overall["recall@5"] >= 0.5, "the harness retrieved almost nothing; check ingestion"
    for row in result["queries"]:
        assert row["retrieved"], f"{row['id']} retrieved nothing at all"
