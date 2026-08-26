"""
Splitting an approved report into retrievable chunks (docs/14 §4).

Pure text in, pure text out — no host, no model, no I/O — so the server and the desktop
build chunk identically and the behaviour is testable without a database or a key.

Three choices worth stating, because each one shows up directly in retrieval quality:

1. **Split on structure, not on a character count.** Reports are Markdown with headings
   and paragraphs. Cutting mid-sentence every N characters produces chunks that begin
   halfway through a claim, which embed poorly and read worse when quoted back with a
   citation.

2. **Carry the heading down.** A chunk lifted from under "## Limitations" loses its frame
   the moment it is retrieved on its own. Prefixing the nearest heading costs a few
   tokens and keeps the retrieved text self-describing.

3. **Overlap by a sentence, not by a fixed slice.** A claim that straddles a boundary
   should be wholly present in one of the two chunks; snapping the overlap to a sentence
   start avoids beginning a chunk with a fragment.

Citation markers (`[1]`, `[2]`) are deliberately preserved. They are what lets a chat
answer resolve through the report to the original sources it cites (docs/14 §5).
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass

# ~1200 characters is roughly 300 tokens: large enough to hold a complete claim with its
# supporting sentence, small enough that eight of them (the retrieval default) stay a
# cheap prompt. Both matter — the budget ceiling in docs/12 is the whole strategy.
TARGET_CHARS = 1200
OVERLAP_CHARS = 180
# Below this a chunk is a heading or a stray line; it gets merged rather than stored, so
# retrieval never returns a hit that carries no information.
MIN_CHARS = 200

# A heading is a natural chunk boundary, but only once the open chunk has enough in it to
# stand alone. Flushing at every heading regardless would shard a report with many short
# sections into many small chunks — and each chunk is an embedding, which is spend. This
# keeps section-aligned boundaries where sections are substantial and merges them where
# they are not.
_HEADING_FLUSH_RATIO = 0.6

_HEADING_RE = re.compile(r"^#{1,6}\s+\S")
# Sentence end: a terminator, optionally followed by a closing quote or bracket, then
# whitespace. Written as two fixed-width lookbehinds because Python's `re` rejects a
# variable-width one. Abbreviations will occasionally fool this; the cost is a slightly
# odd split, never a lost sentence.
_SENTENCE_END_RE = re.compile(r"(?:(?<=[.!?])|(?<=[.!?][\"')\]]))\s+")


def _normalise(text: str) -> str:
    """Trim trailing whitespace and collapse runs of blank lines to one."""
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    out: list[str] = []
    for line in lines:
        if not line and out and not out[-1]:
            continue
        out.append(line)
    return "\n".join(out).strip()


def _blocks(text: str) -> list[str]:
    """Paragraph-ish blocks: split on blank lines, then peel headings off their bodies.

    The second half is load-bearing and was missing. Markdown does not require a blank
    line after a heading, and this product's own synthesizer does not emit one — so
    `## Summary\nRetrieval-augmented generation…` arrived as a *single* block that
    `_HEADING_RE.match` accepted, because the block merely *starts* with a heading. The
    caller then kept `block.splitlines()[0]` as the heading and dropped everything after
    it. A whole report of such sections chunked to nothing at all: the text was silently
    discarded, project memory stayed empty, and no error was raised anywhere.

    So a heading line is always its own block, and the prose under it is always another.
    """
    out: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        run: list[str] = []
        for line in block.splitlines():
            if _HEADING_RE.match(line):
                if run:
                    out.append("\n".join(run).strip())
                    run = []
                out.append(line.strip())
            else:
                run.append(line)
        if run and "\n".join(run).strip():
            out.append("\n".join(run).strip())
    return out


def _split_long(block: str, limit: int) -> list[str]:
    """Break an oversized block on sentence boundaries, then on words as a last resort."""
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_END_RE.split(block):
        if not sentence:
            continue
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= limit or not current:
            current = candidate
        else:
            pieces.append(current)
            current = sentence
    if current:
        pieces.append(current)

    # A single sentence longer than the limit (a table row, a URL list) still has to fit.
    out: list[str] = []
    for piece in pieces:
        while len(piece) > limit:
            cut = piece.rfind(" ", 0, limit)
            cut = cut if cut > limit // 2 else limit
            out.append(piece[:cut].strip())
            piece = piece[cut:].strip()
        if piece:
            out.append(piece)
    return out


def _tail_overlap(text: str, overlap: int) -> str:
    """The last whole sentence(s) of `text`, up to `overlap` characters."""
    if overlap <= 0 or not text:
        return ""
    window = text[-overlap:]
    parts = _SENTENCE_END_RE.split(window, maxsplit=1)
    # Prefer starting at a sentence boundary; fall back to a word boundary.
    if len(parts) > 1 and parts[1].strip():
        return parts[1].strip()
    space = window.find(" ")
    return window[space + 1 :].strip() if space != -1 else ""


def chunk_report(
    text: str,
    *,
    target_chars: int = TARGET_CHARS,
    overlap_chars: int = OVERLAP_CHARS,
    min_chars: int = MIN_CHARS,
) -> list[str]:
    """Split a report into overlapping, heading-aware chunks.

    Deterministic: the same report always produces the same chunks, which is what makes
    re-ingestion idempotent against the `(source_session_id, chunk_index)` unique key.
    """
    normalised = _normalise(text or "")
    if not normalised:
        return []

    heading = ""
    chunks: list[str] = []
    current = ""

    def flush() -> None:
        """Store the open chunk, unless it turned out to be headings and nothing else.

        A chunk of pure headings is a retrieval hit that carries no information — it
        would match a topical query and then contribute nothing to the answer.
        """
        nonlocal current
        body = current.strip()
        if body and not all(_HEADING_RE.match(line) for line in body.splitlines() if line.strip()):
            chunks.append(body)
        current = ""

    for block in _blocks(normalised):
        if _HEADING_RE.match(block):
            # A heading belongs with what follows it. Close the open chunk first, but
            # only if it is substantial — see _HEADING_FLUSH_RATIO.
            heading = block.splitlines()[0].strip()
            if len(current) >= target_chars * _HEADING_FLUSH_RATIO:
                flush()
                current = heading
            else:
                current = f"{current}\n\n{heading}" if current else heading
            continue

        # An oversized block is split to leave room for the heading and overlap that a
        # continuation chunk prepends; without that reservation the assembled chunk
        # overshoots `target_chars` by exactly the carry, and "chunks are at most N" stops
        # being true.
        room = max(target_chars // 2, target_chars - overlap_chars - len(heading) - 4)
        for piece in [block] if len(block) <= target_chars else _split_long(block, room):
            candidate = f"{current}\n\n{piece}" if current else piece
            if len(candidate) <= target_chars or not current:
                current = candidate
                continue

            flush()
            # Re-open with the heading and a sentence of overlap so the next chunk still
            # says what it is about and does not start mid-claim.
            opener = heading if heading else ""
            carry = _tail_overlap(chunks[-1] if chunks else "", overlap_chars)
            current = "\n\n".join(part for part in (opener, carry, piece) if part)

    flush()

    # Merge a runt tail into its predecessor rather than storing a chunk too small to
    # carry a claim. A single short chunk is kept: a short report is still a report.
    if len(chunks) > 1 and len(chunks[-1]) < min_chars:
        tail = chunks.pop()
        chunks[-1] = f"{chunks[-1]}\n\n{tail}"

    return chunks


# ── Corpus documents (docs/12 M10) ──────────────────────────────────────────────
#
# Reports are our own Markdown and get heading-aware chunks above. Ingested corpus
# documents are arbitrary prose, and their requirement is different: every chunk must
# cite an EXACT location in its source (docs/12 M10 DoD). So a corpus chunk is a
# verbatim span [start, end) of the extracted text — no carried headings, no
# reassembled openers — which makes "text[start:end] is the chunk" true by
# construction rather than by convention.


@dataclass(frozen=True)
class DocumentChunk:
    """One chunk of an ingested document, with its exact location in the source.

    `text == source[start:end]` holds verbatim. `page` is the 1-based page the chunk
    starts on (PDFs), or None when the source has no page structure (MD/TXT) — the
    offsets are the universal locator, the page is the human-readable one.
    """

    text: str
    start: int
    end: int
    page: int | None


# Where a new chunk may begin: the start of a paragraph, or the whitespace run after
# a sentence terminator. Splitting only on these points keeps chunks starting at
# sentence boundaries instead of mid-claim.
_PIECE_BREAK_RE = re.compile(r"\n\s*\n|[.!?][\"')\]]*\s+")


def _split_points(text: str) -> list[int]:
    """Offsets at which a piece of text can legally start."""
    return [m.end() for m in _PIECE_BREAK_RE.finditer(text)]


def _page_for(page_starts: list[int], offset: int) -> int | None:
    """1-based page number containing `offset`, or None without page structure."""
    if len(page_starts) <= 1:
        return None
    return bisect_right(page_starts, offset)


def chunk_document(
    text: str,
    *,
    page_starts: list[int] | None = None,
    target_chars: int = TARGET_CHARS,
    overlap_chars: int = OVERLAP_CHARS,
    min_chars: int = MIN_CHARS,
) -> list[DocumentChunk]:
    """Split an ingested document into verbatim, overlapping, offset-tracked chunks.

    Deterministic like `chunk_report`, and idempotency-friendly: the same extracted
    text always yields the same spans. Overlap is implemented by starting the next
    chunk at most `overlap_chars` before the previous end, snapped to a piece
    boundary — so the overlap region belongs verbatim to BOTH chunks' spans.
    """
    body = text or ""
    first_nonws = len(body) - len(body.lstrip())
    if first_nonws >= len(body):
        return []

    pages = page_starts or []
    points = _split_points(body)
    chunks: list[DocumentChunk] = []
    start = first_nonws

    while start < len(body):
        if start + target_chars >= len(body):
            raw_end = len(body)
        else:
            # Snap to the last piece boundary inside the window. When there is none
            # (one enormous sentence / table row) cut at the limit — a chunk that
            # cannot fit whole beats a chunk that never ends.
            lo = bisect_right(points, start)
            hi = bisect_right(points, start + target_chars)
            raw_end = points[hi - 1] if hi > lo else start + target_chars

        # Trim surrounding whitespace WITHOUT leaving the verbatim span: the chunk
        # text is exactly body[start:end].
        end = raw_end
        while start < end and body[start].isspace():
            start += 1
        while end > start and body[end - 1].isspace():
            end -= 1
        if start >= end:
            break

        chunks.append(
            DocumentChunk(text=body[start:end], start=start, end=end, page=_page_for(pages, start))
        )

        if raw_end >= len(body):
            break

        # Next chunk opens within the overlap window, at the first piece boundary —
        # or right after this chunk when the window holds none (progress is mandatory).
        floor = max(raw_end - overlap_chars, start + 1)
        idx = bisect_left(points, floor)
        nxt = points[idx] if idx < len(points) else None
        start = nxt if nxt is not None and nxt < raw_end else raw_end

    # A runt tail carries no claim of its own; fold its span into the predecessor.
    if len(chunks) > 1 and (chunks[-1].end - chunks[-1].start) < min_chars:
        tail = chunks.pop()
        prev = chunks[-1]
        chunks[-1] = DocumentChunk(
            text=body[prev.start : tail.end], start=prev.start, end=tail.end, page=prev.page
        )

    return chunks
