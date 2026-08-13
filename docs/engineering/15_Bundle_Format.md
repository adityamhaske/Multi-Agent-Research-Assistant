# M12: Research Bundle Format (v1)

A research bundle (`.bundle.json`) is a self-contained, auditable export format for a Multi-Agent Research Assistant session. It serves as a "Software Bill of Materials" (SBOM) for a research report, containing not just the final output but all evidence, sources, cost metrics, agent trace, and human approvals that led to it.

The format is pure data (JSON), designed to be parsed and verified entirely offline without the agent application or any network access.

## Format Specification

The root object is a `BundleManifest` matching the version `1` schema.

```json
{
  "bundle_version": 1,
  "session_id": "uuid",
  "query": "The original user prompt",
  "research_depth": "balanced",
  "report": "# Final Markdown...",
  "report_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  
  "claims": [
    {
      "sentence": "The extracted claim sentence.",
      "citation_indices": [1, 3]
    }
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
    {"index": 1, "url": "https://example.com/source", "title": "Page Title", "snippet": ""}
  ],
  
  "contradictions": [],
  
  "models": {
    "planner": "provider:model",
    "executor": "provider:model"
  },
  
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
  
  "trace": [
    {"type": "agent_log", "agent": "planner", "message": "Planning..."}
  ],
  "trace_available": true,
  
  "created_at": "2026-08-13T12:05:00+00:00",
  "bundle_hash": "7a945b14f85e3a8936ef3eb1389c8a9167db9b48c26f63be246becc360f2ea99"
}
```

### Key Design Constraints

**1. Hashing Algorithm:**
All hashes in the bundle are SHA-256 digests of UTF-8 encoded text.

**2. `bundle_hash` Scope:**
The `bundle_hash` covers ALL fields in the manifest, including `trace` and `trace_available`, except `bundle_hash` itself. To recompute it, blank `bundle_hash` to `""`, serialize the JSON (sorted keys, no spaces, `ensure_ascii=False`), and hash the resulting string.

**3. Snippet Completeness:**
`SnippetRecord.snippet` represents the *complete* stored evidence text. It is exactly what the executor extracted (capped at 500 characters by `EvidenceChunk.snippet`). It is NOT a display-truncated view of a longer text. The `content_hash` proves this exact text wasn't tampered with, ensuring it perfectly represents the text the citation-support judge ruled on.

**4. Trace Availability:**
The `trace_available` boolean distinguishes three states for an empty `trace: []`:
- `true` with `trace: [...]`: Full event log is present.
- `true` with `trace: []`: Event log was available but genuinely empty (an edge case).
- `false` with `trace: []`: The host application does not support durable event logs (e.g., the desktop sidecar). This is a documented capability gap, not missing data or a failure.

**5. Approval Chain Contract:**
For a bundle to be considered approved, the `approval_chain` must contain at least one entry where `action == "approved"`, AND its `draft_hash` must identically match the `report_hash`. This proves the approval was given for *this specific report*, not an earlier draft or a different session altogether.

## Standalone Verifier

The bundle includes a standalone verifier (`research_engine/verify_bundle.py`) that executes seven integrity checks. It requires no AI, no network access, and no database connection.

```bash
# Returns exit code 0 if valid, 1 if tampered
python -m research_engine.verify_bundle path/to/bundle.json
```

1. **Schema validity**: JSON parses and matches the `BundleManifest` schema (version 1).
2. **Bundle integrity**: Recomputed `bundle_hash` matches.
3. **Report integrity**: Recomputed `report_hash` matches.
4. **Evidence integrity**: Each snippet's `content_hash` matches.
5. **Citation resolution**: Every `[n]` marker in the report body resolves to a valid `sources` entry.
6. **Claim-evidence linkage**: Every cited source in a claim points to a source that contains at least one evidence snippet.
7. **Approval chain integrity**: Verifies that a valid, linked `approved` entry exists.
