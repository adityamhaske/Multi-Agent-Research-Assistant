"use client";

import Link from "next/link";

import { RelativeTime } from "@/components/RelativeTime";
import { formatCost } from "@/lib/format";
import { v2StatusMeta } from "@/lib/v2Status";
import type { V2RunSummary } from "@/lib/types";

/**
 * One research run in a list.
 *
 * Used by Research, History and the project overview, so the three cannot describe the same
 * run differently — which they did: one printed a lower-cased status string, one printed a
 * date, and only one of them mentioned the artifact.
 *
 * What a row has to answer, in scanning order: what was asked, does it need me, is it
 * verified, and when. "Needs you" is the one that earns emphasis, because it is the only
 * state where reading the list is not the end of the task.
 */
export function RunCard({ run, showProject }: { run: V2RunSummary; showProject?: string | null }) {
  const meta = v2StatusMeta(run.status);

  return (
    <Link
      href={`/research/run?id=${run.id}`}
      className="card card-interactive block hover:border-accent"
      // A left rule rather than a filled panel. Filling the card worked for one row and
      // turned a list of five pending reviews into a solid block of amber, which stops
      // distinguishing anything — the emphasis has to survive repetition.
      style={
        meta.needsYou
          ? { borderLeft: "3px solid var(--warning)", paddingLeft: "calc(var(--card-pad) - 2px)" }
          : undefined
      }
    >
      <div className="flex items-start justify-between gap-3">
        <p className="min-w-0 break-words text-sm leading-relaxed text-text-primary">
          {run.question}
        </p>
        <span
          className="badge shrink-0 border-border font-mono text-[length:var(--text-micro)] text-text-secondary"
          title={meta.sentence}
        >
          <span
            aria-hidden
            className="status-marker"
            style={{ backgroundColor: `var(--${meta.token})` }}
          />
          {meta.label}
        </span>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[length:var(--text-micro)] text-text-muted">
        <RelativeTime iso={run.created_at} />
        <span>{run.depth}</span>
        <span>{formatCost(run.cost_usd)}</span>
        {showProject && <span>{showProject}</span>}
        {run.demo && (
          <span style={{ color: "var(--warning)" }} title="Scripted models and fixture sources.">
            demo
          </span>
        )}
        {run.has_artifact ? (
          <span style={{ color: "var(--success)" }}>✓ verified artifact</span>
        ) : (
          <span title="An artifact exists only once a person approves the report.">
            no artifact yet
          </span>
        )}
        {/* `null` means unmeasured and must never render as 0%. */}
        {run.citation_resolution_rate !== null && (
          <span
            title="Share of this report's citation markers that resolve to a real source."
            style={
              run.citation_resolution_rate < 1 ? { color: "var(--warning)" } : undefined
            }
          >
            {Math.round(run.citation_resolution_rate * 100)}% citations resolve
          </span>
        )}
      </div>
    </Link>
  );
}
