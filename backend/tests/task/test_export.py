"""
Export service tests (docs/05 §3, docs/07 §3). The HTML rendering + citation/source
handling is pure and tested here; the WeasyPrint PDF step needs native libs, so that
test produces a real PDF where they're present (the Docker image, CI) and skips where
they aren't (a bare dev box)."""

import pytest

from app.services.export import (
    _domain,
    _sources_html,
    render_html,
    render_model_attribution_md,
    render_pdf,
)

REPORT = "# Findings\n\nA fact [1] and another [2].\n\n- bullet point [1]\n"
SOURCES = [
    {"index": 1, "url": "https://www.nasa.gov/report", "title": "NASA", "snippet": "quote here"},
    {"index": 2, "url": "https://arxiv.org/abs/1", "title": "", "snippet": ""},
]


def test_domain_strips_scheme_and_www():
    assert _domain("https://www.example.com/a/b") == "example.com"
    assert _domain("http://arxiv.org/abs/1") == "arxiv.org"
    assert _domain("not-a-url") == "not-a-url"


def test_render_html_turns_citations_into_superscripts():
    html = render_html(REPORT, SOURCES)
    assert "<sup>[1]</sup>" in html
    assert "<sup>[2]</sup>" in html


def test_render_html_renders_markdown_structure():
    html = render_html(REPORT, SOURCES)
    assert "<h1>Findings</h1>" in html
    assert "<li>" in html  # the bullet


def test_render_html_appends_sources_section_with_domain():
    html = render_html(REPORT, SOURCES)
    assert "<h2>Sources</h2>" in html
    assert "nasa.gov" in html and "arxiv.org" in html
    assert "quote here" in html  # snippet rendered


def test_render_html_escapes_untrusted_fields():
    # Title + snippet come from web content — must be HTML-escaped, never injected.
    html = render_html(
        "# Ok",
        [
            {
                "index": 1,
                "url": "https://x.com",
                "title": "<script>alert(1)</script>",
                "snippet": "a&b",
            }
        ],
        title="My <Report> & More",
    )
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "My &lt;Report&gt; &amp; More" in html


def test_sources_html_empty_without_sources():
    assert _sources_html([]) == ""


# ─── Model attribution (requirement 1: disclosure "in the report/export") ──────────


def test_render_html_appends_a_models_used_section():
    routing = {"planner": "anthropic:claude-opus-5", "executor": "google:gemini-2.5-flash"}
    out = render_html(REPORT, SOURCES, model_routing=routing)
    assert "<h2>Models used</h2>" in out
    assert "planner" in out and "anthropic:claude-opus-5" in out
    assert "executor" in out and "google:gemini-2.5-flash" in out


def test_render_html_omits_the_models_section_when_unresolved():
    """The unmeasured-vs-zero rule: absent routing must render as absent, never as an
    empty or default-filled table."""
    assert "Models used" not in render_html(REPORT, SOURCES, model_routing=None)
    assert "Models used" not in render_html(REPORT, SOURCES, model_routing={})


def test_render_model_attribution_md_lists_every_role():
    routing = {"synthesizer": "anthropic:claude-sonnet-5", "critic": "google:gemini-2.5-flash"}
    out = render_model_attribution_md(routing)
    assert "## Models used" in out
    assert "**critic** — `google:gemini-2.5-flash`" in out
    assert "**synthesizer** — `anthropic:claude-sonnet-5`" in out


def test_render_model_attribution_md_is_empty_when_unresolved():
    assert render_model_attribution_md(None) == ""
    assert render_model_attribution_md({}) == ""


def test_render_pdf_emits_a_real_pdf_where_libs_exist():
    try:
        import weasyprint  # noqa: F401
    except Exception:  # noqa: BLE001 — native libs absent on this box
        pytest.skip("WeasyPrint native libraries not available in this environment")
    pdf = render_pdf(REPORT, SOURCES, title="Report")
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 500
