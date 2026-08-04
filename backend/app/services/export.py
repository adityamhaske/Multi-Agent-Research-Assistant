"""
Report export (docs/05 §3, docs/07 §3): Markdown → styled HTML → PDF.

WeasyPrint links native Pango/Cairo libraries. Those are present in the Docker image
but not necessarily in a bare dev environment, so it is imported lazily inside
`render_pdf` — the API (and the `.md` export) start fine without them, and only the PDF
endpoint surfaces a clear error when the libraries are missing.
"""

from __future__ import annotations

import html
import re

import markdown as md

# Print stylesheet — self-contained, no external assets (works offline in the renderer).
_PDF_CSS = """
@page { size: A4; margin: 2cm; }
body { font-family: 'Helvetica Neue', Arial, sans-serif; font-size: 11pt;
       line-height: 1.5; color: #1a1a1a; }
h1 { font-size: 20pt; margin: 0 0 4pt; }
h2 { font-size: 14pt; margin: 18pt 0 6pt; border-bottom: 1px solid #ddd; padding-bottom: 2pt; }
h3 { font-size: 12pt; margin: 12pt 0 4pt; }
p, li { orphans: 2; widows: 2; }
a { color: #4338ca; text-decoration: none; }
sup { font-size: 0.7em; color: #4338ca; }
blockquote { border-left: 3px solid #ddd; margin: 8pt 0; padding-left: 10pt; color: #555; }
code { font-family: 'SFMono-Regular', Consolas, monospace; font-size: 0.9em;
       background: #f3f3f5; padding: 1pt 3pt; border-radius: 3px; }
pre { background: #f3f3f5; padding: 8pt; border-radius: 4px; overflow-x: auto; }
.meta { color: #777; font-size: 9pt; margin-bottom: 14pt; }
.sources { margin-top: 20pt; border-top: 1px solid #ddd; padding-top: 8pt; font-size: 10pt; }
.sources ol { padding-left: 18pt; }
.sources li { margin-bottom: 5pt; }
.sources .domain { color: #777; }
.sources .snippet { color: #555; font-style: italic; }
"""

# Matches single and grouped citation markers — `[1]` and `[1, 3]` alike.
#
# The third place the single-number-only pattern appeared (docs/12 M5, defect D1). Here it
# meant a grouped citation silently lost its superscript styling in exported .md and .pdf
# reports, so the exported artifact rendered citations inconsistently with the app that
# produced it. Each number is superscripted separately, matching how the UI chips them.
_CITATION_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


def _superscript_citations(match: re.Match[str]) -> str:
    """`[1, 3]` → `<sup>[1]</sup><sup>[3]</sup>`, one marker per cited source."""
    return "".join(f"<sup>[{part.strip()}]</sup>" for part in match.group(1).split(","))


def _domain(url: str) -> str:
    m = re.match(r"https?://(?:www\.)?([^/]+)", url or "")
    return m.group(1) if m else (url or "")


def _sources_html(sources: list[dict]) -> str:
    if not sources:
        return ""
    items = []
    for s in sources:
        idx = html.escape(str(s.get("index", "")))
        url = html.escape(s.get("url", ""), quote=True)
        title = html.escape(s.get("title") or _domain(s.get("url", "")))
        domain = html.escape(_domain(s.get("url", "")))
        snippet = html.escape(s.get("snippet", ""))
        snippet_html = f'<div class="snippet">&ldquo;{snippet}&rdquo;</div>' if snippet else ""
        items.append(
            f'<li id="src-{idx}"><a href="{url}">{title}</a> '
            f'<span class="domain">— {domain}</span>{snippet_html}</li>'
        )
    return '<div class="sources"><h2>Sources</h2><ol>' + "".join(items) + "</ol></div>"


def render_html(
    report_markdown: str, sources: list[dict], *, title: str = "Research Report"
) -> str:
    """Full standalone HTML document for the report (used by the PDF renderer)."""
    # Render inline [n] markers as superscripts before markdown conversion so they
    # survive as <sup> in the output.
    body_md = _CITATION_RE.sub(_superscript_citations, report_markdown or "")
    body_html = md.markdown(body_md, extensions=["extra", "sane_lists"])
    safe_title = html.escape(title)
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>{safe_title}</title><style>{_PDF_CSS}</style></head><body>"
        f"{body_html}{_sources_html(sources)}"
        "</body></html>"
    )


def render_pdf(
    report_markdown: str, sources: list[dict], *, title: str = "Research Report"
) -> bytes:
    """Render the report to PDF. Raises RuntimeError if WeasyPrint's native libs are
    unavailable — the caller maps that to a clear 501."""
    try:
        from weasyprint import HTML
    except (OSError, ImportError) as e:  # missing Pango/Cairo native libs
        raise RuntimeError(f"PDF rendering is unavailable in this environment: {e}") from e

    document = render_html(report_markdown, sources, title=title)
    return HTML(string=document).write_pdf()
