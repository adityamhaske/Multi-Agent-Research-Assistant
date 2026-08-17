"""
HTML in the corpus, and how the original bytes are served back (docs/07 §2, Phase 6).

Two separate concerns that have to hold together:

1. **Ingest.** `.html`/`.htm` become indexable text — a citation has to be locatable
   inside the document, and tag soup is not. The *original* bytes stay stored so the
   preview shows the page rather than its stripped text.
2. **Serving.** Uploaded HTML is untrusted content authored by whoever made the file.
   It must never render in this origin. The preview renders it in an
   `<iframe sandbox="" srcdoc=…>` — an opaque origin with no scripts — so the download
   route's job is to make sure nothing *else* can happen to it: no inline rendering, no
   sniffing, no framing.

The download route previously said "`Content-Disposition: attachment` … never render an
uploaded document inline in this origin", which was right and stays right for every type
except PDF. PDF is the one format the browser renders in its own sandboxed viewer rather
than as a document in our origin, and it is the one that cannot be previewed any other
way. That narrowing is the whole of the security change here, and it is asserted below in
both directions.
"""

from __future__ import annotations

import pytest

from research_engine.documents import extract_document, kind_for

HTML = b"""<!doctype html>
<html><head><title>Grounding metrics</title><style>p { color: red }</style>
<script>alert('xss')</script></head>
<body><h1>Grounding metrics</h1>
<p>Recall improved by 12 points on the held-out split.</p>
<p>The <em>second</em> paragraph names a number: 0.87.</p>
</body></html>"""


# ── Ingest ─────────────────────────────────────────────────────────────────────────


def test_html_is_an_accepted_document_kind():
    assert kind_for("paper.html") == "html"
    assert kind_for("paper.HTM") == "html"


def test_the_rejection_message_names_html_now_that_it_is_accepted():
    """The message and the accepted set are one contract. They were edited together
    once before and the message is what a user actually reads when they guess wrong."""
    with pytest.raises(ValueError) as exc:
        kind_for("slides.pptx")
    assert "HTML" in str(exc.value)


def test_html_is_indexed_as_readable_text_not_tag_soup():
    text, page_starts, kind = extract_document("paper.html", HTML)

    assert kind == "html"
    assert "Recall improved by 12 points on the held-out split." in text
    assert "0.87" in text
    # Markup must not enter the index: a chunk of `<p class=…>` is text a citation could
    # be "located inside" while meaning nothing.
    assert "<p>" not in text and "<h1>" not in text
    # Script and style bodies are not content, and indexing them would let a page put
    # arbitrary strings into a corpus a model then quotes.
    assert "alert(" not in text
    assert "color: red" not in text
    assert page_starts == [0], "text formats have no page structure"


def test_html_with_no_readable_text_is_refused():
    """An empty shell would index as nothing and then be un-citable, which is worse than
    a rejection the user can act on."""
    with pytest.raises(ValueError, match="no text"):
        extract_document("empty.html", b"<html><body><script>x=1</script></body></html>")


# ── Serving ────────────────────────────────────────────────────────────────────────


def test_download_headers_render_pdf_inline_and_nothing_else():
    """PDF is the single exception, and it is narrow on purpose.

    `application/pdf` + `nosniff` cannot be reinterpreted as a document in this origin —
    the browser hands it to its own viewer. Every other type keeps `attachment`, which is
    what stops an uploaded `.html` from ever being navigated to and executed here.
    """
    from app.api.v1.corpus import download_headers

    pdf = download_headers("pdf", "paper.pdf")
    assert pdf["Content-Disposition"].startswith("inline")
    assert pdf["X-Content-Type-Options"] == "nosniff"
    # Framable by our own preview, by nobody else.
    assert "frame-ancestors 'self'" in pdf["Content-Security-Policy"]
    assert pdf["X-Frame-Options"] == "SAMEORIGIN"

    for kind in ("html", "md", "txt", "unknown"):
        headers = download_headers(kind, f"f.{kind}")
        assert headers["Content-Disposition"].startswith("attachment"), kind
        assert headers["X-Content-Type-Options"] == "nosniff", kind
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"], kind
        # `sandbox` gives even a directly-navigated response an opaque origin with no
        # scripts — belt to `attachment`'s braces, for the case a browser ignores it.
        assert "sandbox" in headers["Content-Security-Policy"], kind


def test_a_crafted_filename_cannot_inject_response_headers():
    from app.api.v1.corpus import download_headers

    headers = download_headers("pdf", 'evil"\r\nX-Injected: 1\n.pdf')
    value = headers["Content-Disposition"]
    assert "\r" not in value and "\n" not in value
    assert "X-Injected" not in headers


def test_html_is_served_as_html_but_never_inline():
    """The media type stays honest — a user who downloads the file gets a `.html` that
    opens in their browser — while the disposition is what keeps it out of this origin."""
    from app.api.v1.corpus import download_headers, media_type_for

    assert media_type_for("html") == "text/html; charset=utf-8"
    assert download_headers("html", "page.html")["Content-Disposition"].startswith("attachment")
