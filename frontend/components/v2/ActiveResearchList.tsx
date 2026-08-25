"use client";

import Link from "next/link";

import { EmptyState } from "@/components/ui/EmptyState";
import { v2StatusMeta } from "@/lib/v2Status";
import type { V2RunSummary } from "@/lib/types";

import { RunCard } from "./RunCard";

/** Recently-finished runs shown before the reader is sent to History for the rest. */
const RECENT_LIMIT = 5;

/**
 * Everything in this project that is not the one run already promoted to the Attention
 * card above it — current and recently-finished work, in one compact, scannable list.
 *
 * Grouped rather than flat, because "what needs me", "what's happening now" and "what
 * just finished" are three different questions and a reader scanning for one should not
 * have to read past the other two. The three groups intentionally sort in different
 * directions: waiting-on-you is oldest-first (`lib/runPriority.ts` — fairness, so an early
 * decision is never pushed down by a later one), while in-progress and recently-finished
 * are newest-first (freshness — what's happening *now* is what matters there). A single
 * "recent" ordering for all three would have made one of those two rules wrong.
 *
 * `excludeId` is the run already shown in the Attention card. Repeating it here would be
 * the same run described twice on one screen, which reads as two runs — the same rule
 * `/research` already applies to its own "waiting on you" section.
 */
export function ActiveResearchList({
  runs,
  excludeId,
  isLoading,
  isError,
  onRetry,
}: {
  runs: V2RunSummary[];
  excludeId: string | null;
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
}) {
  if (isLoading) {
    return (
      <section aria-labelledby="active-research">
        <h2
          id="active-research"
          className="mb-3 font-serif text-lg font-bold tracking-tight text-text-primary"
        >
          Active research
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="card h-24 animate-pulse" aria-hidden />
          ))}
          <span className="sr-only">Loading this project&apos;s research…</span>
        </div>
      </section>
    );
  }

  // Only a *blank* failure replaces the list. React Query keeps the last successful `data`
  // when a background refetch fails, and the rest of the page (the attention card, the
  // health strip) goes on rendering those same rows from that cache — so replacing this
  // section with an error panel produced a page contradicting itself, and left the
  // attention card's "+N more waiting on you" link pointing at a heading that no longer
  // existed. With rows in hand the failure is reported as a banner above them instead.
  if (isError && runs.length === 0) {
    return (
      <section aria-labelledby="active-research">
        <h2
          id="active-research"
          className="mb-3 font-serif text-lg font-bold tracking-tight text-text-primary"
        >
          Active research
        </h2>
        <EmptyState
          title="Couldn't load this project's research"
          description="The list request failed. Your runs are not lost — this page could not read them."
          action={
            <button type="button" onClick={onRetry} className="btn btn-secondary">
              Try again
            </button>
          }
        />
      </section>
    );
  }

  const oldestFirst = (a: V2RunSummary, b: V2RunSummary) =>
    new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
  const newestFirst = (a: V2RunSummary, b: V2RunSummary) =>
    new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
  const isWaiting = (r: V2RunSummary) => v2StatusMeta(r.status).needsYou;
  const isInProgress = (r: V2RunSummary) => r.status === "PENDING" || r.status === "RUNNING";
  const isFinished = (r: V2RunSummary) =>
    r.status === "COMPLETED" || r.status === "CANCELLED" || r.status === "FAILED";

  const visible = runs.filter((r) => r.id !== excludeId);
  const waiting = visible.filter(isWaiting).sort(oldestFirst);
  const inProgress = visible.filter(isInProgress).sort(newestFirst);
  const finished = visible.filter(isFinished).sort(newestFirst);
  const finishedShown = finished.slice(0, RECENT_LIMIT);
  const finishedMore = finished.length - finishedShown.length;
  // Every status this client's type declares falls into one of the three buckets above —
  // but the wire is not the type, and `v2StatusMeta` already documents why a status this
  // build has not been taught is the ordinary shape of a migration, not a bug. A run in
  // that state still spent money and still deserves a row; it must not silently vanish
  // from every bucket because it matched none of them.
  const other = visible.filter((r) => !isWaiting(r) && !isInProgress(r) && !isFinished(r)).sort(newestFirst);

  return (
    <section aria-labelledby="active-research" className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3">
        <div className="flex items-center gap-3">
          <h2
            id="active-research"
            className="font-serif text-xl font-bold tracking-tight text-text-primary"
          >
            Active research
          </h2>
          {visible.length > 0 && (
            <span className="badge-frame">
              {visible.length} {visible.length === 1 ? "run" : "runs"}
            </span>
          )}
        </div>
        <Link href="/research" className="btn btn-primary h-8 px-3 text-xs">
          + New research
        </Link>
      </div>

      {isError && (
        <p
          role="status"
          className="border px-3.5 py-2.5 text-xs leading-relaxed text-text-secondary"
          style={{ borderColor: "var(--warning-line)", backgroundColor: "var(--warning-soft)" }}
        >
          Couldn&apos;t refresh this list, so it may be out of date.{" "}
          <button type="button" onClick={onRetry} className="font-semibold text-accent hover:underline">
            Try again
          </button>
        </p>
      )}

      {visible.length === 0 ? (
        excludeId ? (
          // Every run in this project is accounted for by the Attention card above —
          // an empty list here is not the same absence as a project with no research at
          // all, and the two must not read the same.
          <EmptyState
            title="Nothing else here yet"
            description="Every run in this project is waiting for a decision from you, above."
          />
        ) : (
          <EmptyState
            title="No research yet"
            description="Ask your first question above. Every run appears here with its state and, once approved, a verifiable artifact."
            action={
              <Link href="/research" className="btn btn-secondary text-xs">
                Ask a question
              </Link>
            }
          />
        )
      ) : (
        <div className="space-y-6">
          {waiting.length > 0 && (
            <div className="space-y-2.5">
              {/* `tabIndex={-1}` because this is the AttentionCard's in-page link target.
                  A non-focusable fragment target scrolls the viewport but does not reliably
                  move keyboard focus (Safari in particular), so the next Tab returns the
                  reader to where they started and AT gives no sign they arrived. */}
              <div className="flex items-center gap-2">
                <span className="flex h-2 w-2 bg-warning shrink-0" aria-hidden />
                <h3
                  id="waiting-on-you"
                  tabIndex={-1}
                  className="scroll-mt-4 font-mono text-[length:var(--text-micro)] font-bold uppercase tracking-wider text-warning"
                >
                  Waiting on you
                </h3>
                <span className="font-mono text-[length:var(--text-micro)] text-text-muted font-normal">
                  ({waiting.length})
                </span>
              </div>
              <ul className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {waiting.map((r) => (
                  <li key={r.id}>
                    <RunCard run={r} />
                  </li>
                ))}
              </ul>
            </div>
          )}

          {inProgress.length > 0 && (
            <div className="space-y-2.5">
              <div className="flex items-center gap-2">
                <span className="flex h-2 w-2 bg-info animate-pulse shrink-0" aria-hidden />
                <h3 className="font-mono text-[length:var(--text-micro)] font-bold uppercase tracking-wider text-info">
                  In progress
                </h3>
                <span className="font-mono text-[length:var(--text-micro)] text-text-muted font-normal">
                  ({inProgress.length})
                </span>
              </div>
              <ul className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {inProgress.map((r) => (
                  <li key={r.id}>
                    <RunCard run={r} />
                  </li>
                ))}
              </ul>
            </div>
          )}

          {finishedShown.length > 0 && (
            <div className="space-y-2.5">
              <div className="flex items-center gap-2">
                <span className="flex h-2 w-2 bg-text-muted shrink-0" aria-hidden />
                <h3 className="font-mono text-[length:var(--text-micro)] font-semibold uppercase tracking-wider text-text-muted">
                  Recently finished
                </h3>
                <span className="font-mono text-[length:var(--text-micro)] text-text-muted font-normal">
                  ({finished.length})
                </span>
              </div>
              <ul className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {finishedShown.map((r) => (
                  <li key={r.id}>
                    <RunCard run={r} />
                  </li>
                ))}
              </ul>
              {finishedMore > 0 && (
                <div className="pt-1">
                  <Link
                    href="/history"
                    className="inline-flex items-center gap-1 font-mono text-xs text-accent hover:underline"
                  >
                    +{finishedMore} more in History →
                  </Link>
                </div>
              )}
            </div>
          )}

          {other.length > 0 && (
            <div className="space-y-2.5">
              <h3 className="font-mono text-[length:var(--text-micro)] font-semibold uppercase tracking-wider text-text-muted">
                Other
              </h3>
              <ul className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {other.map((r) => (
                  <li key={r.id}>
                    <RunCard run={r} />
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
