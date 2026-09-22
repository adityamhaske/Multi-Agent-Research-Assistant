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
from typing import Literal

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

    action: str = Field(
        description=(
            '"approved" or "rework_requested" at the report gate, "plan_approved" at the '
            "plan gate. Only a report approval authorizes anything: the verifier counts "
            "`approved` alone, and an artifact requires an APPROVED REPORT review."
        )
    )
    feedback: str | None = None
    draft_hash: str = Field(description="SHA-256 of the draft at decision time")
    timestamp: str = Field(description="ISO-8601 datetime")


class PromptProvenance(BaseModel):
    """Which system prompt one purpose actually ran under (bundle v2, scope freeze §9).

    **Deliberately plain strings, and deliberately not validated against this build's
    registry.** The verifier reads bundles it did not produce, including ones from later
    versions whose shipped prompts differ from these. Checking `purpose` or `policy` against
    the running code would make a bundle's validity depend on the verifier's build, which is
    the opposite of what an offline, third-party artifact format is for — a v1 bundle
    verifies forever, and a v2 bundle must too.

    `effective_prompt` is the exact string the model received, so a reader can see what the
    run was actually instructed to do rather than infer it from a role name.
    """

    purpose: str = Field(description="`<role>.<purpose>`, e.g. `planner.main`")
    role: str
    policy: Literal["OVERRIDABLE", "PROTECTED"]
    overridden: bool = Field(description="False when the shipped prompt ran unchanged")
    effective_prompt: str
    effective_prompt_sha256: str = Field(description="SHA-256 of `effective_prompt`")


class BundleManifest(BaseModel):
    """The .bundle.json schema — versions 1 and 2."""

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

    # ── v2 (scope freeze §9) ──────────────────────────────────────────────────────
    # Both default, so a v1 bundle and a `research_artifacts.payload` frozen before v2
    # existed still parse unchanged — the compatibility §10 calls non-negotiable.
    #
    # Covered by `bundle_hash` **on a v2 bundle** — `compute_bundle_hash` hashes the fields
    # the declared version defines, so these enter it there and are excluded from a v1's.
    # §9 requires that be *proved* rather than assumed, which is what the tampering tests do.
    prompt_provenance: list[PromptProvenance] = Field(default_factory=list)

    # Copied from `research_runs.prompt_overrides_status`, never recomputed from the
    # provenance above: "no override was configured" and "one was configured and could not
    # be used" both produce shipped prompts, and only the row knows which happened.
    prompt_overrides_status: str | None = None

    created_at: str = ""
    bundle_hash: str = ""


# ── Hashing ───────────────────────────────────────────────────────────────────────


def content_hash(text: str) -> str:
    """SHA-256 hex digest of UTF-8 encoded text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


#: Fields that bundle v2 introduced. A v1 bundle is hashed without them.
#:
#: **This is what keeps already-issued bundles valid.** The hash is taken over the model's
#: dump, so adding a field silently changes the hash of *every* bundle — including ones
#: frozen in `research_artifacts.payload` years ago and ones a third party downloaded and
#: still has. Their recorded `bundle_hash` would no longer match what this code computes,
#: and `bundle_integrity` would fail on artifacts nobody touched. The scope freeze calls
#: that outcome out by name: existing v1 bundles remain valid forever.
#:
#: So the hash is defined **per format version**: v1 hashes the fields v1 defined, v2 adds
#: these two. Growing v3 means adding to this map, not editing the function.
_FIELDS_ADDED_BY_VERSION: dict[int, tuple[str, ...]] = {
    2: ("prompt_provenance", "prompt_overrides_status"),
}


def compute_bundle_hash(bundle: BundleManifest) -> str:
    """SHA-256 of every field this bundle's version defines, except ``bundle_hash`` itself.

    Canonical JSON, sorted keys, ``bundle_hash`` blanked, so the hash is reproducible from
    the bundle's own contents. Fields belonging to a *later* version than this bundle
    declares are excluded — see `_FIELDS_ADDED_BY_VERSION`.
    """
    d = bundle.model_dump()
    d["bundle_hash"] = ""
    for version, fields in _FIELDS_ADDED_BY_VERSION.items():
        if bundle.bundle_version < version:
            for name in fields:
                d.pop(name, None)
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


#: Prepended to the report text of any demo export (docs/17 §6.2). Markdown, so it
#: survives into the PDF renderer as well as the `.md` file.
#:
#: **Lives here for the same reason `render_model_attribution_md` does:** both the API
#: server and the desktop sidecar export `.md`, and both must stamp it. It used to be a
#: private constant in `app/api/v1/research.py`, which the sidecar could not reach — so the
#: desktop `.md` export shipped unstamped while `docs/user-guide/29-exports.md` promised
#: that "every export path stamps the artifact" (#52). That is precisely the artifact the
#: flag exists to prevent: a scripted, fixture-sourced report that leaves the app looking
#: like research.
#:
#: The bundle deliberately does NOT carry this. `report_hash` is checked against the
#: `draft_hash` recorded at approval, so injecting prose into the report body afterwards
#: breaks the approval chain. The bundle carries `demo` as a hash-covered field instead.
DEMO_STAMP_MD = (
    "> ## ⚠ DEMO — NOT REAL RESEARCH\n"
    ">\n"
    "> This report was produced with **scripted models and fixture sources** so the\n"
    "> product could be demonstrated without an API key. The citations below resolve to\n"
    "> real-looking references, but **nothing here was researched and nothing here is\n"
    "> verified**. Do not cite, share, or act on it.\n"
    "\n"
    "---\n\n"
)


def stamp_demo_md(report: str, *, demo: bool) -> str:
    """Prepend the demo banner when `demo` is set. The one place either host decides.

    A function rather than a bare constant so the rule ("stamped iff demo") has a single
    implementation too, not just a single string — `tests/test_demo_stamp_parity.py`
    pins that both hosts route through it.
    """
    return f"{DEMO_STAMP_MD}{report}" if demo else report


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
