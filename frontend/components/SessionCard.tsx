"use client";

import Link from "next/link";
import { useState } from "react";
import toast from "react-hot-toast";

import { useArchiveSession, useDeleteSession } from "@/hooks/queries";
import { sessionHref } from "@/lib/desktop";
import { formatCost } from "@/lib/format";
import type { SessionSummary } from "@/lib/types";

import { RelativeTime } from "./RelativeTime";
import { StatusBadge } from "./StatusBadge";

/**
 * A session row with its own archive/delete affordances.
 *
 * The whole card is a link, so the actions are real buttons layered on top and must
 * stop propagation — otherwise "Delete" would also navigate into the session being
 * deleted. Delete asks for confirmation inline rather than via window.confirm: it is
 * irreversible (report, logs, chat, and the graph checkpoints all go), and an inline
 * two-step keeps the warning honest about that.
 */
export function SessionCard({ session }: { session: SessionSummary }) {
  const archived = Boolean(session.archived_at);
  const archive = useArchiveSession();
  const del = useDeleteSession();
  const [confirming, setConfirming] = useState(false);
  const busy = archive.isPending || del.isPending;

  const stop = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const onArchive = async (e: React.MouseEvent) => {
    stop(e);
    try {
      await archive.mutateAsync({ id: session.session_id, archived: !archived });
      toast.success(archived ? "Restored to History" : "Archived");
    } catch {
      toast.error(archived ? "Couldn't restore this session." : "Couldn't archive this session.");
    }
  };

  const onDelete = async (e: React.MouseEvent) => {
    stop(e);
    try {
      await del.mutateAsync(session.session_id);
      toast.success("Session deleted");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't delete this session.");
      setConfirming(false);
    }
  };

  return (
    <Link
      href={sessionHref(session.session_id)}
      className="card card-interactive group relative block p-5"
    >
      <div className="flex items-center justify-between gap-2">
        <StatusBadge status={session.status} />
        <span className="text-xs text-text-muted">
          <RelativeTime iso={session.created_at} />
        </span>
      </div>

      <p className="mt-3 line-clamp-2 text-[0.9375rem] leading-snug text-text-primary transition-colors group-hover:text-accent">
        {session.prompt}
      </p>

      <div className="mt-3.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-text-muted">
        <span className="capitalize">{session.research_depth}</span>
        <span aria-hidden>·</span>
        <span className="tabular-nums">{formatCost(session.total_cost_usd)}</span>
        {session.rework_count > 0 && (
          <>
            <span aria-hidden>·</span>
            <span>
              {session.rework_count} rework{session.rework_count > 1 ? "s" : ""}
            </span>
          </>
        )}

        {/* Actions. Visible on hover/focus at pointer sizes, always visible on touch. */}
        <span className="ml-auto flex items-center gap-1.5 opacity-100 transition-opacity sm:opacity-0 sm:group-focus-within:opacity-100 sm:group-hover:opacity-100">
          {confirming ? (
            <>
              <span className="text-[0.6875rem] text-danger">Delete permanently?</span>
              <button
                type="button"
                onClick={onDelete}
                disabled={busy}
                className="rounded px-1.5 py-0.5 text-[0.6875rem] font-medium text-danger hover:bg-danger/10"
              >
                {del.isPending ? "Deleting…" : "Yes"}
              </button>
              <button
                type="button"
                onClick={(e) => {
                  stop(e);
                  setConfirming(false);
                }}
                className="rounded px-1.5 py-0.5 text-[0.6875rem] text-text-muted hover:text-text-secondary"
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
                className="rounded px-1.5 py-0.5 text-[0.6875rem] text-text-muted hover:text-text-secondary"
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
                className="rounded px-1.5 py-0.5 text-[0.6875rem] text-text-muted hover:text-danger"
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
