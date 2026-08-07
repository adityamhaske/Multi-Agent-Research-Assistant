"use client";

import Link from "next/link";
import { useState } from "react";

import { SessionCard } from "@/components/SessionCard";
import { useSessions } from "@/hooks/queries";
import type { SessionStatus } from "@/lib/types";

const LIMIT = 20;

const FILTERS: { value: SessionStatus | "ALL"; label: string }[] = [
  { value: "ALL", label: "All" },
  { value: "RUNNING", label: "Running" },
  { value: "AWAITING_APPROVAL", label: "Needs review" },
  { value: "COMPLETED", label: "Completed" },
  { value: "FAILED", label: "Failed" },
];

export default function HistoryPage() {
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState<SessionStatus | "ALL">("ALL");
  // Archived is a separate destination, not another status filter — a session is
  // archived *or* active, and mixing them would defeat the point of getting one
  // out of the way. Switching views resets paging.
  const [showArchived, setShowArchived] = useState(false);
  const { data, isLoading, isError, refetch, isFetching } = useSessions(
    page,
    LIMIT,
    showArchived
  );

  const rows = data?.sessions ?? [];
  const visible = filter === "ALL" ? rows : rows.filter((s) => s.status === filter);
  const totalPages = data ? Math.max(1, Math.ceil(data.total / LIMIT)) : 1;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold text-text-primary">
          {showArchived ? "Archived" : "History"}
        </h1>
        <div className="flex flex-wrap gap-1" role="tablist" aria-label="Filter by status">
          {FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              role="tab"
              aria-selected={filter === f.value}
              onClick={() => setFilter(f.value)}
              className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                filter === f.value
                  ? "bg-accent-muted text-accent"
                  : "bg-bg-elevated text-text-muted hover:text-text-secondary"
              }`}
            >
              {f.label}
            </button>
          ))}
          <button
            type="button"
            onClick={() => {
              setShowArchived((v) => !v);
              setPage(1);
            }}
            aria-pressed={showArchived}
            className={`ml-1 rounded-full px-3 py-1 text-xs font-medium transition-colors ${
              showArchived
                ? "bg-accent-muted text-accent"
                : "bg-bg-elevated text-text-muted hover:text-text-secondary"
            }`}
          >
            {showArchived ? "← Back to History" : "Archived"}
          </button>
        </div>
      </div>

      {isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="card h-28 animate-pulse" aria-hidden />
          ))}
        </div>
      ) : isError ? (
        <div className="card text-sm text-text-muted">
          Couldn&apos;t load sessions.{" "}
          <button onClick={() => refetch()} className="text-accent hover:underline">
            Retry
          </button>
        </div>
      ) : rows.length === 0 ? (
        <div className="card text-center">
          {showArchived ? (
            <p className="text-sm text-text-secondary">
              Nothing archived. Archiving moves a session out of History without deleting it.
            </p>
          ) : (
            <>
              <p className="text-sm text-text-secondary">No research sessions yet.</p>
              <Link
                href="/dashboard"
                className="mt-2 inline-block text-sm text-accent hover:underline"
              >
                Start your first research →
              </Link>
            </>
          )}
        </div>
      ) : visible.length === 0 ? (
        <div className="card text-center text-sm text-text-muted">
          No sessions match this filter on this page.
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2" aria-busy={isFetching}>
          {visible.map((s) => (
            <SessionCard key={s.session_id} session={s} />
          ))}
        </div>
      )}

      {data && totalPages > 1 && (
        <div className="flex items-center justify-center gap-3 pt-2">
          <button
            type="button"
            className="btn btn-secondary"
            disabled={page <= 1 || isFetching}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            ← Prev
          </button>
          <span className="text-sm text-text-muted tabular-nums">
            Page {page} of {totalPages}
          </span>
          <button
            type="button"
            className="btn btn-secondary"
            disabled={page >= totalPages || isFetching}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}
