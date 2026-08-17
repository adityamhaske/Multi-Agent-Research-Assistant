# Citations and verification

The central claim of this product is that its citations are checkable. This page describes
exactly what is checked, by what, and what happens when a check fails.

## What a citation is here

A citation is not a link. It is a chain of data, and each link in it is stored:

```
claim sentence  →  [n]  →  sources[n]  →  { url, title, snippets[] }
                                              ↑
                    the verbatim text the executor extracted from that page
```

The executor never returns a bare fact. Every piece of evidence carries the source URL, the
source title, the claim it supports, and a **verbatim snippet** — the actual text from the
page, capped at 500 characters. That snippet is the provenance unit; everything downstream
is a view of it.

A single page routinely supports several distinct facts, so a source carries **every**
snippet extracted from it, not one. Keeping only the first meant a chip could show a quote
that had nothing to do with the sentence it was attached to.

## Reading the report

Every factual claim carries `[n]` markers. Hover one and you get the source title, the
domain, and the verbatim snippet supporting *that* claim. The sources panel lists the same
table in full.

Markers that cannot be resolved render a visible **⚠ unverified** chip. This is the design,
not a bug report: a citation apparatus that renders broken markers as clean text is worse
than no apparatus, because it looks like evidence.

Rendering is deliberately conservative. Reports are model-generated Markdown rendered in
your browser, so raw HTML is never passed through — no `rehype-raw`, no
`dangerouslySetInnerHTML`, enforced by a check in CI. The citation chips are produced by a
dependency-free Markdown plugin rather than by injecting HTML. Remote images in report
Markdown are not rendered either; they become links, so injected content cannot exfiltrate
a reader's IP through a tracking pixel.

Today only **single** `[n]` markers become interactive chips. Grouped markers like
`[3, 11, 18]` still resolve in the sources table but are not hoverable.

## Citation resolution rate

Every completed report records what fraction of its in-text markers resolve to a real
source. It is shown on the session and on every row of history, and history can filter on
it.

**`Not measured` is a distinct state from `0%`.** A report that made no citable claims, and
a report where every marker is broken, are opposite findings; storing them as one number
would make an unmeasured value indistinguishable from a total failure. The column is
nullable and nothing renders `null` as zero.

The same function computes the number for the product and for the evaluation harness, so a
published figure and a displayed figure cannot disagree.

## What is checked, and where

| Check | When | On failure |
|---|---|---|
| Snippet is text that was actually fetched | During the run, against what the tools returned | The snippet is blanked and flagged — the citation keeps its source and loses its quote rather than showing an invented one |
| Markers resolve to the evidence list | Synthesis | One retry with the validation errors, then the run fails |
| Numbers in a claim appear in its snippet | Synthesis | Flagged in the citation-fidelity pass |
| Marker resolves to a source in the report | Render, and at export | ⚠ unverified chip; excluded from the resolution rate |
| Snippet content hash matches | Offline, by the bundle verifier | Verification fails |
| An `approved` entry hashes to this report | Offline, by the bundle verifier | Verification fails |

Two of those are worth spelling out.

**The snippet must be text that was really fetched.** The executor's output is checked
against what the tools actually returned during the run. A model that writes a plausible
quote from memory does not get to attach it to a real URL — that is a fabricated citation,
the precise failure this product exists to prevent.

**Contradictions are surfaced, not resolved.** When two sources cannot both be true, both
sides are quoted from snippets the detector was shown, and any pair whose source URL was not
in the evidence is dropped. The pairs appear in the report and the count appears at the
review gate. Nothing picks a winner.

## What is *not* checked

Stated plainly, because a verification story with a hidden gap is worse than none:

- **The critic grades per-task evidence, not the finished report.** Nothing at runtime
  re-checks that the synthesizer's use of `[n]` is faithful to the snippet it points at. That
  is measured offline by the [evaluation harness](../developers/08-testing-and-evaluation.md)
  and by the [citation-fidelity benchmark](../research/16-citation-fidelity-benchmark.md),
  not by a runtime gate.
- **Resolution is not truth.** A marker resolving means the source and its supporting
  snippet exist and match. It does not mean the source is correct, or that the claim is true
  in the world.
- **Evidence de-duplication is URL-exact.** The same article at two URLs becomes two
  sources.

## Offline verification

The `.bundle.json` export is the strongest form of this. It carries the report, every claim
with its cited indices, every evidence snippet with a SHA-256 content hash, the sources, the
contradictions, the model routing, the costs, and the full approval chain — and a
`bundle_hash` covering all of it.

```bash
python -m research_engine.verify_bundle path/to/research.bundle.json
```

Seven checks, no AI, no network, no database. Exit code 0 or 1. Full specification:
[Research bundle format](../reference/15-bundle-format.md).

## Chat citations

Follow-up chat over a finished report answers from that report and its sources, and says so.
The scope selector states what each option will and will not read, and a scoped answer
reports which grounding produced it.

Project chat answers from **approved reports in that project** and cites them as `[R1]`,
`[R2]`, resolving to the report title, date, and link — and through the report to its
original sources. A claim with no resolvable citation gets the same ⚠ chip as anywhere else.
Citations are computed from what was actually retrieved and then narrowed to the markers the
answer used, because listing an unused excerpt as a citation would be exactly the sources
theatre the ⚠ chip exists to prevent.
