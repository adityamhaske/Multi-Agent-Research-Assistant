"""
Research bundle: the auditable export format (docs/12 M12).

"SBOM for research" — a self-contained JSON artifact that carries the report, every
claim, every evidence snippet with a content hash, the source list, contradictions,
model routing, costs, the full approval chain, and the agent trace. A standalone
verifier (verify_bundle.py) can check the whole thing offline with no AI and no network.

This module is the pure assembler: no DB, no ORM, no host. Both the API server and
the desktop sidecar produce bundles through it.

Design decisions (docs/engineering/15_Bundle_Format.md):

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
  not support durable logging (desktop sidecar today).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from evals.metrics import CITE_RE, claim_lines

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
