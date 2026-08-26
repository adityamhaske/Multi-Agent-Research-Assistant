"use client";

import { useMemo, useState } from "react";

import { useActiveProject } from "@/components/ActiveProject";
import { SessionHistory } from "@/components/history/SessionHistory";
import { EmptyState } from "@/components/ui/EmptyState";
import { RunCard } from "@/components/runs/RunCard";
import { useRuns } from "@/hooks/runs";
import { RUN_STATUS_ORDER, runStatusMeta } from "@/lib/runStatus";
import type { RunStatus } from "@/lib/types";

/**
 * Everything that has been researched.
 *
 * This page used to list sessions and nothing else, while the runs it exists to record
 * were reachable only from a list at the bottom of the Research page. A user who clicked
 * "History" after doing research in this product saw none of it.
 *
 * The filters are derived from data every row already carries, so none of them can lie
 * about what they select. Two are worth spelling out:
 *
 * - **Artifact** is not a synonym for "finished". A run can be COMPLETED and carry no
 *   artifact, and the difference is exactly the product's claim, so it filters separately.
 * - **Status options are the statuses actually present on this page**, not the whole
 *   vocabulary, so the strip never offers a filter that selects nothing.
 */

type Scope = "project" | "all";
type Verified = "any" | "artifact" | "none";

export default function HistoryPage() {
  const { activeId, active, projects } = useActiveProject();
  const [scope, setScope] = useState<Scope>("project");
  const [status, setStatus] = useState<RunStatus | "ALL">("ALL");
  const [verified, setVerified] = useState<Verified>("any");
  const [query, setQuery] = useState("");
  const [showArchived, setShowArchived] = useState(false);

  const { data: runs, isLoading, isError, refetch } = useRuns(
    scope === "project" ? (activeId ?? null) : null,
    showArchived,
  );

  const projectNames = useMemo(
    () => new Map(projects.map((p) => [p.id, p.name])),
    [projects],
  );

  const present = useMemo(() => {
    const seen = new Set(runs?.map((r) => r.status) ?? []);
    return RUN_STATUS_ORDER.filter((s) => seen.has(s));
  }, [runs]);

  const needle = query.trim().toLowerCase();
  const visible = (runs ?? []).filter(
    (r) =>
      (status === "ALL" || r.status === status) &&
      (verified === "any" ||
        (verified === "artifact" ? r.has_artifact : !r.has_artifact)) &&
      (needle === "" || r.question.toLowerCase().includes(needle)),
  );

  const filtering = status !== "ALL" || verified !== "any" || needle !== "";

  return (
    <div className="space-y-8">
      <section aria-labelledby="history-heading" className="space-y-4">
        <div>
          <h1
            id="history-heading"
            className="font-serif text-2xl font-bold tracking-tight text-text-primary"
          >
            {showArchived ? "Archived history" : "History"}
          </h1>
          <p className="mt-1 max-w-2xl text-sm leading-relaxed text-text-muted">
            {showArchived
              ? "Archived research runs. You can restore them to active history or delete them permanently."
              : "Every research run, with the decision it is waiting on and whether it produced a verifiable artifact."}
          </p>
        </div>

        <div className="flex flex-wrap items-end gap-x-4 gap-y-3">
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[length:var(--text-micro)] uppercase tracking-wider text-text-muted">
              Search questions
            </span>
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter by wording…"
              className="input-base h-8 w-56 py-1 text-xs"
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="font-mono text-[length:var(--text-micro)] uppercase tracking-wider text-text-muted">
              Scope
            </span>
            <select
              value={scope}
              onChange={(e) => setScope(e.target.value as Scope)}
              className="input-base h-8 w-44 py-1 text-xs"
            >
              <option value="project">{active ? active.name : "This project"}</option>
              <option value="all">All projects</option>
            </select>
          </label>

          <label className="flex flex-col gap-1">
            <span className="font-mono text-[length:var(--text-micro)] uppercase tracking-wider text-text-muted">
              Artifact
            </span>
            <select
              value={verified}
              onChange={(e) => setVerified(e.target.value as Verified)}
              className="input-base h-8 w-44 py-1 text-xs"
            >
              <option value="any">Any</option>
              <option value="artifact">Has a verified artifact</option>
              <option value="none">No artifact yet</option>
            </select>
          </label>

          {present.length > 1 && (
            <div className="flex flex-wrap gap-1" role="group" aria-label="Filter by status">
              <button
                type="button"
                aria-pressed={status === "ALL"}
                onClick={() => setStatus("ALL")}
                className={`border px-3 py-1 font-mono text-xs font-medium transition-colors ${
                  status === "ALL"
                    ? "border-accent bg-accent text-accent-contrast"
                    : "border-border bg-bg-surface text-text-muted hover:text-text-primary"
                }`}
              >
                All
              </button>
              {present.map((s) => (
                <button
                  key={s}
                  type="button"
                  aria-pressed={status === s}
                  onClick={() => setStatus(s)}
                  className={`border px-3 py-1 font-mono text-xs font-medium transition-colors ${
                    status === s
                      ? "border-accent bg-accent text-accent-contrast"
                      : "border-border bg-bg-surface text-text-muted hover:text-text-primary"
                  }`}
                >
                  {runStatusMeta(s).label}
                </button>
              ))}
            </div>
          )}

          <button
            type="button"
            onClick={() => setShowArchived((v) => !v)}
            aria-pressed={showArchived}
            className={`border px-3 py-1 font-mono text-xs font-medium transition-colors ${
              showArchived
                ? "border-accent bg-accent text-accent-contrast"
                : "border-border bg-bg-surface text-text-muted hover:text-text-primary"
            }`}
          >
            {showArchived ? "← Active History" : "Archived"}
          </button>
        </div>

        {isLoading ? (
          <div className="grid gap-3 sm:grid-cols-2">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="card h-28 animate-pulse" aria-hidden />
            ))}
            <span className="sr-only">Loading your research history…</span>
          </div>
        ) : isError ? (
          <EmptyState
            title="Couldn't load your history"
            description="The request failed. Nothing has been lost — this page could not read it."
            action={
              <button type="button" onClick={() => refetch()} className="btn btn-secondary">
                Try again
              </button>
            }
          />
        ) : (runs ?? []).length === 0 ? (
          <EmptyState
            title={showArchived ? "Nothing archived" : "No research yet"}
            description={
              showArchived
                ? "Archiving moves a research run out of History without deleting it."
                : scope === "project"
                  ? "Nothing has been researched in this project. Start a question and it will be recorded here."
                  : "Nothing has been researched in any of your projects yet."
            }
          />
        ) : visible.length === 0 ? (
          <EmptyState
            title="Nothing matches these filters"
            description={`${runs!.length} run${runs!.length === 1 ? "" : "s"} are hidden by the current filters.`}
            action={
              <button
                type="button"
                onClick={() => {
                  setStatus("ALL");
                  setVerified("any");
                  setQuery("");
                }}
                className="btn btn-secondary"
              >
                Clear filters
              </button>
            }
          />
        ) : (
          <>
            <p className="font-mono text-xs text-text-muted" aria-live="polite">
              {filtering
                ? `${visible.length} of ${runs!.length} runs`
                : `${visible.length} run${visible.length === 1 ? "" : "s"}`}
            </p>
            <ul className="grid gap-3 sm:grid-cols-2">
              {visible.map((r) => (
                <li key={r.id} className="h-full">
                  <RunCard
                    run={r}
                    showProject={
                      scope === "all" ? (projectNames.get(r.project_id) ?? null) : null
                    }
                  />
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      {/* Research recorded as sessions, kept readable rather than hidden — and rendered
          as nothing at all on an account that has none. */}
      <SessionHistory />
    </div>
  );
}
