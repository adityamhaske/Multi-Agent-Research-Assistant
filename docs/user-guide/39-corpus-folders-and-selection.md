# Research over the files you choose

Upload folders of documents to a project's corpus, pick any mix of folders and files, and ask
a question that only those files answer. Every claim in the report is checked against the
files you picked, and every citation opens at the place it quotes.

This page covers what you can upload, how folders and selection work, what "only these files"
does and does not guarantee, and what you see when your files cannot answer. It applies to the
desktop app and the server alike.

> **Not in a released version yet.** This page describes the current source on `main`. The
> installers on the download page have no folders, file selection or Offline, and read only the
> first two rows of the table below (plus CSV, as plain text). The rest arrive with the next release.

## What you can upload

| Kind | Extensions | How a citation names its place |
|---|---|---|
| PDF | `.pdf` | page |
| Web pages, Markdown, plain text | `.html .htm .md .markdown .txt .text .rst .json` | characters |
| Word, OpenDocument text, RTF | `.docx .odt .rtf` | heading, or table row |
| Spreadsheets | `.xlsx .xlsm .xls .ods .csv .tsv` | sheet and row |
| Presentations | `.pptx` | slide |
| E-books | `.epub` | chapter |
| Notebooks | `.ipynb` | cell |
| Source code, LaTeX, BibTeX, config | `.py .java .r .m .jl .c .cpp .js .ts .go .rs .sql .sh .tex .bib .yaml .toml .xml` and more | line |

Anything else is refused by name, with the list above, rather than read as text: a format whose
quotes cannot be located has no place in a corpus whose citations are checked.

**What is read, exactly.** Spreadsheets are read as the values a spreadsheet program shows, not
their formulas; hidden sheets are read and marked hidden. Word documents are read with tracked
changes accepted; footnotes, comments, headers and footers are not read. Notebook outputs keep
their text and say how many images were left out. Scanned PDFs need text recognition first; a
PDF with no text is refused, and pages without text are listed.

**Tables, slides and cells become text.** A spreadsheet row is read as `Row 14 — Item: Staff;
Cost: 1200`, with its header on every row, so a quote from it makes sense on its own. Quotes from
these files are marked as coming from a text rendering of the file.

Files are limited to 25 MB. Office files that would expand past 200 MB, or that are
password-protected, are refused with the reason.

## Folders

Choose **Choose folder**, or drop a folder onto the Corpus page, and its subfolders come with
it. The same file in two folders is stored once and listed in both. Folders can be renamed and
moved without changing anything that cites their files.

Deleting a folder removes the files filed **only** there, with every version; a file also in
another folder stays. Research that cited a deleted file keeps the quotes it gathered, but the
file itself can no longer be opened from it.

Each project has its own corpus, on the desktop app as on a server. Documents uploaded to the
desktop app before projects had separate corpora were moved to a project named **Documents from
before 3.1**, and the original store is kept as `corpus.legacy-3.0.sqlite` in the app's data
folder.

## Choosing files and asking

Tick folders and files in **Choose files to research** — a folder's box selects everything
beneath it — then **Ask about these files**. The research form opens with your selection
attached and **Only the files you selected** switched on.

The selection is fixed when the research starts: the exact version of each file is recorded,
and a file you replace, delete or add afterwards does not change what that research may read.
The run page lists the files it used.

## Two guarantees, and what each one means

**Only the files you selected** limits the evidence. Every search, every passage read and every
citation comes from the selected files; nothing from the web, another project or an auto-saved
report can become evidence, and the report's own record and its exported bundle say which files
were selected. It does **not** keep your question private: the question and excerpts from your
files are sent to whichever model provider each agent is set to use.

**Offline** limits where the models run. Turn it on and the research refuses to start unless
every agent uses a model on this computer — Ollama, or a custom endpoint on this machine — and
names any agent that does not. Offline research never reads the web.

The two are independent: you can have either without the other.

## How the answer is checked

Every sentence of a report on selected files is split into the individual claims it makes, and
each claim is checked against the passages its citations point to:

- numbers and dates must appear in those passages;
- a citation that does not support its claim is removed from it;
- a conclusion must follow from the findings it rests on.

A passage holding a claim your files do not support is rewritten from what they do support, and
checked again. A passage that still fails is removed, with a note saying so where it was. The
run page shows how many claims were supported, kept out and removed.

**When your files cannot answer**, the research ends with *"Your selected files don't answer this
question. Nothing was answered from outside them."* — not with an answer from the model's own
knowledge.

**When a claim could not be checked** — the checking model was unavailable, or the spending
limit ran out part-way — the research ends without a report rather than presenting unchecked
claims as checked. The checking calls count against the same spending limit as the research.

## Opening a citation

In a report's sources, **Open where it's cited** shows the file's text with the cited passage
highlighted and named by its page, sheet and row, slide, cell or line.
