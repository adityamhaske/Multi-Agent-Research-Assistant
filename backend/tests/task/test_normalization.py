"""
Tests for GPT-Researcher report normalization (evals/normalization.py).
"""

from __future__ import annotations

from evals import metrics
from evals.normalization import canonicalize_url, normalize_external_report


def test_canonicalize_url_tracking_params():
    u1 = "https://example.com/docs/?utm_source=twitter&utm_medium=social&ref=abc&fbclid=123"
    u2 = "https://example.com/docs"
    u3 = "https://example.com/docs?gclid=xyz&_ga=456"
    assert (
        canonicalize_url(u1)
        == canonicalize_url(u2)
        == canonicalize_url(u3)
        == "https://example.com/docs"
    )


def test_canonicalize_url_preserves_content_params():
    """Content-differentiating query parameters must NOT be stripped."""
    u_page1 = "https://example.com/api?page=1"
    u_page2 = "https://example.com/api?page=2"
    u_sec_a = "https://example.com/docs?section=auth"
    u_sec_b = "https://example.com/docs?section=billing"
    u_lang = "https://example.com/docs?lang=de"

    # Distinct content params produce distinct canonical URLs
    assert canonicalize_url(u_page1) != canonicalize_url(u_page2)
    assert canonicalize_url(u_sec_a) != canonicalize_url(u_sec_b)
    assert canonicalize_url(u_sec_a) != canonicalize_url("https://example.com/docs")
    assert canonicalize_url(u_lang) == "https://example.com/docs?lang=de"

    # Content params with tracking params attached: tracking param stripped, content param preserved
    u_mixed = "https://example.com/api?page=1&utm_source=newsletter"
    assert canonicalize_url(u_mixed) == "https://example.com/api?page=1"


def test_adversarial_dedup_and_content_separation():
    """
    Adversarial test:
    - Source A: https://example.com/docs?section=auth (cited twice with different anchor text & tracking)
    - Source B: https://example.com/docs?section=storage (same host/path, different content param)
    - Source C: https://example.com/docs (base doc)

    Must resolve to 3 distinct sources ([1], [2], [3]) without over-merging.
    """
    raw_markdown = """# System Architecture Overview

Authentication is handled via JWT bearer tokens [Auth Spec](https://example.com/docs?section=auth&utm_source=twitter). All login endpoints require token validation [Authentication Docs](https://example.com/docs?section=auth&ref=nav).

Persistent storage uses PostgreSQL with connection pooling [Storage Spec](https://example.com/docs?section=storage&utm_campaign=launch). General setup instructions are available in the base guide [Getting Started](https://example.com/docs).

## References
- [Auth Spec](https://example.com/docs?section=auth)
- [Storage Spec](https://example.com/docs?section=storage)
- [Getting Started](https://example.com/docs)
"""

    normalized_report, sources = normalize_external_report(raw_markdown)

    # Must have exactly 3 distinct sources
    assert len(sources) == 3
    urls = [s["url"] for s in sources]
    assert "https://example.com/docs?section=auth" in urls
    assert "https://example.com/docs?section=storage" in urls
    assert "https://example.com/docs" in urls

    # Both auth citations mapped to the SAME index
    auth_idx = [s["index"] for s in sources if s["url"] == "https://example.com/docs?section=auth"][
        0
    ]
    storage_idx = [
        s["index"] for s in sources if s["url"] == "https://example.com/docs?section=storage"
    ][0]
    base_idx = [s["index"] for s in sources if s["url"] == "https://example.com/docs"][0]

    assert auth_idx != storage_idx != base_idx

    body = metrics.body_before_sources(normalized_report)
    assert f"tokens [{auth_idx}]." in body
    assert f"validation [{auth_idx}]." in body
    assert f"pooling [{storage_idx}]." in body
    assert f"guide [{base_idx}]." in body

    stats = metrics.citation_stats(normalized_report, sources)
    assert stats["total_citations"] == 4
    assert stats["unresolved_citations"] == 0
    assert stats["resolution_rate"] == 1.0


def test_claim_extraction_excludes_headings_and_references():
    """Verify claim extractor ignores document titles, section headers, and references."""
    raw_markdown = """# Top-Level Title Not A Claim

## Section Heading Not A Claim

This is the first real claim sentence [1]. This is the second real claim sentence [2].

### Subsection Heading

This is the third real claim sentence with no citation.

## References
1. [Source 1](https://example.com/1)
2. [Source 2](https://example.com/2)
"""
    claims = metrics.claim_lines(raw_markdown)
    assert len(claims) == 3
    assert "Top-Level Title" not in " ".join(claims)
    assert "Section Heading" not in " ".join(claims)
    assert "Subsection Heading" not in " ".join(claims)
    assert "References" not in " ".join(claims)
    assert "Source 1" not in " ".join(claims)

    assert metrics.uncited_claim_count(raw_markdown) == 1


def test_normalization_dry_run():
    sample_gpt_researcher_output = """# Research Report on Long-Term Memory in AI Agents

Long-term memory is critical for autonomous agent architectures. Various approaches have been proposed, including external vector stores and retrieval-augmented generation [LangChain Documentation](https://python.langchain.com/docs/modules/memory/). In contrast, graph-based memory structures maintain entity relationships over extended interactions [Neo4j AI Guide](https://neo4j.com/developer/genai-ecosystem/?utm_campaign=ai).

Furthermore, hybrid architectures combine episodic vector indexes with parametric fine-tuning [LangChain Memory Overview](https://python.langchain.com/docs/modules/memory/?ref=top) and working memory buffers [MemGPT Paper](https://arxiv.org/abs/2310.08560). Benchmarks indicate that graph-augmented recall yields 18% higher context fidelity [Neo4j Developer](https://neo4j.com/developer/genai-ecosystem/).

## References
- [LangChain Documentation](https://python.langchain.com/docs/modules/memory/)
- [Neo4j AI Guide](https://neo4j.com/developer/genai-ecosystem/)
- [MemGPT Research](https://arxiv.org/abs/2310.08560)
"""

    mock_snippets = {
        "https://python.langchain.com/docs/modules/memory": [
            "LangChain provides conversation memory and vectorstore-backed memory abstractions.",
            "Hybrid memory buffers support episodic retrieval alongside short-term context.",
        ],
        "https://neo4j.com/developer/genai-ecosystem": [
            "Graph structures preserve semantic relationships between entities across sessions.",
            "Knowledge graph integrations demonstrate 18% improvement in multi-hop context retrieval.",
        ],
        "https://arxiv.org/abs/2310.08560": [
            "MemGPT introduces tiered memory management inspired by OS virtual memory paging.",
        ],
    }

    normalized_report, sources = normalize_external_report(
        sample_gpt_researcher_output, mock_snippets
    )

    # 1. Check sources structure
    assert len(sources) == 3
    assert sources[0]["index"] == 1
    assert sources[0]["url"] == "https://python.langchain.com/docs/modules/memory"
    assert sources[1]["index"] == 2
    assert sources[1]["url"] == "https://neo4j.com/developer/genai-ecosystem"
    assert sources[2]["index"] == 3
    assert sources[2]["url"] == "https://arxiv.org/abs/2310.08560"

    # 2. Check in-text citations
    body = metrics.body_before_sources(normalized_report)
    assert "[1]" in body
    assert "[2]" in body
    assert "[3]" in body
    assert "[LangChain Documentation]" not in body

    # 3. Check metrics on normalized report
    stats = metrics.citation_stats(normalized_report, sources)
    assert stats["total_citations"] == 5
    assert stats["unresolved_citations"] == 0
    assert stats["resolution_rate"] == 1.0

    claims = metrics.claim_lines(normalized_report)
    assert len(claims) == 5
    assert metrics.uncited_claim_count(normalized_report) == 1
