# Exports

Three formats.

| Format | Endpoint | Contains |
|---|---|---|
| **Markdown** | `GET /runs/{id}/export.md` | The report as written, plus a model-attribution block |
| **PDF** | `GET /runs/{id}/export.pdf` | The report typeset, with citations as superscripts, a numbered sources list, and model attribution |
| **Bundle** | `GET /runs/{id}/bundle.json` | Everything needed to verify the report offline |

## Getting one

**Markdown and PDF** are on the run's **Report** tab, beside **Copy**, for whichever revision
you are reading — before approval too.

**The verification bundle** is on the **Artifact** tab, which exists once a person has
approved the report at the review gate: approving is what freezes it. The tab shows the
verifier's own checks, names any agent that ran on
[replaced instructions](38-agent-instructions.md), and offers all three downloads, with the
bundle first — Markdown and PDF are the report alone, readable but not checkable. **Verify it
yourself** expands to the exact command for checking the bundle, so the instruction is where
the file is.

All three work on the self-hosted server. On the desktop app, Markdown and the bundle work the
same way; **PDF** is the app's own Print → Save as PDF rather than a server render, and the PDF
button says so (see below).

Research recorded as a session, on the earlier pipeline, keeps its own export routes under
`/research/{id}/` — see the [API reference](../reference/34-api.md).

## Markdown

The report text, unchanged, with a trailing block recording **which model produced which
part** — the per-role routing the run actually ran with, not the routing currently
configured.

Filename: `research-<first 8 chars of run id>.md`.

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

The interesting one. A `.bundle.json` is a self-contained, auditable record of the run — a
bill of materials for a research report:

- the **report** and its SHA-256;
- every **claim** with the citation indices it carries;
- every **evidence snippet** with a content hash and the source it came from;
- the **sources** table, and any **contradictions** surfaced;
- the **models** that ran, the **cost**, the **token counts**, the elapsed time;
- the **prompts** the run used — each one's full text, its SHA-256, and whether you had
  replaced it — and whether your custom instructions were applied (from 3.0.0);
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
earlier draft or a different run.

A bundle whose agents ran on replaced instructions verifies like any other — its hashes are
real hashes of what really ran — so the verifier prints a *CUSTOMISED AGENTS* banner above the
verdict and lists the replaced prompts. The prompts' text is in the bundle in full, so anyone
you share it with can read your instructions.

**Bundles from 3.0.0 on are format version 2.** A verifier from before 3.0.0 refuses them;
the one from 3.0.0 or later verifies versions 1 and 2 alike. Research recorded before 3.0.0
still exports as version 1, with no prompts recorded.

Full specification: [Research bundle format](../reference/15-bundle-format.md).

## Demo runs are stamped

A run made with scripted models and fixture sources is marked in the database, and every
export path stamps the artifact — **on both hosts**:

- `.md` and `.pdf` carry a prominent **⚠ DEMO — NOT REAL RESEARCH** banner at the top;
- the bundle carries a hash-covered `demo` field instead, and the verifier prints the
  provenance above its verdict.

The banner text and the "stamped iff demo" rule live in one place, `research_engine.bundle`,
and the server and the desktop sidecar both call it. That is not decoration: the desktop
`.md` export shipped *unstamped* for a release while this page already promised otherwise,
which is exactly the unmarked fixture report the flag exists to prevent. A parity test now
fails the build if either host stops applying it, or if either starts stamping the bundle.

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
