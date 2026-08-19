"use client";

import { useMemo } from "react";

import { Disclosure } from "@/components/ui/Disclosure";
import { EmptyState } from "@/components/ui/EmptyState";
import type { V2Evidence, V2RunGraph } from "@/lib/types";

import { CitationChip, ClaimStateChip, ProvenanceChip, runTotals } from "../primitives";

/**
 * Every sentence the report asserts, with the evidence it resolved to.
 *
 * A claim with no supporting evidence is shown as such rather than hidden — that is the
 * whole reason for listing claims separately from the prose. The panel's job is to make
 * "this sentence is backed by that quotation from that page" a thing a reader can walk,
 * so each claim carries the two moves that continue the chain: inspect the evidence, or
 * open the source.
 */
export function ClaimsPanel({
  graph,
  onInspectEvidence,
  onInspectSource,
}: {
  graph: V2RunGraph;
  onInspectEvidence: (claimId: string) => void;
  onInspectSource: (sourceId: string) => void;
}) {
  const { claims, unsupported } = runTotals(graph);
  const evidenceById = useMemo(
    () => new Map(graph.evidence.map((e) => [e.id, e])),
    [graph.evidence],
  );
  const sourceById = useMemo(() => new Map(graph.sources.map((s) => [s.id, s])), [graph.sources]);

  if (claims.length === 0) {
    return (
      <EmptyState
        title="No claims yet"
        description="Claims are derived from a report's prose, so they appear once this run produces a revision."
      />
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-xs leading-relaxed text-text-secondary">
        Every sentence the report asserts, with the evidence it resolved to. A claim with no
        supporting evidence is shown as such rather than hidden — that is the point of
        listing them separately from the prose.
        {unsupported > 0 && (
          <>
            {" "}
            <strong className="text-warning">
              {unsupported} of {claims.length} resolved to no evidence.
            </strong>
          </>
        )}
      </p>

      <ul className="space-y-2">
        {claims.map((claim) => {
          const links = graph.claim_evidence_links.filter((l) => l.claim_id === claim.id);
          const support = links
            .map((l) => evidenceById.get(l.evidence_id))
            .filter((e): e is V2Evidence => Boolean(e));
          return (
            <li key={claim.id} className="card">
              <p className="break-words text-sm leading-relaxed text-text-primary">{claim.text}</p>

              <div className="mt-2 flex flex-wrap items-center gap-2">
                <ClaimStateChip state={claim.verification_state} />
                <span
                  className="font-mono text-[length:var(--text-micro)] text-text-muted"
                  title="How this claim was obtained. DERIVED_FROM_REPORT means it was split out of the report's prose, not emitted as structured output."
                >
                  {claim.extraction_method.toLowerCase().replace(/_/g, " ")}
                </span>
              </div>

              {support.length === 0 ? (
                <p
                  className="mt-2 border p-2 text-xs leading-relaxed"
                  style={{
                    color: "var(--warning)",
                    backgroundColor: "var(--warning-soft)",
                    borderColor: "var(--warning-line)",
                  }}
                >
                  No evidence resolved for this claim. Its citation markers, if any, pointed
                  at nothing the run retrieved.
                </p>
              ) : (
                <div className="mt-2">
                  <Disclosure
                    label={`${support.length} supporting evidence item${
                      support.length === 1 ? "" : "s"
                    }`}
                  >
                    <ul className="space-y-2">
                      {support.map((e) => {
                        const source = sourceById.get(e.source_id);
                        return (
                          <li key={e.id} className="border border-border p-2">
                            <div className="flex flex-wrap items-center gap-2">
                              {source && <CitationChip source={source} />}
                              <ProvenanceChip state={e.provenance_state} />
                              {source && (
                                <button
                                  type="button"
                                  onClick={() => onInspectSource(source.id)}
                                  className="min-w-0 truncate text-xs text-accent hover:underline"
                                  title={source.url}
                                >
                                  {source.title || source.url}
                                </button>
                              )}
                            </div>
                            <blockquote className="mt-1.5 border-l-2 border-border pl-2 text-xs leading-relaxed text-text-secondary">
                              {e.snippet || (
                                <em className="text-text-muted">
                                  The snippet was blanked when it could not be found in the
                                  retrieved text.
                                </em>
                              )}
                            </blockquote>
                          </li>
                        );
                      })}
                    </ul>
                    <button
                      type="button"
                      onClick={() => onInspectEvidence(claim.id)}
                      className="mt-2 text-xs text-accent hover:underline"
                    >
                      Inspect this claim&apos;s evidence in full →
                    </button>
                  </Disclosure>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
