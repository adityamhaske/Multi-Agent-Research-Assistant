# Research bundle format (v1)

A research bundle (`.bundle.json`) is a self-contained, auditable export of one research
session — a bill of materials for a report. It carries not just the output but the evidence,
the sources, the costs, the agent trace, and the human approvals that produced it.

The format is pure JSON, designed to be parsed and verified **entirely offline**, with no
model, no network, and no database.

## Schema

The root object is a `BundleManifest` at version `1`.

```json
{
  "bundle_version": 1,
  "session_id": "uuid",
  "query": "The original user prompt",
  "research_depth": "balanced",

  "demo": false,

  "report": "# Final Markdown…",
  "report_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",

  "claims": [
    { "sentence": "The extracted claim sentence.", "citation_indices": [1, 3] }
  ],

  "evidence": [
    {
      "source_url": "https://example.com/source",
      "source_title": "Page Title",
      "snippet": "The COMPLETE stored evidence text (executor-extracted, 500-char cap).",
      "content_hash": "a591a6d40bf420404a011733cfb7b190d62c65bf0bcda32b57b277d9ad9f146e",
      "key_fact": "Summary of the snippet"
    }
  ],

  "sources": [
    { "index": 1, "url": "https://example.com/source", "title": "Page Title", "snippet": "" }
  ],

  "contradictions": [],

  "models": { "planner": "provider:model", "executor": "provider:model" },

  "cost_usd": 0.045,
  "tokens_input": 12500,
  "tokens_output": 3200,
  "elapsed_seconds": 45.2,

  "approval_chain": [
    {
      "action": "approved",
      "feedback": null,
      "draft_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "timestamp": "2026-08-13T12:00:00+00:00"
    }
  ],

  "trace": [ { "type": "agent_log", "agent": "planner", "message": "Planning…" } ],
  "trace_available": true,

  "created_at": "2026-08-13T12:05:00+00:00",
  "bundle_hash": "7a945b14f85e3a8936ef3eb1389c8a9167db9b48c26f63be246becc360f2ea99"
}
```

## Design constraints

### 1. Hashing

Every hash is a SHA-256 hex digest of UTF-8 encoded text.

### 2. `bundle_hash` scope

`bundle_hash` covers **all** fields including `trace` and `trace_available`, and excluding
only itself. To recompute it:

1. Set `bundle_hash` to `""`.
2. Serialise the object as JSON with **sorted keys**, `ensure_ascii=False`, and separators
   `(",", ":")` — no whitespace.
3. SHA-256 the resulting UTF-8 string.

Stripping the trace from a bundle that had one therefore breaks the hash, which is correct. An
absent trace (`trace_available: false`) is the truthful state, and the hash covers that truth.

### 3. Snippet completeness

`evidence[].snippet` is the **complete** stored evidence text — exactly what the executor
extracted, capped at 500 characters by the schema. It is **not** a display-truncated view of
something longer.

`content_hash` proves that exact text was not altered after research time, so it is provably
the text the citation-support judge ruled on.

The hash covers the **snippet**, not the source page. A live page is not reproducible — it
changes — whereas the snippet is a fixed artifact of the run.

### 4. Trace availability

`trace_available` distinguishes three states that would otherwise all be `trace: []`:

| `trace_available` | `trace` | Meaning |
|---|---|---|
| `true` | `[…]` | The full event log is present |
| `true` | `[]` | The log was available and genuinely empty — an edge case |
| `false` | `[]` | **The host does not support durable event logs**, as on the desktop sidecar. A documented capability gap, not missing data |

This is the unmeasured-versus-zero rule in the format itself.

### 5. Demo provenance

`demo` is `true` when the run used scripted models and fixture sources rather than a real
provider.

It sits beside the identity of the run rather than among the metrics, because someone
deciding whether to trust the file must not have to scroll past cost and token counts to
discover none of it was real. It is covered by `bundle_hash`, so a demo bundle cannot be
edited into a real-looking one without breaking verification.

**The report body is not stamped in a bundle**, unlike the `.md` and `.pdf` exports.
Injecting prose into the report would change `report_hash` and break the approval-chain
check, making every demo bundle fail verification for a reason unrelated to its integrity —
and teaching a reader that FAIL is normal for demos would defeat the verifier far more
thoroughly than a missing banner. The verifier prints the provenance above its verdict
instead.

### 6. Approval-chain contract

For a bundle to count as approved, `approval_chain` must contain at least one entry where
`action == "approved"` **and** whose `draft_hash` matches `report_hash` exactly.

That proves the approval was given for *this specific report* — not an earlier draft, and not
a different session.

`action` is `approved`, `rework_requested`, or `plan_approved`. A `plan_approved` entry
hashes the approved research design rather than a draft, so the design decision travels in
the same chain without ever satisfying the check above.

The rules these entries obey — who may write one, why the chain is ordered by id rather
than timestamp, why it is append-only without a database constraint enforcing it, and the
fact that `draft_hash` carries two different hashed objects — are set out under
[`audit_log` semantics](../architecture/05-data-model.md#semantics). Worth reading before
trusting a chain: verifying a bundle means trusting them.

## Standalone verifier

Ships with the engine. No model, no network, no database.

```bash
python -m research_engine.verify_bundle path/to/research.bundle.json
```

Exit code `0` if valid, `1` if tampered. `--format json` emits a machine-readable result.

Seven checks:

1. **Schema validity** — the JSON parses and matches the version 1 manifest.
2. **Bundle integrity** — the recomputed `bundle_hash` matches.
3. **Report integrity** — the recomputed `report_hash` matches.
4. **Evidence integrity** — every snippet's `content_hash` matches.
5. **Citation resolution** — every `[n]` marker in the report body resolves to a `sources`
   entry.
6. **Claim–evidence linkage** — every cited source in a claim points to a source that has at
   least one evidence snippet behind it.
7. **Approval-chain integrity** — a valid, linked `approved` entry exists per §6.

Demo provenance is reported alongside the verdict rather than inside the notes, because a
demo bundle verifies perfectly well — its hashes match and its citations resolve — and would
otherwise print a clean PASS with nothing to say that none of it was real.

## Stability

This is intended to be an ecosystem-facing format, so the contract above is what a consumer
may rely on. Changes that would break a v1 consumer get a new `bundle_version`.

Everything not listed here is an implementation detail of the producer, not part of the
contract.
