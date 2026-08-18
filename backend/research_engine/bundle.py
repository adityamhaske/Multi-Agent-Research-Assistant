"""
Research bundle: the auditable export format (docs/12 M12).

"SBOM for research" — a self-contained JSON artifact that carries the report, every
claim, every evidence snippet with a content hash, the source list, contradictions,
model routing, costs, the full approval chain, and the agent trace. A standalone
verifier (verify_bundle.py) can check the whole thing offline with no AI and no network.

This module is the pure assembler: no DB, no ORM, no host. Both the API server and
the desktop sidecar produce bundles through it. Claim extraction comes from
`research_engine.claims` — the same definition the graph's citation-fidelity pass and the
eval judge use. It used to come from `evals.metrics`, which meant a desktop build could
not ship the engine without also shipping the eval harness.

Design decisions (docs/reference/15-bundle-format.md):

- **Content hashes are SHA-256 of the snippet text, not the source page.** The live
  page is non-reproducible (it changes); the snippet is exactly what the executor
  extracted and the citation-support judge ruled on. The hash proves it wasn't tampered
  with after research time.

- **Snippet is the complete stored evidence text**, not a display truncation. The
  executor caps it at 500 chars (EvidenceChunk.snippet max_length=500); that IS the
  full evidence.

- **bundle_hash covers ALL fields** (including trace and trace_available) except itself.
  Stripping the trace from a bundle that had one breaks the hash — correct. An absent
  trace (trace_available=false) is the truthful state and the hash covers that truth.

- **trace_available distinguishes three states** that would otherwise all be `trace: []`:
  host had logs and they're present, host had logs but nothing fired (edge), host does
  not support durable logging. Both shipped hosts are in the first state: the desktop
  sidecar's `PersistingSink` writes an `agent_logs` row per event exactly as the server
  worker's sink does, so it reports `trace_available=True` and a populated trace. This
  line named the sidecar as the no-durable-logging example until M0C, when adding its
  bundle route made the claim testable and it turned out to be false.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from research_engine.claims import CITE_RE, claim_lines

# ── Schema ────────────────────────────────────────────────────────────────────────


class SnippetRecord(BaseModel):
    """One evidence chunk with its integrity hash."""

    source_url: str
    source_title: str = ""
    snippet: str = Field(
        description=(
            "The COMPLETE stored evidence text (executor-extracted, 500-char cap). "
            "Not a display truncation — this is exactly what the citation judge ruled on."
        )
    )
    content_hash: str = Field(description="SHA-256 of snippet.encode('utf-8')")
    key_fact: str = ""


class ClaimRecord(BaseModel):
    """One assertable claim extracted from the report body."""

    sentence: str
    citation_indices: list[int] = Field(
        default_factory=list,
        description="The [n] markers this sentence carries",
    )


class ApprovalRecord(BaseModel):
    """One HITL decision in the approval chain."""

    action: str = Field(description='"approved" or "rework_requested"')
    feedback: str | None = None
    draft_hash: str = Field(description="SHA-256 of the draft at decision time")
    timestamp: str = Field(description="ISO-8601 datetime")


class BundleManifest(BaseModel):
    """The .bundle.json schema — version 1."""

    bundle_version: int = 1
    session_id: str
    query: str
    research_depth: str = "balanced"

    # True when this report came from scripted models and fixture retrievers rather than a
    # real provider (docs/17 §6.2). Placed here, beside the identity of the run, rather
    # than among the metrics: a reader deciding whether to trust this file must not have to
    # scroll past cost and token counts to discover none of it was real. Covered by
    # `bundle_hash`, so a demo bundle cannot be edited into a real-looking one without
    # breaking verification.
    demo: bool = False

    report: str
    report_hash: str

    claims: list[ClaimRecord] = Field(default_factory=list)
    evidence: list[SnippetRecord] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)
    contradictions: list[dict] = Field(default_factory=list)

    models: dict[str, str] = Field(default_factory=dict)
    cost_usd: float = 0.0
    tokens_input: int = 0
    tokens_output: int = 0
    elapsed_seconds: float | None = None

    approval_chain: list[ApprovalRecord] = Field(default_factory=list)
    trace: list[dict] = Field(default_factory=list)
    trace_available: bool = True

    created_at: str = ""
    bundle_hash: str = ""


# ── Hashing ───────────────────────────────────────────────────────────────────────


def content_hash(text: str) -> str:
    """SHA-256 hex digest of UTF-8 encoded text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_bundle_hash(bundle: BundleManifest) -> str:
    """SHA-256 of all fields except ``bundle_hash`` itself.

    Produces a canonical JSON with sorted keys and ``bundle_hash`` blanked to the
    empty string, so the hash is reproducible from the bundle's own contents.
    """
    d = bundle.model_dump()
    d["bundle_hash"] = ""
    canonical = json.dumps(d, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── Claim extraction ──────────────────────────────────────────────────────────────


def _extract_citation_indices(sentence: str) -> list[int]:
    """Which [n] markers a sentence carries."""
    out: list[int] = []
    for m in CITE_RE.finditer(sentence):
        out.extend(int(part.strip()) for part in m.group(1).split(","))
    return sorted(set(out))


# ── Assembly ──────────────────────────────────────────────────────────────────────


def assemble(
    *,
    session_id: str,
    query: str,
    report: str,
    evidence: list[dict],
    sources: list[dict],
    contradictions: list[dict] | None = None,
    models: dict[str, str] | None = None,
    cost_usd: float = 0.0,
    tokens_input: int = 0,
    tokens_output: int = 0,
    elapsed_seconds: float | None = None,
    research_depth: str = "balanced",
    approval_chain: list[dict] | None = None,
    trace: list[dict] | None = None,
    trace_available: bool = True,
    demo: bool = False,
) -> BundleManifest:
    """Build a complete bundle from session data. Pure — no DB, no ORM."""

    report_h = content_hash(report)

    snippet_records = [
        SnippetRecord(
            source_url=e.get("source_url", ""),
            source_title=e.get("source_title", ""),
            snippet=e.get("snippet", ""),
            content_hash=content_hash(e.get("snippet", "")),
            key_fact=e.get("key_fact", ""),
        )
        for e in evidence
    ]

    claims = [
        ClaimRecord(sentence=s, citation_indices=_extract_citation_indices(s))
        for s in claim_lines(report)
    ]

    approvals = [
        ApprovalRecord(
            action=a.get("action", ""),
            feedback=a.get("feedback"),
            draft_hash=a.get("draft_hash", ""),
            timestamp=a.get("timestamp") or a.get("created_at") or "",
        )
        for a in (approval_chain or [])
    ]

    bundle = BundleManifest(
        session_id=session_id,
        query=query,
        research_depth=research_depth,
        demo=demo,
        report=report,
        report_hash=report_h,
        claims=claims,
        evidence=snippet_records,
        sources=sources,
        contradictions=contradictions or [],
        models=models or {},
        cost_usd=cost_usd,
        tokens_input=tokens_input,
        tokens_output=tokens_output,
        elapsed_seconds=elapsed_seconds,
        approval_chain=approvals,
        trace=trace or [],
        trace_available=trace_available,
        created_at=datetime.now(UTC).isoformat(),
        bundle_hash="",
    )
    bundle.bundle_hash = compute_bundle_hash(bundle)
    return bundle


def serialize(bundle: BundleManifest) -> str:
    """Canonical JSON for storage/export — readable, deterministic key order."""
    return json.dumps(bundle.model_dump(), sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def render_model_attribution_md(model_routing: dict[str, str] | None) -> str:
    """A "Models used" Markdown footer — the `.md`/`.pdf` export counterpart of this
    module's `models` field (requirement 1: disclosure "in the report/export").

    Lives here, not in `app.services.export`, because both the API server AND the
    desktop sidecar's `.md` export need it, and `app.services.export` lazily imports
    WeasyPrint — `test_sidecar_import_tree_excludes_weasyprint` pins that the sidecar
    process never touches that module at all (docs/13 §7). This module is already the
    documented host-agnostic export home ("no DB, no ORM, no host. Both the API server
    and the desktop sidecar produce bundles through it" — see the module docstring).

    Appended by the caller, never merged into the report body itself: the body is the
    exact text a human approved, and `report_hash` is checked against that same
    `draft_hash` above — mutating it here would break bundle verification for a reason
    that has nothing to do with the bundle's integrity (the same trap `_DEMO_STAMP`,
    `app/api/v1/research.py`, documents for the demo banner).

    Empty when routing was never resolved — a run that failed before the planner, or a
    report exported from before this field existed — never a guessed default (the
    unmeasured-vs-zero rule).
    """
    if not model_routing:
        return ""
    lines = "\n".join(f"- **{role}** — `{route}`" for role, route in sorted(model_routing.items()))
    return f"\n\n---\n\n## Models used\n\n{lines}\n"
