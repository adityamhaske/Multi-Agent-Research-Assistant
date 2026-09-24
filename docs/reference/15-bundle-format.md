# Research bundle format

A research bundle (`.bundle.json`) is a self-contained, auditable export of one research
run — a bill of materials for a report. It carries not just the output but the evidence,
the sources, the costs, the agent trace, and the human approvals that produced it.

The format is pure JSON, designed to be parsed and verified **entirely offline**, with no
model, no network, and no database.

Two versions exist. Version 2 adds a record of the system prompts the run actually used, and
of whether its owner's prompt overrides applied; everything else is version 1 unchanged.

## Schema

The root object is a `BundleManifest`. This is a version 2 bundle; a version 1 bundle is the
same object without `prompt_provenance` and `prompt_overrides_status`.

```json
{
  "bundle_version": 2,
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

  "prompt_provenance": [
    {
      "purpose": "planner.main",
      "role": "planner",
      "policy": "OVERRIDABLE",
      "overridden": false,
      "effective_prompt": "You are the Orchestration Planner of a research assistant.…",
      "effective_prompt_sha256": "4ae5f09938963fe8f2ad7c50280f819a2c651c33809f7ef25bbeaff7c6afb85b"
    }
  ],
  "prompt_overrides_status": "NONE",

  "created_at": "2026-08-13T12:05:00+00:00",
  "bundle_hash": "7a945b14f85e3a8936ef3eb1389c8a9167db9b48c26f63be246becc360f2ea99"
}
```

### Fields by version

| Version | Fields it defines |
|---|---|
| 1 | `bundle_version`, `session_id`, `query`, `research_depth`, `demo`, `report`, `report_hash`, `claims`, `evidence`, `sources`, `contradictions`, `models`, `cost_usd`, `tokens_input`, `tokens_output`, `elapsed_seconds`, `approval_chain`, `trace`, `trace_available`, `created_at`, `bundle_hash` |
| 2 | Every version 1 field, plus `prompt_provenance` and `prompt_overrides_status` |

### Which bundles are which version

The version is decided by whether the run's prompts were recorded while it executed — not by
whether anything was customised.

| Bundle | Version |
|---|---|
| A research run whose prompts were recorded as it executed — customised or not | **2** |
| A research run that executed before prompts were recorded | **1** — they were never recorded, and are not reconstructed |
| A research session (the earlier pipeline, still exportable) | **1** — sessions do not apply prompt overrides and record no prompts |
| The frozen artifact of an approved run | The version it was frozen with |

A version 2 bundle with `prompt_overrides_status: "NONE"` is ordinary: nothing was
customised, and the prompts the run used are recorded anyway.

A version 1 bundle from a current producer may still carry the version 2 fields, empty —
`"prompt_provenance": []` and `"prompt_overrides_status": null`. They are outside its hash
(§2). A version 1 bundle carrying a non-empty `prompt_provenance` or
`prompt_overrides_status` fails verification.

## Design constraints

### 1. Hashing

Every hash is a SHA-256 hex digest of UTF-8 encoded text.

### 2. `bundle_hash` scope

`bundle_hash` covers every field **the bundle's declared version defines** — including
`trace` and `trace_available` — except itself. To recompute it:

1. Keep only the fields the declared `bundle_version` defines ([Fields by
   version](#fields-by-version)), and drop every other key. For a version 1 bundle that drops
   `prompt_provenance` and `prompt_overrides_status` if they are present.
2. Set `bundle_hash` to `""`.
3. Serialise the object as JSON with **sorted keys**, `ensure_ascii=False`, and separators
   `(",", ":")` — no whitespace.
4. SHA-256 the resulting UTF-8 string.

Stripping the trace from a bundle that had one therefore breaks the hash, which is correct. An
absent trace (`trace_available: false`) is the truthful state, and the hash covers that truth.

Step 1 is what keeps version 1 bundles already issued valid: version 2's fields are outside
a version 1 hash, so adding them changed no existing bundle's digest — and skipping the step
fails every version 1 bundle that carries them empty. A key no version defines is covered by
no hash, and the verifier ignores it.

**The hash is unkeyed.** It detects a bundle modified by someone who did not recompute it. It
does not authenticate where a bundle came from: anyone able to modify a bundle can recompute
every hash in it. A bundle that verifies is internally consistent; it is not proof of who
produced it.

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

### 7. Prompt provenance (version 2)

The owner of a run may replace the system prompt of some agent roles. `prompt_provenance`
records, one entry per prompt purpose, the system prompt the run actually sent to the model:

| Field | Meaning |
|---|---|
| `purpose` | `<role>.<purpose>`, e.g. `planner.main` |
| `role` | The agent role the purpose runs under |
| `policy` | `OVERRIDABLE` if an owner may replace this prompt, `PROTECTED` if nobody may |
| `overridden` | `true` when the run used the owner's replacement. It records the decision, not a text comparison: a replacement identical to the shipped prompt is still `true`, and a `PROTECTED` entry is always `false` |
| `effective_prompt` | The exact string the model received |
| `effective_prompt_sha256` | SHA-256 of `effective_prompt` |

A replacement is not always the owner's text verbatim. Where the shipped prompt carries the
instruction to treat retrieved content as untrusted data, the system adds that instruction
before and after the owner's text, and `effective_prompt` — and so its hash — includes it.

A research run executes seven purposes, and only those appear in the bundles it produces:
`planner.main`, `executor.main`, `critic.research`, `critic.citation_verify`,
`critic.contradiction_detector`, `synthesizer.main`, and `synthesizer.repair`. Chat is not
part of a run, so no chat prompt appears.

**An absent purpose means "not recorded", not necessarily "did not run".** A purpose is
recorded when the run composes its prompt, so one the run never reached is absent —
`synthesizer.repair` runs only when a draft contains uncited sentences. And a run that was
paused at a human gate while its deployment was upgraded from a version that did not record
prompts has only the ones composed after the upgrade: resumed past the design gate, it
exports a version 2 bundle with no `planner.main` entry, although its planner ran.

The entries are plain strings, deliberately not checked against the verifier's own prompts:
a bundle from a version whose shipped prompts differ verifies the same way.

The prompt text is included in full so the bundle describes itself. A custom prompt therefore
travels with every copy of the bundle — it is not a secret, and should not contain one.

### 8. `prompt_overrides_status` (version 2)

| Value | Meaning |
|---|---|
| `NONE` | No override was configured when the run started, so it ran its shipped prompts |
| `APPLIED` | The owner's overrides were in force for the whole run. `overridden` shows which purposes they reached — possibly none, since an override set only for chat reaches no research purpose |
| `UNUSABLE` | Overrides were configured, but the run's stored copy of them could not be used, so the run fell back to its shipped prompts rather than applying part of them. `overridden` records what actually ran |

It is copied from the run's own record rather than inferred from `prompt_provenance`: `NONE`
and `UNUSABLE` both produce shipped prompts, and only the run knows which happened. The
status says what the run was configured with; the `overridden` flags say what actually ran. A
run that recorded its prompts but has no recorded status reads as `NONE`.

## Standalone verifier

Ships with the engine. No model, no network, no database.

```bash
python -m research_engine.verify_bundle path/to/research.bundle.json
```

Exit code `0` if every check passes, `1` otherwise. `--format json` emits a machine-readable
result.

It reads versions 1 and 2, and runs the same checks on both. A version 1 bundle is hashed as
it always was — without the version 2 fields — so one that verified before version 2 existed
still verifies. **A verifier released before version 2 refuses every version 2 bundle** —
`Unsupported bundle_version 2 (this verifier supports version 1)` — and nothing can change
that after the fact; verifying a version 2 bundle needs a current verifier.

Seven checks:

1. **Schema validity** — the JSON parses and matches the manifest for a supported version, 1
   or 2. Any other version is refused by name.
2. **Bundle integrity** — the recomputed `bundle_hash` matches (§2). It also fails a version
   1 bundle carrying version 2 prompt provenance or status, which its hash would not cover,
   and any provenance entry whose `effective_prompt_sha256` does not match its
   `effective_prompt` — so a prompt edited without also editing its recorded hash is caught
   even if `bundle_hash` was recomputed.
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

Prompt provenance is reported alongside the verdict for the same reason. When any entry is
`overridden`, the text report prints a `CUSTOMISED AGENTS` warning above the verdict — below
the demo warning, if there is one: the checks confirm what the prompts were and that they are
unchanged since assembly, not that they were sound. Below the checks it gives the number of
purposes recorded and names each replaced one with the start of its hash; `UNUSABLE` adds a
note that the run's stored overrides could not be used. `--format json` carries
`prompt_overrides_status` and every provenance field except the prompt text, which is in the
bundle.

## Stability

This is intended to be an ecosystem-facing format, so the contract above is what a consumer
may rely on. Changes that would break a consumer of an existing version get a new
`bundle_version`. Version 2 only adds fields, and each version's hash covers only the fields
it defines, so no issued bundle's hash changes when a later version adds more.

A new version cannot reach verifiers already in use: a verifier admits exactly the versions it
shipped with.

Everything not listed here is an implementation detail of the producer, not part of the
contract.
