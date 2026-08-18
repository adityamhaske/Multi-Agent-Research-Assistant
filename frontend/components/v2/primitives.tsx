"use client";

import type { V2Evidence, V2RunGraph, V2Source } from "@/lib/types";

/**
 * Small shared pieces for the V2 workspace.
 *
 * The rules they encode are the product's, not decoration:
 *
 * - **Retrieved is not verified.** Evidence provenance renders as its own three-valued
 *   chip. `UNCHECKED` says "nobody checked", which is different from "checked and failed",
 *   and neither is a tick.
 * - **Retrieved is not cited.** A source with no citation index renders without a number
 *   and says so, rather than being given the next free one.
 * - **A citation is not evidence.** The claim view links a marker to the evidence row it
 *   resolved to, and shows nothing when it resolved to nothing.
 */

export function ProvenanceChip({ state }: { state: V2Evidence["provenance_state"] }) {
  const copy: Record<string, { label: string; tone: string; title: string }> = {
    ATTESTED: {
      label: "Attested",
      tone: "bg-status-success-bg text-status-success",
      title: "The snippet was checked against what the retriever actually returned.",
    },
    UNATTESTED: {
      label: "Unattested",
      tone: "bg-status-danger-bg text-status-danger",
      title: "A check ran and this snippet could not be found in the retrieved text.",
    },
    UNCHECKED: {
      label: "Unchecked",
      tone: "bg-bg-elevated text-text-secondary",
      title:
        "No per-item verification was recorded for this snippet. Unchecked is not the same as verified, and not the same as failed.",
    },
  };
  const c = copy[state] ?? copy.UNCHECKED;
  return (
    <span
      title={c.title}
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-[0.6875rem] font-medium ${c.tone}`}
    >
      {c.label}
    </span>
  );
}

export function CitationChip({ source }: { source: V2Source }) {
  if (source.citation_index === null) {
    return (
      <span
        title="This source was retrieved but the report does not cite it. It has no citation number."
        className="inline-flex items-center rounded border border-dashed border-border-subtle px-1.5 py-0.5 text-[0.6875rem] text-text-muted"
      >
        Retrieved, not cited
      </span>
    );
  }
  return (
    <span className="inline-flex h-5 min-w-5 items-center justify-center rounded bg-accent-subtle px-1 text-[0.6875rem] font-semibold text-accent">
      {source.citation_index}
    </span>
  );
}

export function Hash({ value }: { value: string }) {
  return (
    <code
      title={value}
      className="rounded bg-bg-elevated px-1 py-0.5 font-mono text-[0.6875rem] text-text-muted"
    >
      {value.slice(0, 12)}…
    </code>
  );
}

/** The counts that make the workflow legible at a glance. Derived, never stored. */
export function runTotals(graph: V2RunGraph) {
  const detected = graph.contradictions.filter((c) => c.detection_state === "DETECTED");
  const cited = graph.sources.filter((s) => s.citation_index !== null);
  const latest = graph.revisions[graph.revisions.length - 1] ?? null;
  const claims = latest ? graph.claims.filter((c) => c.revision_id === latest.id) : [];
  const linkedClaimIds = new Set(graph.claim_evidence_links.map((l) => l.claim_id));
  return {
    latest,
    claims,
    evidence: graph.evidence.length,
    sources: graph.sources.length,
    citedSources: cited.length,
    uncitedSources: graph.sources.length - cited.length,
    contradictions: detected.length,
    /** Claims with at least one evidence link. The rest carry no traceable support. */
    supported: claims.filter((c) => linkedClaimIds.has(c.id)).length,
    unsupported: claims.filter((c) => !linkedClaimIds.has(c.id)).length,
    approval: graph.reviews.find((r) => r.gate === "REPORT" && r.decision === "APPROVED") ?? null,
  };
}
