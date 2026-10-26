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
    ".json": Format("txt", "plain text"),
    # Tier B (RFC V3.1 §10.2): exact-pinned parsers, both MIT, with cp314 wheels on every
    # target (G-1). Word documents and spreadsheets, cached values only.
    ".docx": Format("docx", "Word document", "docx"),
    ".xlsx": Format("spreadsheet", "Excel workbook", "python_calamine"),
    ".xlsm": Format("spreadsheet", "Excel workbook", "python_calamine"),
    ".xls": Format("spreadsheet", "Excel workbook", "python_calamine"),
    ".ods": Format("spreadsheet", "OpenDocument spreadsheet", "python_calamine"),
    # Tier A (RFC V3.1 §10.2): the standard library reads all of these.
    ".csv": Format("csv", "CSV"),
    ".tsv": Format("csv", "TSV"),
    ".ipynb": Format("ipynb", "Jupyter notebook"),
    **{
        ext: Format("code", "source code")
        for ext in (
            ".py",
            ".java",
            ".r",
            ".m",
            ".jl",
            ".c",
            ".h",
            ".cpp",
            ".hpp",
            ".cc",
            ".cs",
            ".js",
            ".ts",
            ".tsx",
            ".jsx",
            ".go",
            ".rs",
            ".rb",
            ".scala",
            ".kt",
            ".swift",
            ".sql",
            ".sh",
            ".ps1",
            ".yaml",
            ".yml",
            ".toml",
            ".ini",
            ".cfg",
            ".xml",
            ".tex",
            ".sty",
            ".cls",
            ".bib",
        )
    },
}

#: Bounds on a table rendered into text, beyond which the file is refused by name rather than
#: indexed in part (§10.2). A partial index would answer as if it had read the whole sheet.
MAX_TABLE_ROWS = 1_048_576
MAX_TABLE_COLUMNS = 256
MAX_TABLE_CELLS = 2_000_000
#: A notebook cell's text output is kept up to this many characters, then marked as cut.
MAX_NOTEBOOK_OUTPUT_CHARS = 4096


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
        if kind == "docx":
            return _extract_docx(data)
        if kind == "spreadsheet":
            return _extract_spreadsheet(data, _extension(filename))
        if kind == "csv":
            return _extract_table(data, delimiter="\t" if _extension(filename) == ".tsv" else None)
        if kind == "ipynb":
            return _extract_notebook(data)
        if kind == "code":
            # Exact source: what a citation quotes is the file as written. Only the BOM and
            # Windows line endings go, as for every text format, so offsets are stable.
            text = data.decode("utf-8-sig", errors="replace").replace("\r\n", "\n")
            if not text.strip():
                raise ValueError("Document contains no text.")
            return Extraction(text, [0], "code")
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


def _extract_table(data: bytes, *, delimiter: str | None) -> Extraction:
    """A CSV or TSV as one line per data row, each carrying its own header (§10.2).

    `Row N — Header: value; Header: value`. The header is written into every row because a
    quoted row must be readable on its own, and verbatim matching survives only if the
    header is part of the text that is quoted. N is the row number a spreadsheet shows —
    the header is row 1 — so "row 14" in a citation is row 14 in the user's own program.
    Empty cells are left out rather than rendered as "Header: ".
    """
    import csv

    raw = data.decode("utf-8-sig", errors="replace").replace("\r\n", "\n")
    if not raw.strip():
        raise ValueError("Document contains no text.")
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(raw[:4096], delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
    rows = list(csv.reader(io.StringIO(raw), delimiter=delimiter))
    rows = [r for r in rows if any(cell.strip() for cell in r)]
    if len(rows) < 2:
        raise ValueError("The table has a header row but no data rows.")
    header = [h.strip() or f"Column {i + 1}" for i, h in enumerate(rows[0])]
    width = max(len(r) for r in rows)
    if (
        len(rows) > MAX_TABLE_ROWS
        or width > MAX_TABLE_COLUMNS
        or len(rows) * width > MAX_TABLE_CELLS
    ):
        raise ValueError(
            f"The table is {len(rows)} rows by {width} columns; the corpus reads at most "
            f"{MAX_TABLE_ROWS} rows, {MAX_TABLE_COLUMNS} columns and {MAX_TABLE_CELLS} cells."
        )
    parts: list[str] = []
    segments: list[tuple[int, str]] = []
    offset = 0
    for number, row in enumerate(rows[1:], start=2):
        cells = [
            f"{header[i] if i < len(header) else f'Column {i + 1}'}: {value.strip()}"
            for i, value in enumerate(row)
            if value.strip()
        ]
        line = f"Row {number} — " + "; ".join(cells)
        segments.append((offset, f"row {number}"))
        parts.append(line)
        offset += len(line) + 1
    return Extraction("\n".join(parts), [0], "csv", segments, LINEARIZED)


def _extract_notebook(data: bytes) -> Extraction:
    """A Jupyter notebook as its cells in order, each headed `## Cell N (markdown|code)`.

    Text outputs (`stream`, `text/plain`) follow their cell under `Output:`, cut at
    `MAX_NOTEBOOK_OUTPUT_CHARS`; images and other rich outputs are left out and counted in
    the cell's heading, so the text never claims to show what it cannot.
    """
    import json

    try:
        notebook = json.loads(data.decode("utf-8-sig"))
        cells = notebook["cells"]
        if not isinstance(cells, list):
            raise TypeError("cells is not a list")
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"Not a readable notebook: {exc}") from exc

    def joined(value) -> str:
        return "".join(value) if isinstance(value, list) else str(value or "")

    parts: list[str] = []
    segments: list[tuple[int, str]] = []
    offset = 0
    for number, cell in enumerate(cells, start=1):
        if not isinstance(cell, dict):
            continue
        kind = "code" if cell.get("cell_type") == "code" else "markdown"
        body = joined(cell.get("source")).replace("\r\n", "\n").rstrip()
        texts, dropped = [], 0
        for output in cell.get("outputs") or []:
            if not isinstance(output, dict):
                continue
            if output.get("output_type") == "stream":
                texts.append(joined(output.get("text")))
            elif "text/plain" in (output.get("data") or {}):
                texts.append(joined(output["data"]["text/plain"]))
                dropped += len(output["data"]) - 1
            elif output.get("data"):
                dropped += len(output["data"])
        heading = f"## Cell {number} ({kind})"
        if dropped:
            heading += f" — {dropped} non-text output(s) not shown"
        block = heading + "\n" + body
        out = "\n".join(t.rstrip() for t in texts if t.strip())
        if out:
            if len(out) > MAX_NOTEBOOK_OUTPUT_CHARS:
                out = out[:MAX_NOTEBOOK_OUTPUT_CHARS] + " [output cut]"
            block += "\nOutput:\n" + out
        segments.append((offset, f"cell {number}"))
        parts.append(block)
        offset += len(block) + 2
    text = "\n\n".join(parts)
    if not text.strip():
        raise ValueError("The notebook has no cells.")
    return Extraction(text, [0], "ipynb", segments, LINEARIZED)


#: An encrypted Office file is an OLE compound file, not a ZIP: password protection replaces
#: the archive with an encrypted container. Recognised by its magic number and refused by
#: name, rather than reported as a corrupt file.
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _refuse_encrypted_office(data: bytes) -> None:
    if data[:8] == _OLE_MAGIC:
        raise ValueError(
            "The file is password-protected (or a pre-2007 .doc). Save an unprotected "
            ".docx/.xlsx copy and upload that."
        )


def _extract_docx(data: bytes) -> Extraction:
    """A Word document's body in order: headings, paragraphs, tables (§10.2).

    Headings are prefixed `#` by level, so the text keeps the document's outline. Paragraph
    text is every `w:t` in the paragraph, inserted runs included and deleted text
    (`w:delText`) excluded — the accepted-changes view, which is what a reader of the
    finished document sees. Tables become `Row N — Header: value; …` like a CSV. Footnotes,
    comments, headers and footers are not read (a known limit, stated in the docs).
    """
    _refuse_encrypted_office(data)
    check_archive(data)
    import docx
    from docx.oxml.ns import qn

    document = docx.Document(io.BytesIO(data))
    parts: list[str] = []
    segments: list[tuple[int, str]] = []
    offset = 0
    path: list[str] = []
    tables = 0

    def add(text: str, label: str) -> None:
        nonlocal offset
        segments.append((offset, label))
        parts.append(text)
        offset += len(text) + 1

    for block in document.element.body.iterchildren():
        if block.tag == qn("w:p"):
            text = "".join(t.text or "" for t in block.iter(qn("w:t"))).strip()
            if not text:
                continue
            style = block.find(qn("w:pPr"))
            style_id = ""
            if style is not None and style.find(qn("w:pStyle")) is not None:
                style_id = style.find(qn("w:pStyle")).get(qn("w:val")) or ""
            level = (
                int(style_id[7:])
                if style_id.startswith("Heading") and style_id[7:].isdigit()
                else 0
            )
            if level:
                path = path[: level - 1] + [text]
                add("#" * level + " " + text, " › ".join(path))
            else:
                add(text, " › ".join(path) or "body")
        elif block.tag == qn("w:tbl"):
            tables += 1
            rows = [
                [
                    "".join(t.text or "" for t in cell.iter(qn("w:t"))).strip()
                    for cell in row.iter(qn("w:tc"))
                ]
                for row in block.iter(qn("w:tr"))
            ]
            if not rows:
                continue
            header = [h or f"Column {i + 1}" for i, h in enumerate(rows[0])]
            for number, row in enumerate(rows[1:], start=2):
                cells = [
                    f"{header[i] if i < len(header) else f'Column {i + 1}'}: {v}"
                    for i, v in enumerate(row)
                    if v
                ]
                if cells:
                    add(f"Row {number} — " + "; ".join(cells), f"table {tables} row {number}")
    text = "\n".join(parts)
    if not text.strip():
        raise ValueError("The document contains no text.")
    return Extraction(text, [0], "docx", segments, LINEARIZED)


def _cell(value) -> str:
    """One spreadsheet value as text: integers without `.0`, dates as ISO, the rest as is."""
    import datetime as _dt

    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, _dt.datetime | _dt.date | _dt.time):
        return value.isoformat()
    return str(value).strip()


def _extract_spreadsheet(data: bytes, ext: str) -> Extraction:
    """Every sheet in workbook order: `## Sheet: <name>`, then its rows like a CSV (§10.2).

    Cached values only — formulas are not indexed, so a citation quotes the number a reader
    of the workbook sees. Hidden sheets are read and marked `(hidden)`: leaving them out
    could hide evidence, and the mark tells the reader it was not on screen. Merged cells
    take their top-left value, which is what calamine reports. Row numbers are the sheet's
    own, so "row 14" in a citation is row 14 in the spreadsheet program.
    """
    if ext != ".xls":  # .xls is an OLE file by design; the others are ZIP archives
        _refuse_encrypted_office(data)
        check_archive(data)
    from python_calamine import CalamineWorkbook

    workbook = CalamineWorkbook.from_filelike(io.BytesIO(data))
    visibility = {
        m.name: str(getattr(m, "visible", "visible")).lower() for m in workbook.sheets_metadata
    }
    parts: list[str] = []
    segments: list[tuple[int, str]] = []
    offset = 0
    cells_seen = 0
    for name in workbook.sheet_names:
        rows = workbook.get_sheet_by_name(name).to_python(skip_empty_area=False)
        numbered = [(i + 1, [_cell(v) for v in row]) for i, row in enumerate(rows)]
        numbered = [(n, row) for n, row in numbered if any(row)]
        if not numbered:
            continue
        width = max(len(row) for _, row in numbered)
        cells_seen += len(numbered) * width
        if (
            len(numbered) > MAX_TABLE_ROWS
            or width > MAX_TABLE_COLUMNS
            or cells_seen > MAX_TABLE_CELLS
        ):
            raise ValueError(
                f"Sheet {name!r} is {len(numbered)} rows by {width} columns; the corpus reads "
                f"at most {MAX_TABLE_ROWS} rows, {MAX_TABLE_COLUMNS} columns and "
                f"{MAX_TABLE_CELLS} cells per workbook."
            )
        hidden = "" if "visible" == visibility.get(name, "visible").split(".")[-1] else " (hidden)"
        heading = f"## Sheet: {name}{hidden}"
        segments.append((offset, f"Sheet {name}"))
        parts.append(heading)
        offset += len(heading) + 1
        header_row, header = numbered[0]
        header = [h or f"Column {i + 1}" for i, h in enumerate(header)]
        for number, row in numbered[1:]:
            cells = [
                f"{header[i] if i < len(header) else f'Column {i + 1}'}: {v}"
                for i, v in enumerate(row)
                if v
            ]
            line = f"Row {number} — " + "; ".join(cells)
            segments.append((offset, f"Sheet {name}, row {number}"))
            parts.append(line)
            offset += len(line) + 1
    text = "\n".join(parts)
    if not text.strip():
        raise ValueError("The workbook has no data.")
    return Extraction(text, [0], "spreadsheet", segments, LINEARIZED)
