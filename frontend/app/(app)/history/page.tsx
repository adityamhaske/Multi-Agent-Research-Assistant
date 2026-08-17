"use client";

import Link from "next/link";
import { useState } from "react";

import { useActiveProject } from "@/components/ActiveProject";
import { SessionCard } from "@/components/SessionCard";
import { useSessions } from "@/hooks/queries";
import { STATUS_ORDER, statusMeta } from "@/lib/status";
import type { SessionStatus } from "@/lib/types";

const LIMIT = 20;

/**
 * Derived from the shared vocabulary, never restated (docs/07 §2, Phase 7). This list
 * was hand-written and had already fallen behind: `AWAITING_PLAN` was missing, so a run
 * parked at the design gate — the one a user is most likely scanning for — could be seen
 * and not filtered for.
 */
const FILTERS: { value: SessionStatus | "ALL"; label: string }[] = [
  { value: "ALL", label: "All" },
  ...STATUS_ORDER.map((value) => ({ value, label: statusMeta(value).label })),
];

/** Depth is on every session row, so it filters client-side like status does. */
const DEPTHS = ["fast", "balanced", "comprehensive"] as const;

/**
 * Verified-citation rate bands. The product's central claim, made scannable.
 *
 * "Unmeasured" is its own band rather than being swept into the lowest one: a report
 * with no citable claims and a report whose every marker is broken are opposite
 * findings, and `citation_resolution_rate` is `null` for the first and `0` for the
 * second. A band of "under 80%" that quietly included nulls would be the
 * unmeasured-as-zero bug wearing a filter.
 */
const CITATION_BANDS = {
  ALL: { label: "Any", match: () => true },
  PERFECT: { label: "100% verified", match: (r: number | null) => r === 1 },
  PARTIAL: { label: "Under 100%", match: (r: number | null) => r !== null && r < 1 },
  UNMEASURED: { label: "Not measured", match: (r: number | null) => r === null },
} as const;

export default function HistoryPage() {
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState<SessionStatus | "ALL">("ALL");
  const [depth, setDepth] = useState<(typeof DEPTHS)[number] | "ALL">("ALL");
  const [band, setBand] = useState<keyof typeof CITATION_BANDS>("ALL");
  const [model, setModel] = useState<string>("ALL");
  // Archived is a separate destination, not another status filter — a session is
  // archived *or* active, and mixing them would defeat the point of getting one
  // out of the way. Switching views resets paging.
  const [showArchived, setShowArchived] = useState(false);
  const { activeId, active } = useActiveProject();
  const { data, isLoading, isError, refetch, isFetching } = useSessions(
    page,
    LIMIT,
    showArchived,
    activeId
  );

  const rows = data?.sessions ?? [];
  // Every distinct route any listed run dialled, so the picker only offers models that
  // actually appear on this page rather than the whole catalog.
  const models = Array.from(
    new Set(rows.flatMap((s) => Object.values(s.model_routing ?? {}))),
  ).sort();

  const visible = rows.filter(
    (s) =>
      (filter === "ALL" || s.status === filter) &&
      (depth === "ALL" || s.research_depth === depth) &&
      CITATION_BANDS[band].match(s.citation_resolution_rate) &&
      (model === "ALL" || Object.values(s.model_routing ?? {}).includes(model)),
  );
  const totalPages = data ? Math.max(1, Math.ceil(data.total / LIMIT)) : 1;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-serif text-xl font-bold tracking-tight text-text-primary">
            {showArchived ? "Archived Research" : "Research History"}
          </h1>
          {active && (
            <p className="mt-0.5 font-mono text-xs text-text-muted">
              in <span className="text-text-secondary">{active.name}</span>
            </p>
          )}
        </div>
        {/* Two independent axes, laid out as two controls: a single row of tabs would
            imply that picking a depth clears the status, which it does not. */}
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-1.5 font-mono text-xs text-text-muted">
            <span>Depth</span>
            <select
              value={depth}
              onChange={(e) => setDepth(e.target.value as typeof depth)}
              className="border border-border bg-bg-surface px-2 py-1 font-mono text-xs text-text-primary"
            >
              <option value="ALL">Any</option>
              {DEPTHS.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </label>

          <label className="flex items-center gap-1.5 font-mono text-xs text-text-muted">
            <span>Citations</span>
            <select
              value={band}
              onChange={(e) => setBand(e.target.value as keyof typeof CITATION_BANDS)}
              className="border border-border bg-bg-surface px-2 py-1 font-mono text-xs text-text-primary"
            >
              {Object.entries(CITATION_BANDS).map(([key, b]) => (
                <option key={key} value={key}>
                  {b.label}
                </option>
              ))}
            </select>
          </label>

          {models.length > 1 && (
            <label className="flex items-center gap-1.5 font-mono text-xs text-text-muted">
              <span>Model</span>
              <select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="max-w-[12rem] border border-border bg-bg-surface px-2 py-1 font-mono text-xs text-text-primary"
              >
                <option value="ALL">Any</option>
                {models.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </label>
          )}

          <div className="flex flex-wrap gap-1" role="tablist" aria-label="Filter by status">
            {FILTERS.map((f) => (
              <button
                key={f.value}
                type="button"
                role="tab"
                aria-selected={filter === f.value}
                onClick={() => setFilter(f.value)}
                className={`px-3 py-1 font-mono text-xs font-medium border transition-colors ${
                  filter === f.value
                    ? "bg-accent text-white border-accent"
                    : "bg-bg-surface text-text-muted border-border hover:text-text-primary"
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
              className={`ml-1 px-3 py-1 font-mono text-xs font-medium border transition-colors ${
                showArchived
                  ? "bg-accent text-white border-accent"
                  : "bg-bg-surface text-text-muted border-border hover:text-text-primary"
              }`}
            >
              {showArchived ? "← Active History" : "Archived"}
            </button>
          </div>
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
              <p className="text-sm text-text-secondary">
                No research in {active ? `“${active.name}”` : "this project"} yet.
              </p>
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
