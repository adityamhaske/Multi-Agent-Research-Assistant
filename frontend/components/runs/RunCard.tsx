"use client";

import Link from "next/link";
import { useState } from "react";
import toast from "react-hot-toast";

import { RelativeTime } from "@/components/RelativeTime";
import { useArchiveRun, useDeleteRun } from "@/hooks/runs";
import { formatCost } from "@/lib/format";
import { runStatusMeta } from "@/lib/runStatus";
import type { RunSummary } from "@/lib/types";

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
export function RunCard({ run, showProject }: { run: RunSummary; showProject?: string | null }) {
  const meta = runStatusMeta(run.status);
  const archived = Boolean(run.archived_at);
  const archive = useArchiveRun();
  const del = useDeleteRun();
  const [confirming, setConfirming] = useState(false);
  const busy = archive.isPending || del.isPending;

  const stop = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const onArchive = async (e: React.MouseEvent) => {
    stop(e);
    try {
      await archive.mutateAsync({ id: run.id, archived: !archived });
      toast.success(archived ? "Restored to History" : "Archived");
    } catch {
      toast.error(archived ? "Couldn't restore this run." : "Couldn't archive this run.");
    }
  };

  const onDelete = async (e: React.MouseEvent) => {
    stop(e);
    try {
      await del.mutateAsync(run.id);
      toast.success("Research run deleted");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't delete this run.");
      setConfirming(false);
    }
  };


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
      className="card card-interactive flex flex-col justify-between group p-4 hover:border-text-secondary transition-all h-full"
      style={{
        borderLeft: `3px solid ${borderLeftColor}`,
        paddingLeft: "calc(var(--card-pad, 1rem) - 2px)",
      }}
    >
      <div>
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
      </div>

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

        {/* Actions. Visible on hover/focus at pointer sizes, always visible on touch. */}
        <span className="ml-auto flex items-center gap-1.5 opacity-100 transition-opacity sm:opacity-0 sm:group-focus-within:opacity-100 sm:group-hover:opacity-100 font-sans">
          {confirming ? (
            <>
              <span className="text-[0.6875rem] text-danger font-medium">Delete permanently?</span>
              <button
                type="button"
                onClick={onDelete}
                disabled={busy}
                className="px-1.5 py-0.5 text-[0.6875rem] font-medium text-danger border border-danger/30 hover:bg-danger/10"
              >
                {del.isPending ? "Deleting…" : "Yes"}
              </button>
              <button
                type="button"
                onClick={(e) => {
                  stop(e);
                  setConfirming(false);
                }}
                className="px-1.5 py-0.5 text-[0.6875rem] text-text-muted border border-border hover:text-text-secondary"
              >
                No
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                onClick={onArchive}
                disabled={busy}
                className="px-1.5 py-0.5 text-[0.6875rem] text-text-muted border border-transparent hover:border-border hover:text-text-secondary"
                title={archived ? "Restore to History" : "Move out of History"}
              >
                {archived ? "Restore" : "Archive"}
              </button>
              <button
                type="button"
                onClick={(e) => {
                  stop(e);
                  setConfirming(true);
                }}
                disabled={busy}
                className="px-1.5 py-0.5 text-[0.6875rem] text-text-muted border border-transparent hover:border-danger/30 hover:text-danger"
                title="Delete permanently"
              >
                Delete
              </button>
            </>
          )}
        </span>
      </div>
    </Link>
  );
}
