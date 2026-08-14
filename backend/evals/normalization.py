"""
Citation normalization for external research agents (e.g., GPT-Researcher).

GPT-Researcher natively outputs Markdown hyperlinks like `[Source Title](https://example.com/page)`
instead of numbered citation markers `[n]`. This module normalizes external reports into the
standard format expected by the citation metrics harness (`evals.metrics`).

Normalization rules:
1. URL canonicalization (strip trailing slashes, tracking params).
2. Unique sequential indexing: every distinct URL is assigned an integer index [1..k].
3. Multiple references to the same URL (even with different anchor text) resolve to the same index.
4. Consecutive / grouped citations in close proximity are cleanly transformed.
5. The References / Bibliography section at the bottom is extracted and parsed into `sources` dicts.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any


MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s\)]+)\)")
REFERENCES_HEADING_RE = re.compile(
    r"^#{1,6}\s*(references|sources|citations|bibliography)\b", re.I
)


TRACKING_PARAM_DENYLIST = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "ref",
        "ref_src",
        "source",
        "fbclid",
        "gclid",
        "gclsrc",
        "dclid",
        "msclkid",
        "mc_cid",
        "mc_eid",
        "_ga",
        "_gl",
        "yclid",
    }
)


def canonicalize_url(url: str) -> str:
    """
    Normalize a URL to prevent duplicate indices for trivial tracking differences.

    Uses an explicit TRACKING_PARAM_DENYLIST. Content-differentiating query parameters
    (e.g., ?page=, ?section=, ?id=, ?v=, ?lang=, ?tab=) are strictly PRESERVED so that
    distinct content pages on the same host resolve to distinct source indices.
    """
    url = url.strip()
    parsed = urllib.parse.urlparse(url)
    clean_query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    filtered_query = [
        (k, v)
        for k, v in clean_query
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAM_DENYLIST
    ]
    new_query = urllib.parse.urlencode(filtered_query)
    clean_path = parsed.path.rstrip("/") if parsed.path != "/" else "/"
    return urllib.parse.urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            clean_path,
            parsed.params,
            new_query,
            parsed.fragment,
        )
    )


def normalize_external_report(
    raw_markdown: str,
    raw_source_snippets: dict[str, list[str]] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """
    Transform raw Markdown with inline hyperlinks into normalized report text with [n] citations
    and a structured sources list matching research_engine schemas.

    Returns:
        (normalized_markdown, sources_list)
    """
    raw_source_snippets = raw_source_snippets or {}

    # 1. Separate report body from existing References section if present
    lines = raw_markdown.splitlines()
    body_lines: list[str] = []
    ref_lines: list[str] = []
    in_refs = False

    for line in lines:
        if REFERENCES_HEADING_RE.match(line.strip()):
            in_refs = True
            continue
        if in_refs:
            ref_lines.append(line)
        else:
            body_lines.append(line)

    body_text = "\n".join(body_lines)

    # 2. Extract all markdown links in body order
    url_to_index: dict[str, int] = {}
    url_to_title: dict[str, str] = {}
    next_index = 1

    for match in MD_LINK_RE.finditer(body_text):
        anchor_text, raw_url = match.group(1).strip(), match.group(2).strip()
        canon_url = canonicalize_url(raw_url)
        if canon_url not in url_to_index:
            url_to_index[canon_url] = next_index
            url_to_title[canon_url] = anchor_text
            next_index += 1

    # Also parse links from the References section if any exist there but weren't in body
    for line in ref_lines:
        for match in MD_LINK_RE.finditer(line):
            anchor_text, raw_url = match.group(1).strip(), match.group(2).strip()
            canon_url = canonicalize_url(raw_url)
            if canon_url not in url_to_index:
                url_to_index[canon_url] = next_index
                url_to_title[canon_url] = anchor_text
                next_index += 1

    # 3. Replace inline markdown links in the body with [n]
    def _replace_link(match: re.Match) -> str:
        raw_url = match.group(2).strip()
        canon_url = canonicalize_url(raw_url)
        idx = url_to_index.get(canon_url)
        if idx is not None:
            return f"[{idx}]"
        return match.group(0)

    normalized_body = MD_LINK_RE.sub(_replace_link, body_text)

    # 4. Clean up any accidental double brackets or trailing formatting
    # e.g., "[[1]]" -> "[1]"
    normalized_body = re.sub(r"\[\[(\d+)\]\]", r"[\1]", normalized_body)

    # 5. Build structured sources list
    sources: list[dict[str, Any]] = []
    for canon_url, idx in sorted(url_to_index.items(), key=lambda x: x[1]):
        title = url_to_title.get(canon_url, f"Source {idx}")
        snippets = raw_source_snippets.get(canon_url, [])
        sources.append(
            {
                "index": idx,
                "title": title,
                "url": canon_url,
                "snippet": snippets[0] if snippets else "",
                "snippets": snippets,
            }
        )

    # 6. Rebuild normalized report with standard References section
    sources_section_lines = ["\n\n## Sources\n"]
    for s in sources:
        sources_section_lines.append(f"{s['index']}. [{s['title']}]({s['url']})")
    
    final_report = normalized_body.rstrip() + "\n" + "\n".join(sources_section_lines) + "\n"

    return final_report, sources
