"use client";

import { useMemo, useState } from "react";

import { EmptyState } from "@/components/ui/EmptyState";
import type { V2Claim, V2RunGraph } from "@/lib/types";

import { CitationChip, Hash, ProvenanceChip } from "../primitives";

/** Long enough that the ledger stops being scannable. Measured against real snippets. */
const SNIPPET_CLAMP = 420;

/**
 * The evidence ledger: what the executor extracted, in the order it arrived.
 *
 * Two things this panel has to keep true. **Retrieved is not verified** — the provenance
 * chip says whether anything checked this snippet against what the retriever actually
 * returned, and `UNCHECKED` is not a tick. And a filtered ledger must *say* it is filtered:
 * arriving here from a claim used to silently show a subset, so a reader who had lost track
 * of how they got here would conclude the run had gathered three items when it had gathered
 * ninety.
 */
export function EvidencePanel({
  graph,
  focusClaim,
  onClearFocus,
  onInspectSource,
}: {
  graph: V2RunGraph;
  focusClaim: string | null;
  onClearFocus: () => void;
  onInspectSource: (sourceId: string) => void;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const sourceById = useMemo(() => new Map(graph.sources.map((s) => [s.id, s])), [graph.sources]);
  const claimsByEvidence = useMemo(() => {
    const claimById = new Map(graph.claims.map((c) => [c.id, c]));
    const map = new Map<string, V2Claim[]>();
    for (const link of graph.claim_evidence_links) {
      const claim = claimById.get(link.claim_id);
      if (!claim) continue;
      map.set(link.evidence_id, [...(map.get(link.evidence_id) ?? []), claim]);
    }
    return map;
  }, [graph.claims, graph.claim_evidence_links]);

  const focusedClaim = focusClaim ? graph.claims.find((c) => c.id === focusClaim) : null;
  const rows = useMemo(
    () =>
      focusClaim
        ? graph.evidence.filter((e) =>
            graph.claim_evidence_links.some(
              (l) => l.claim_id === focusClaim && l.evidence_id === e.id,
            ),
          )
        : graph.evidence,
    [focusClaim, graph.evidence, graph.claim_evidence_links],
  );

  if (graph.evidence.length === 0) {
    return (
      <EmptyState
        title="No evidence recorded"
        description="Nothing was retrieved for this run, or it has not reached the executor yet. Evidence appears here as the executor extracts it."
      />
    );
  }

  return (
    <div className="space-y-3">
      {focusedClaim ? (
        <div
          className="flex flex-wrap items-start justify-between gap-3 border p-2.5"
          style={{ backgroundColor: "var(--info-soft)", borderColor: "var(--info-line)" }}
        >
          <p className="min-w-0 text-xs leading-relaxed text-text-primary">
            <span className="font-mono text-[length:var(--text-micro)] uppercase tracking-wider text-text-secondary">
              Filtered ·{" "}
            </span>
            showing the {rows.length} evidence item{rows.length === 1 ? "" : "s"} behind one
            claim, out of {graph.evidence.length} in this run.
            <span className="mt-1 block break-words text-text-secondary">
              &ldquo;{focusedClaim.text}&rdquo;
            </span>
          </p>
          <button
            type="button"
            onClick={onClearFocus}
            className="btn btn-secondary shrink-0 px-2 py-1 text-xs"
          >
            Show all evidence
          </button>
        </div>
      ) : (
        <p className="text-xs leading-relaxed text-text-secondary">
          What the executor extracted, in the order it arrived.{" "}
          <strong className="text-text-primary">Retrieved is not verified</strong> — the
          provenance chip says whether anything checked this snippet against what the
          retriever actually returned.
        </p>
      )}

      {rows.length === 0 ? (
        <EmptyState
          title="No evidence for that claim"
          description="This claim resolved to nothing the run retrieved."
        />
      ) : (
        <ul className="space-y-2">
          {rows.map((e) => {
            const source = sourceById.get(e.source_id);
            const claims = claimsByEvidence.get(e.id) ?? [];
            const long = e.snippet.length > SNIPPET_CLAMP;
            const open = expanded.has(e.id);
            return (
              <li key={e.id} className="card">
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className="font-mono text-[length:var(--text-micro)] text-text-muted"
                    title="Sequence within this run. Evidence is never renumbered."
                  >
                    #{e.sequence}
                  </span>
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

                <blockquote className="mt-2 border-l-2 border-border pl-2 text-sm leading-relaxed break-words text-text-primary">
                  {e.snippet ? (
                    long && !open ? (
                      `${e.snippet.slice(0, SNIPPET_CLAMP)}…`
                    ) : (
                      e.snippet
                    )
                  ) : (
                    <em className="text-text-muted">
                      Blanked: this snippet could not be found in what the retriever returned.
                    </em>
                  )}
                </blockquote>
                {long && (
                  <button
                    type="button"
                    onClick={() =>
                      setExpanded((prev) => {
                        const next = new Set(prev);
                        if (next.has(e.id)) next.delete(e.id);
                        else next.add(e.id);
                        return next;
                      })
                    }
                    aria-expanded={open}
                    className="mt-1 text-xs text-accent hover:underline"
                  >
                    {open ? "Show less" : `Show the full ${e.snippet.length}-character quotation`}
                  </button>
                )}

                {e.key_fact && (
                  <p className="mt-1.5 text-xs leading-relaxed text-text-secondary">{e.key_fact}</p>
                )}

                <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[length:var(--text-micro)] text-text-muted">
                  <span className="inline-flex items-center gap-1">
                    <span>Content hash</span>
                    <Hash value={e.content_hash} label="Content hash" />
                  </span>
                  {e.attested_against && (
                    <span title="What the snippet was checked against.">
                      attested against {e.attested_against.toLowerCase().replace(/_/g, " ")}
                    </span>
                  )}
                  <span>
                    {claims.length === 0
                      ? "supports no claim in the current revision"
                      : `supports ${claims.length} claim${claims.length === 1 ? "" : "s"}`}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
