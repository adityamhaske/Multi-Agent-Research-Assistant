"use client";

import { useMemo } from "react";

import { EmptyState } from "@/components/ui/EmptyState";
import type { V2Contradiction, V2RunGraph, V2Source } from "@/lib/types";

/**
 * Where two sources cannot both be right.
 *
 * The product surfaces conflicts and refuses to resolve them, so the layout puts the two
 * quotations side by side at equal weight and never picks a winner. It is also careful
 * about the three things absence can mean, because they are different findings and the
 * backend stores them as different rows:
 *
 * - a `DETECTED` pair — two distinct sources, both anchored;
 * - a `NOT_RUN` row — the detector produced a pair it could not anchor to two sources;
 * - a `DETECTOR_UNAVAILABLE` row — the detector could not run at all.
 *
 * Only the first is a conflict. The other two used to be merged into one warning that said
 * neither of the things they mean.
 */

function Side({
  label,
  source,
  quote,
  summary,
}: {
  label: string;
  source: V2Source | null | undefined;
  quote: string | null;
  summary: string | null;
}) {
  return (
    <div className="bg-bg-surface p-3">
      <p className="font-mono text-[length:var(--text-micro)] font-semibold uppercase tracking-wider text-text-muted">
        {label}
      </p>
      {source ? (
        <a
          href={source.url}
          target="_blank"
          rel="noreferrer noopener"
          className="mt-1 block break-words text-xs font-medium text-accent hover:underline"
        >
          {source.title || source.url}
        </a>
      ) : (
        <span className="mt-1 block text-xs text-text-muted">Source not recorded</span>
      )}
      {summary && (
        <p className="mt-1.5 break-words text-sm leading-relaxed text-text-primary">{summary}</p>
      )}
      {quote && (
        <blockquote className="mt-1.5 border-l-2 border-border pl-2 text-xs leading-relaxed break-words text-text-secondary">
          {quote}
        </blockquote>
      )}
    </div>
  );
}

export function ContradictionsPanel({ graph }: { graph: V2RunGraph }) {
  const sourceById = useMemo(() => new Map(graph.sources.map((s) => [s.id, s])), [graph.sources]);

  const detected = graph.contradictions.filter((c) => c.detection_state === "DETECTED");
  const unanchored = graph.contradictions.filter((c) => c.detection_state === "NOT_RUN");
  const unavailable = graph.contradictions.filter(
    (c) => c.detection_state === "DETECTOR_UNAVAILABLE",
  );

  if (graph.contradictions.length === 0) {
    const noReport = graph.revisions.length === 0;
    return (
      <EmptyState
        title={noReport ? "Nothing to compare yet" : "No conflicting claims recorded"}
        description={
          noReport
            ? "Conflicts are looked for once a run has gathered evidence and drafted a report."
            : "Nothing in this run was recorded as conflicting. A detector that cannot run records itself as unavailable, so an empty list here means no conflicting pair was found rather than that the check was skipped."
        }
      />
    );
  }

  return (
    <div className="space-y-3">
      {unavailable.length > 0 && (
        <p
          className="border p-2.5 text-xs leading-relaxed"
          style={{
            color: "var(--warning)",
            backgroundColor: "var(--warning-soft)",
            borderColor: "var(--warning-line)",
          }}
        >
          <strong>The conflict detector could not run for this run.</strong> That is not a
          clean bill of health — nothing has looked for conflicting sources here, so an empty
          list below says nothing either way.
        </p>
      )}

      {detected.length > 0 && (
        <p className="text-xs leading-relaxed text-text-secondary">
          {detected.length} pair{detected.length === 1 ? "" : "s"} where two sources cannot
          both be right. Both sides are shown at equal weight:{" "}
          <strong className="text-text-primary">the report does not decide between them</strong>
          , and neither does this page.
        </p>
      )}

      <ul className="space-y-3">
        {detected.map((c: V2Contradiction, i) => {
          const a = c.source_a_id ? sourceById.get(c.source_a_id) : null;
          const b = c.source_b_id ? sourceById.get(c.source_b_id) : null;
          return (
            <li key={c.id} className="border border-border">
              <h3 className="border-b border-border bg-bg-elevated px-3 py-2 font-mono text-[length:var(--text-micro)] font-semibold uppercase tracking-wider text-text-secondary">
                Conflict {i + 1}
                {c.dimension && c.dimension !== "UNCLASSIFIED" && (
                  <span className="ml-2 normal-case tracking-normal text-text-muted">
                    {c.dimension.toLowerCase().replace(/_/g, " ")}
                  </span>
                )}
              </h3>
              <div className="grid gap-px bg-border md:grid-cols-2">
                <Side label="Source A says" source={a} quote={c.quote_a} summary={c.summary_a} />
                <Side label="Source B says" source={b} quote={c.quote_b} summary={c.summary_b} />
              </div>
              {c.nature && (
                <p className="border-t border-border p-3 text-xs leading-relaxed text-text-secondary">
                  <span className="font-medium text-text-primary">Why this matters: </span>
                  {c.nature}
                </p>
              )}
              <p className="border-t border-border px-3 py-2 text-[length:var(--text-micro)] leading-relaxed text-text-muted">
                Surfaced, not resolved. The report does not decide between these — a reviewer
                does.
                {c.evidence_a_id === null && (
                  <>
                    {" "}
                    The quoted text could not be matched to exactly one evidence item, so no
                    evidence link is claimed.
                  </>
                )}
              </p>
            </li>
          );
        })}
      </ul>

      {unanchored.length > 0 && (
        <p className="text-xs leading-relaxed text-text-muted">
          {unanchored.length} further record{unanchored.length === 1 ? "" : "s"} where the
          detector produced a pair it could not anchor to two distinct sources. Not shown as a
          conflict, and not dropped either: a pair nothing can be checked against is a
          different finding from no pair at all.
        </p>
      )}
    </div>
  );
}
