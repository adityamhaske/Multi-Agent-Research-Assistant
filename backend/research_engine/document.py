"""A typed view of a report (V2.1-a A7).

A report is a Markdown string at every layer of this system: in the graph's state, on
`revisions.report_markdown`, and in the bundle. Its structure is re-derived by regex in
three places, and `research_engine/claims.py` records what that costs — a single-number
citation pattern once made 42% of a real report's markers invisible while reporting a
perfect resolution rate.

**Markdown stays authoritative here, and that is the whole design.** `report_hash` is
`sha256(report_markdown)`, and that hash is what `reviews.reviewed_hash`,
`research_artifacts.artifact_hash` and the bundle verifier's approval-chain check all pin.
Re-rendering a parsed document back into the hash input would put an already-approved
artifact's verification at the mercy of a parser. So the arrow runs one way:

    LLM output ──> report_markdown ──> report_hash / approval / artifact / bundle
                        │
                        └────────────> ReportDocument   (derived, non-authoritative)

The direction inverts only when generation itself emits blocks, which is a later phase.

Parsing reuses `claims.py`'s regexes **by import rather than by restatement**: the document
and claim extraction must never disagree about what a heading or a list item is, and two
copies of those rules would eventually do exactly that.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from research_engine.claims import HEADING_RE, LIST_MARKER_RE, extract_citations

#: Bumped when the block vocabulary or the render rules change. A stored document carries
#: it so a reader can tell whether it was produced by the rules it is about to apply.
SCHEMA_VERSION = 1

BlockKind = Literal["heading", "paragraph", "list_item"]


class ReportBlock(BaseModel):
    """One structural element of a report.

    Three kinds, because three kinds are what the synthesizer emits. Tables, figures,
    equations and code have no producer until a later phase, and a kind nothing can write
    is a column nothing fills.
    """

    kind: BlockKind
    #: The visible text, with the Markdown marker removed — `## Summary` stores `Summary`,
    #: `- a fact [1]` stores `a fact [1]`. The renderer puts the marker back.
    text: str
    order: int
    #: Heading depth, 1-6. `None` for every other kind.
    level: int | None = None
    #: The `[n]` markers this block carries, in source order, flattened from grouped forms
    #: like `[1, 3]`. Derived with `claims.extract_citations` — the same function the
    #: citation-resolution rate uses, so a marker cannot count here and not there.
    citation_markers: tuple[int, ...] = ()


class ReportMetadata(BaseModel):
    """What identifies this report. Deliberately small.

    No workflow, agent, prompt or model provenance: those belong to the phase that
    introduces them, and recording a version this build cannot know would be a fabricated
    provenance claim rather than an empty one.
    """

    run_id: str
    revision_version: int
    question: str
    #: Passed in by the caller, never read from the clock here — a parser that timestamps
    #: itself is a parser whose output differs on every call, and this one must be a pure
    #: function of its input.
    generated_at: str


class ReportDocument(BaseModel):
    """The derived, typed view of one report revision."""

    schema_version: int = SCHEMA_VERSION
    blocks: tuple[ReportBlock, ...]
    metadata: ReportMetadata
    #: Whether `render_markdown(self)` reproduces the exact bytes this was parsed from.
    #:
    #: Recorded rather than required. A report using Markdown this vocabulary does not
    #: model — a fenced code block, a table — still parses, with the construct preserved
    #: verbatim inside a paragraph, and simply does not round-trip. Saying so is the
    #: difference between a derived view a reader can trust the provenance of and one that
    #: quietly claims to be its source. `EXACT` is not a success condition and `LOSSY` is
    #: not a failure; what matters is that neither is ever mistaken for the authoritative
    #: `report_markdown`.
    render_fidelity: Literal["EXACT", "LOSSY"]


def _heading_level(line: str) -> int:
    return len(line) - len(line.lstrip("#"))


def parse_markdown(markdown: str, *, metadata: ReportMetadata) -> ReportDocument:
    """Derive a typed view of a report. Pure, deterministic, and never authoritative.

    Unrecognised constructs are not dropped and not guessed at — they become paragraph text
    verbatim, so the document is always a complete view of the report even where it is a
    coarse one. `render_fidelity` then records that the view is coarse.
    """
    blocks: list[ReportBlock] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            text = "\n".join(paragraph)
            blocks.append(
                ReportBlock(
                    kind="paragraph",
                    text=text,
                    order=len(blocks),
                    citation_markers=tuple(extract_citations(text)),
                )
            )
            paragraph.clear()

    for raw in (markdown or "").split("\n"):
        line = raw.rstrip()
        if not line.strip():
            flush()
            continue
        if HEADING_RE.match(line):
            flush()
            text = line.lstrip("#").strip()
            blocks.append(
                ReportBlock(
                    kind="heading",
                    text=text,
                    order=len(blocks),
                    level=_heading_level(line),
                    citation_markers=tuple(extract_citations(text)),
                )
            )
            continue
        if LIST_MARKER_RE.match(line):
            flush()
            text = LIST_MARKER_RE.sub("", line, count=1)
            blocks.append(
                ReportBlock(
                    kind="list_item",
                    text=text,
                    order=len(blocks),
                    citation_markers=tuple(extract_citations(text)),
                )
            )
            continue
        paragraph.append(line)
    flush()

    document = ReportDocument(
        blocks=tuple(blocks),
        metadata=metadata,
        render_fidelity="EXACT",  # provisional; decided by the comparison below
    )
    fidelity = "EXACT" if render_markdown(document) == (markdown or "") else "LOSSY"
    return document.model_copy(update={"render_fidelity": fidelity})


def render_markdown(document: ReportDocument) -> str:
    """Render a document back to Markdown.

    The separator rules are read off what the synthesizer actually emits rather than chosen:
    a heading is followed by a single newline when the next block is its content and a blank
    line when it is another heading, consecutive list items are separated by a single
    newline, and everything else by a blank line. That reproduces this product's own reports
    byte-for-byte; anything else is reported as `LOSSY` rather than quietly reshaped.

    **Not a path to the hash.** `report_hash` reads `report_markdown`, which is the model's
    own bytes and is never replaced by this function's output.
    """
    if not document.blocks:
        return ""

    out: list[str] = []
    for index, block in enumerate(document.blocks):
        if block.kind == "heading":
            out.append("#" * (block.level or 1) + " " + block.text)
        elif block.kind == "list_item":
            out.append("- " + block.text)
        else:
            out.append(block.text)

        nxt = document.blocks[index + 1] if index + 1 < len(document.blocks) else None
        if nxt is None:
            out.append("\n")
        elif block.kind == "heading" and nxt.kind != "heading":
            out.append("\n")
        elif block.kind == "list_item" and nxt.kind == "list_item":
            out.append("\n")
        else:
            out.append("\n\n")
    return "".join(out)
