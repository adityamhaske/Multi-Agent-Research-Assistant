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

  // Status-colored left border accent
  let borderLeftColor = "transparent";
  if (meta.needsYou) {
    borderLeftColor = "var(--warning)";
  } else if (run.status === "FAILED" || run.status === "CANCELLED") {
    borderLeftColor = "var(--danger)";
  } else if (run.status === "COMPLETED") {
    borderLeftColor = "var(--success)";
  } else if (run.status === "RUNNING" || run.status === "PENDING") {
    borderLeftColor = "var(--info)";
  }

  return (
    <Link
      href={`/research/run?id=${run.id}`}
      className="card card-interactive block group p-4 hover:border-text-secondary transition-all"
      style={{
        borderLeft: `3px solid ${borderLeftColor}`,
        paddingLeft: "calc(var(--card-pad, 1rem) - 2px)",
      }}
    >
      {/* Top Context & Status Row */}
      <div className="flex items-center justify-between gap-3 border-b border-border/40 pb-2 mb-2.5">
        <div className="flex flex-wrap items-center gap-2 font-mono text-[length:var(--text-micro)] text-text-muted">
          <RelativeTime iso={run.created_at} />
          <span>·</span>
          <span className="capitalize">{run.depth}</span>
          <span>·</span>
          <span className="font-semibold text-text-secondary">{formatCost(run.cost_usd)}</span>
          {showProject && (
            <>
              <span>·</span>
              <span className="text-text-secondary">{showProject}</span>
            </>
          )}
          {run.demo && (
            <span
              className="border border-warning-line bg-warning-soft px-1.5 py-0.2 font-semibold text-warning"
              title="Scripted models and fixture sources."
            >
              demo
            </span>
          )}
        </div>

        {/* Status Badge */}
        <span
          className="badge shrink-0 border-border bg-bg-elevated font-mono text-[length:var(--text-micro)] font-medium text-text-primary"
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

      {/* Research Question */}
      <p className="min-w-0 line-clamp-2 break-words text-[0.9375rem] font-medium leading-snug text-text-primary group-hover:text-accent transition-colors">
        {run.question}
      </p>

      {/* Bottom Telemetry & Artifact Status Bar */}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-border/30 pt-2.5 text-xs">
        <div className="flex flex-wrap items-center gap-2">
          {run.has_artifact ? (
            <span className="inline-flex items-center gap-1 font-mono text-[length:var(--text-micro)] font-semibold text-success bg-success-soft border border-success-line px-2 py-0.5">
              ✓ verified artifact
            </span>
          ) : (
            <span
              className="font-mono text-[length:var(--text-micro)] text-text-muted bg-bg-elevated px-2 py-0.5"
              title="An artifact exists only once a person approves the report."
            >
              no artifact yet
            </span>
          )}
        </div>

        {/* Citation Resolution Pill */}
        {run.citation_resolution_rate !== null && (
          <span
            className={`font-mono text-[length:var(--text-micro)] px-2 py-0.5 ${
              run.citation_resolution_rate < 1
                ? "border border-warning-line bg-warning-soft text-warning font-semibold"
                : "bg-bg-elevated text-text-secondary"
            }`}
            title="Share of this report's citation markers that resolve to a real source."
          >
            {Math.round(run.citation_resolution_rate * 100)}% citations resolve
          </span>
        )}
      </div>
    </Link>
  );
}
