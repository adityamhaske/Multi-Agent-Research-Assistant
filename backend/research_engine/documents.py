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

# A single document must be small enough that extracting, chunking, and embedding it
# stays a bounded operation on a laptop; 500 such documents (the M10 DoD scale) is
# ~12 GB in the worst case, which no corpus is. These are tripwires, not tuning knobs.
MAX_DOCUMENT_BYTES = 25 * 1024 * 1024
MAX_PDF_PAGES = 2000

_TEXT_EXTENSIONS = {
    ".txt": "txt",
    ".text": "txt",
    ".md": "md",
    ".markdown": "md",
    ".rst": "txt",
    ".csv": "txt",
    ".json": "txt",
}


def kind_for(filename: str) -> str:
    """The document kind for a filename, or raises for an unsupported format.

    Fail closed: the error names what IS supported instead of letting an odd file
    through as "text", where its bytes would surface as a citation later.
    """
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == ".pdf":
        return "pdf"
    kind = _TEXT_EXTENSIONS.get(ext)
    if kind is None:
        raise ValueError(
            f"Unsupported document type {ext or '(no extension)'!r}. The corpus accepts "
            "PDF, Markdown (.md/.markdown), and plain text (.txt) only — a format we "
            "cannot locate a quote inside cannot enter a citation-grade corpus."
        )
    return kind


def extract_document(filename: str, data: bytes) -> tuple[str, list[int], str]:
    """Extract `(text, page_starts, kind)` from raw document bytes.

    `page_starts[i]` is the offset in `text` where page `i + 1` begins; text formats
    get `[0]`, which the chunker reads as "no page structure — offsets only". The
    offsets are the load-bearing locator; pages exist so a human can flip to the spot.
    """
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError(
            f"Document is {len(data)} bytes; the corpus accepts at most "
            f"{MAX_DOCUMENT_BYTES} bytes per file."
        )

    kind = kind_for(filename)
    if kind == "pdf":
        return _extract_pdf(data)

    text = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
    if not text.strip():
        raise ValueError("Document contains no text.")
    return text, [0], kind


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
