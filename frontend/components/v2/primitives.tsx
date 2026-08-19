"use client";

import type { ReactNode } from "react";

import { v2StatusMeta } from "@/lib/v2Status";
import type { V2Claim, V2Evidence, V2RunGraph, V2Source } from "@/lib/types";

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
 * - **A claim's verification state is four-valued and it is spelled out.** These chips used
 *   to print the wire enum — `INSUFFICIENT_EVIDENCE` in capitals and underscores, which a
 *   reader has to decode, and which reads as a verdict about the claim rather than about
 *   what was run.
 */

/** One chip grammar for every three- and four-valued state on this surface. */
function Chip({
  label,
  tone,
  title,
}: {
  label: string;
  tone: string;
  title: string;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center whitespace-nowrap px-1.5 py-0.5 text-[length:var(--text-micro)] font-medium ${tone}`}
    >
      {label}
    </span>
  );
}

export function ProvenanceChip({ state }: { state: V2Evidence["provenance_state"] }) {
  const copy: Record<string, { label: string; tone: string; title: string }> = {
    ATTESTED: {
      label: "Attested",
      tone: "bg-success-soft text-success",
      title: "The snippet was checked against what the retriever actually returned.",
    },
    UNATTESTED: {
      label: "Unattested",
      tone: "bg-danger-soft text-danger",
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
  return <Chip {...c} />;
}

/**
 * A claim's verification state, in words.
 *
 * `UNCHECKED` is rendered as "Verification not run" rather than as anything shorter,
 * because every shorter phrasing available reads as a verdict about the claim. It is not
 * one: it says no claim-level check was performed, which is a statement about this run,
 * not about whether the sentence is true.
 */
export function ClaimStateChip({ state }: { state: V2Claim["verification_state"] }) {
  const copy: Record<string, { label: string; tone: string; title: string }> = {
    SUPPORTED: {
      label: "Supported",
      tone: "bg-success-soft text-success",
      title: "A verification pass found the cited evidence supports this claim.",
    },
    UNSUPPORTED: {
      label: "Unsupported",
      tone: "bg-danger-soft text-danger",
      title: "A verification pass ran and the cited evidence did not support this claim.",
    },
    INSUFFICIENT_EVIDENCE: {
      label: "Not enough evidence",
      tone: "bg-warning-soft text-warning",
      title:
        "A verification pass ran and could not decide either way from the evidence available.",
    },
    UNCHECKED: {
      label: "Verification not run",
      tone: "bg-bg-elevated text-text-secondary",
      title:
        "No claim-level verification has run. This is not a judgement that the claim is true or false.",
    },
  };
  const c = copy[state] ?? copy.UNCHECKED;
  return <Chip {...c} />;
}

/** The run's status, with the same vocabulary the header and History use. */
export function RunStatusBadge({ status }: { status: string }) {
  const meta = v2StatusMeta(status);
  return (
    <span
      className="badge border-border font-mono text-[length:var(--text-micro)] text-text-secondary"
      title={meta.sentence}
    >
      <span
        aria-hidden
        className="status-marker"
        style={{ backgroundColor: `var(--${meta.token})` }}
      />
      {meta.label}
    </span>
  );
}

export function CitationChip({ source }: { source: V2Source }) {
  if (source.citation_index === null) {
    return (
      <span
        title="This source was retrieved but the report does not cite it. It has no citation number."
        className="inline-flex items-center whitespace-nowrap border border-dashed border-border px-1.5 py-0.5 text-[length:var(--text-micro)] text-text-muted"
      >
        Retrieved, not cited
      </span>
    );
  }
  return (
    <span className="inline-flex h-5 min-w-5 items-center justify-center bg-accent-muted px-1 text-[length:var(--text-micro)] font-semibold text-accent">
      {source.citation_index}
    </span>
  );
}

/**
 * A content hash, truncated for the eye and complete for the clipboard.
 *
 * The full value is what a reader compares against a downloaded bundle, so it has to be
 * obtainable — a `title` tooltip cannot be selected, and 64 hex characters inline destroy
 * every layout they are placed in. `select-all` makes one click take the whole string.
 */
export function Hash({ value, label }: { value: string; label?: string }) {
  return (
    <code
      title={value}
      aria-label={label ? `${label}: ${value}` : value}
      className="select-all break-all bg-bg-elevated px-1 py-0.5 font-mono text-[length:var(--text-micro)] text-text-muted"
    >
      {value.slice(0, 12)}…
    </code>
  );
}

/** A labelled figure. `warn` is for a number a reviewer must not skim past. */
export function Stat({
  label,
  value,
  warn,
  hint,
}: {
  label: ReactNode;
  value: ReactNode;
  warn?: boolean;
  hint?: ReactNode;
}) {
  return (
    <div>
      <dt className="text-xs text-text-secondary">{label}</dt>
      <dd
        className={`text-sm font-medium ${warn ? "text-warning" : "text-text-primary"}`}
      >
        {value}
      </dd>
      {hint && <p className="mt-0.5 text-[length:var(--text-micro)] text-text-muted">{hint}</p>}
    </div>
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
    /** Records the detector could not anchor. Not the same as "no conflicts found". */
    unanchoredContradictions: graph.contradictions.length - detected.length,
    /** Evidence nothing has attested. Unchecked is not verified. */
    uncheckedEvidence: graph.evidence.filter((e) => e.provenance_state === "UNCHECKED").length,
    /** Claims with at least one evidence link. The rest carry no traceable support. */
    supported: claims.filter((c) => linkedClaimIds.has(c.id)).length,
    unsupported: claims.filter((c) => !linkedClaimIds.has(c.id)).length,
    approval: graph.reviews.find((r) => r.gate === "REPORT" && r.decision === "APPROVED") ?? null,
    planDecided: graph.reviews.some((r) => r.gate === "PLAN"),
  };
}
