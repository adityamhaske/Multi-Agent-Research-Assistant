# Exports

Three formats. The bundle requires the session to be `COMPLETED` and refuses otherwise.

| Format | Endpoint | Contains |
|---|---|---|
| **Markdown** | `GET /research/{id}/export.md` | The report as written, plus a model-attribution block |
| **PDF** | `GET /research/{id}/export.pdf` | The report typeset, with citations as superscripts, a numbered sources list, and model attribution |
| **Bundle** | `GET /research/{id}/export.bundle.json` | Everything needed to verify the report offline |

## Getting one

Open a completed report. The three buttons sit beside its heading — **.md**, **PDF**, and
**.bundle.json** — and each downloads the file directly. There is no separate export screen.

Below the metrics row, **Verify this report independently** expands to the exact command for
checking a bundle, so the instruction is where the file is.

All three work on the self-hosted server. On the desktop app, `.md` and `.bundle.json` work
the same way; **PDF** is the app's own Print → Save as PDF rather than a server render (see
below).

## Markdown

The report text, unchanged, with a trailing block recording **which model produced which
part** — the per-role routing the session actually ran with, not the routing currently
configured.

Filename: `research-<first 8 chars of session id>.md`.

## PDF

Rendered server-side: Markdown → HTML → PDF via WeasyPrint, with a self-contained print
stylesheet and no external assets, so it renders identically offline.

Inline `[n]` markers become superscripts, followed by a numbered sources list and the same
model-attribution block.

If the environment lacks WeasyPrint's native libraries the endpoint returns **501** with the
reason rather than a broken file. The Docker image installs them; the desktop build
deliberately omits WeasyPrint — its dependency chain on Windows is a packaging tar pit — and
uses the WebView's own print-to-PDF instead.

## Research bundle

The interesting one. A `.bundle.json` is a self-contained, auditable record of the session —
a bill of materials for a research report:

- the **report** and its SHA-256;
- every **claim** with the citation indices it carries;
- every **evidence snippet** with a content hash and the source it came from;
- the **sources** table, and any **contradictions** surfaced;
- the **models** that ran, the **cost**, the **token counts**, the elapsed time;
- the full **approval chain** — every approve or rework, its feedback, the hash of the draft
  it applied to, and when;
- the **agent trace**, and a `trace_available` flag distinguishing "the host has no durable
  event log" from "nothing happened" — both the server and the desktop app write one, so it
  is `true` on each;
- a `bundle_hash` covering all of the above.

Verify one with no AI, no network, and no database:

```bash
python -m research_engine.verify_bundle path/to/research.bundle.json
```

Exit code 0 if valid, 1 if tampered. Seven checks run: schema validity, bundle integrity,
report integrity, evidence integrity, citation resolution, claim-evidence linkage, and
approval-chain integrity.

The load-bearing one is the last: at least one `approved` entry's `draft_hash` must match
the report's own hash, which proves the approval was given for *this* report rather than an
earlier draft or a different session.

Full specification: [Research bundle format](../reference/15-bundle-format.md).

## Demo runs are stamped

A run made with scripted models and fixture sources is marked in the database, and every
export path stamps the artifact:

- `.md` and `.pdf` carry a prominent **⚠ DEMO — NOT REAL RESEARCH** banner at the top;
- the bundle carries a hash-covered `demo` field instead, and the verifier prints the
  provenance above its verdict.

The bundle is stamped differently on purpose. Injecting prose into the report body would
change the report hash and break the approval-chain check, making every demo bundle fail
verification for a reason that has nothing to do with its integrity — teaching readers that
FAIL is normal for demos would defeat the verifier far more thoroughly than a missing
banner would.

Because the flag is persisted rather than inferred from the process's mode, a demo report
cannot be laundered into a real-looking artifact by any route that bypasses the UI.

## Copying and sharing

The report page also offers copy-to-clipboard and browser print. Shareable read-only report
links are [planned](../project/10-roadmap.md), not built — today an export is the way to
hand a report to someone else, and the bundle is the way to hand it to someone who should
not have to take your word for it.
