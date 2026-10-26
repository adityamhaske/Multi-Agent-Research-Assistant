"""
Extracting text from ingested corpus documents (docs/12 M10, docs/13 §8).

Pure bytes in, text out — with the page boundaries a PDF has and an offset map the
chunker turns into exact citation locations. Supported: PDF, Markdown, plain text;
anything else is refused, because a format we cannot locate a quote inside has no
business entering a citation-grade corpus.

`pypdf` is imported lazily so an MD/TXT-only deployment (and every test that never
touches a PDF) does not pay for it, and so the engine's import surface stays small.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field

# A single document must be small enough that extracting, chunking, and embedding it
# stays a bounded operation on a laptop; 500 such documents (the M10 DoD scale) is
# ~12 GB in the worst case, which no corpus is. These are tripwires, not tuning knobs.
MAX_DOCUMENT_BYTES = 25 * 1024 * 1024
MAX_PDF_PAGES = 2000

#: ZIP-based formats are bounded *before* parsing, on what the archive says it would expand
#: to (internal/rfcs/V3.1-corpus-scope.md §11.2). A 25 MiB upload can declare gigabytes.
MAX_ARCHIVE_EXPANDED_BYTES = 200 * 1024 * 1024
MAX_ARCHIVE_RATIO = 100
MAX_ARCHIVE_MEMBERS = 10_000

VERBATIM, LINEARIZED = "verbatim", "linearized"


@dataclass(frozen=True)
class Extraction:
    """What a document becomes inside the corpus.

    `text` is canonical: deterministic for pinned parser versions, and every citation's
    quote is verified against it. `page_starts` are PDF pages (`[0]` for everything else).
    `segments` are `(start, label)` pairs, in order, naming where each sheet, row, slide,
    cell or chapter begins — the human-readable location of a citation, derived without
    touching the `corpus://` URL format (RFC D-13). `mode` is `linearized` when the text is
    a rendering of structure (a spreadsheet, a notebook) rather than the document's own
    prose, and the UI says so beside every quote from it (RFC D-14).
    """

    text: str
    page_starts: list[int]
    kind: str
    segments: list[tuple[int, str]] = field(default_factory=list)
    mode: str = VERBATIM


@dataclass(frozen=True)
class Format:
    kind: str
    label: str
    #: The module a lazily imported parser needs, so packaging can be checked against it
    #: (`research-sidecar.spec` hiddenimports). None for the standard library.
    parser_module: str | None = None


#: Every accepted extension, and the one place that list lives. The refusal message, the
#: download media types and the upload picker's list are all checked against this
#: (`tests/task/test_document_formats.py`): five homes used to disagree (audit C8).
FORMATS: dict[str, Format] = {
    ".pdf": Format("pdf", "PDF", "pypdf"),
    ".html": Format("html", "HTML", "bs4"),
    ".htm": Format("html", "HTML", "bs4"),
    ".md": Format("md", "Markdown"),
    ".markdown": Format("md", "Markdown"),
    ".txt": Format("txt", "plain text"),
    ".text": Format("txt", "plain text"),
    ".rst": Format("txt", "plain text"),
    ".csv": Format("txt", "plain text"),
    ".json": Format("txt", "plain text"),
}


def _extension(filename: str) -> str:
    return "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def kind_for(filename: str) -> str:
    """The document kind for a filename, or raises for an unsupported format.

    Fail closed: the error names what IS supported instead of letting an odd file
    through as "text", where its bytes would surface as a citation later.
    """
    ext = _extension(filename)
    fmt = FORMATS.get(ext)
    if fmt is None:
        labels = ", ".join(dict.fromkeys(f.label for f in FORMATS.values()))
        extensions = " ".join(sorted(FORMATS))
        raise ValueError(
            f"Unsupported document type {ext or '(no extension)'!r}. The corpus accepts "
            f"{labels} ({extensions}) — a format we cannot locate a quote inside cannot "
            "enter a citation-grade corpus."
        )
    return fmt.kind


def check_archive(data: bytes) -> None:
    """Refuse a ZIP-based document whose declared expansion is too large, before parsing.

    Reads only the central directory. A member's declared size is what a parser would
    allocate, so a bomb is refused on its own say-so, never by trying it.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Not a readable document: {exc}") from exc
    if len(members) > MAX_ARCHIVE_MEMBERS:
        raise ValueError(
            f"The file holds {len(members)} parts; the limit is {MAX_ARCHIVE_MEMBERS}."
        )
    total = sum(m.file_size for m in members)
    if total > MAX_ARCHIVE_EXPANDED_BYTES:
        raise ValueError(
            f"The file would expand to {total} bytes; the limit is {MAX_ARCHIVE_EXPANDED_BYTES}."
        )
    for m in members:
        if m.compress_size and m.file_size / m.compress_size > MAX_ARCHIVE_RATIO:
            raise ValueError(
                f"Part {m.filename!r} expands {m.file_size // m.compress_size}x; files that "
                f"compress more than {MAX_ARCHIVE_RATIO}x are refused."
            )


def extract(filename: str, data: bytes) -> Extraction:
    """The canonical extraction of one document, or a `ValueError` naming why not.

    Any other exception a parser raises is turned into a `ValueError` here, so an
    unreadable file is a refused upload (400) and never a server error (RFC B-5). A parser
    that is missing from the build is named as such rather than reported as a bad file.
    """
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError(
            f"Document is {len(data)} bytes; the corpus accepts at most "
            f"{MAX_DOCUMENT_BYTES} bytes per file."
        )
    kind = kind_for(filename)
    try:
        if kind == "pdf":
            text, page_starts, kind = _extract_pdf(data)
            return Extraction(text, page_starts, kind)
        if kind == "html":
            text, page_starts, kind = _extract_html(data)
            return Extraction(text, page_starts, kind)
        text = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
        if not text.strip():
            raise ValueError("Document contains no text.")
        return Extraction(text, [0], kind)
    except ValueError:
        raise
    except ImportError as exc:
        raise ValueError(
            f"This build cannot read {FORMATS[_extension(filename)].label} files "
            f"(missing {exc.name or 'parser'})."
        ) from exc
    except Exception as exc:  # noqa: BLE001 — every other parser failure is a refused file
        raise ValueError(f"Could not read this file: {type(exc).__name__}.") from exc


def extract_document(filename: str, data: bytes) -> tuple[str, list[int], str]:
    """`(text, page_starts, kind)` — the pre-3.1 shape of `extract`, kept for its callers."""
    result = extract(filename, data)
    return result.text, result.page_starts, result.kind


def _extract_pdf(data: bytes) -> tuple[str, list[int], str]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 — every parse failure means "not a PDF"
        raise ValueError(f"Not a readable PDF: {exc}") from exc

    if reader.is_encrypted:
        # A password prompt is not text we can locate quotes in. Refuse rather than
        # silently trying an empty password.
        raise ValueError("The PDF is encrypted. Remove the password before ingesting it.")
    if len(reader.pages) > MAX_PDF_PAGES:
        raise ValueError(
            f"PDF has {len(reader.pages)} pages; the corpus accepts at most "
            f"{MAX_PDF_PAGES} per file."
        )

    parts: list[str] = []
    page_starts: list[int] = []
    offset = 0
    for page in reader.pages:
        try:
            page_text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 — one broken page must not sink the document
            page_text = ""
        page_starts.append(offset)
        parts.append(page_text)
        offset += len(page_text) + 1  # the "\n" join below

    text = "\n".join(parts)
    if not text.strip():
        raise ValueError("The PDF contains no extractable text (scanned images need OCR first).")
    return text, page_starts, "pdf"


def _extract_html(data: bytes) -> tuple[str, list[int], str]:
    """Readable text from an HTML document, for indexing only.

    The *original* bytes are stored alongside this and are what the preview renders —
    in a sandboxed iframe, never in this origin. What goes into the index is the prose,
    because a citation's whole promise is that a verbatim snippet can be located inside
    the document, and a chunk of `<div class="col-md-6">` is text that means nothing.

    `script` and `style` are dropped rather than merely untagged: their bodies are not
    content, and indexing them would let an uploaded page inject arbitrary strings into a
    corpus a model later quotes as evidence.

    Same parser as `tools.read_webpage` (bs4 + lxml) so a page ingested as a file and the
    same page fetched by the executor produce comparable text.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(data, "lxml")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    text = soup.get_text("\n")
    # Collapse the blank-line storm tag removal leaves behind; offsets stay the locator,
    # so the only requirement is that this is deterministic.
    lines = [line.strip() for line in text.replace("\r\n", "\n").split("\n")]
    text = "\n".join(line for line in lines if line)
    if not text.strip():
        raise ValueError("Document contains no text.")
    return text, [0], "html"
