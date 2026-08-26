"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { useActiveProject } from "@/components/ActiveProject";
import { FirstRunNotice } from "@/components/FirstRunNotice";
import { EmptyState } from "@/components/ui/EmptyState";
import { RunCard } from "@/components/runs/RunCard";
import { StartResearchForm } from "@/components/runs/StartResearchForm";
import { useRuns } from "@/hooks/runs";

/**
 * Research: ask a question, and see what this project has already established.
 *
 * Start and recent work live on one page deliberately. A research tool's first screen should
 * show what has already been established, not an empty box — the list is the reason to
 * trust the box.
 *
 * Project scoping comes from the switcher's context, not a second control here and not a
 * route param: one choice, one source of truth (frontend/AGENTS.md).
 */
export default function ResearchPage() {
  // `useSearchParams` forces a client bailout, which a static export refuses to prerender
  // without a boundary. The fallback must NOT be the same component — one that also reads
  // the query string fails the export in exactly the same way, which is what `build:desktop`
  // caught here and `build` did not. This is the third-target trap frontend/AGENTS.md
  // describes: a branch is only exercised by the target that builds it.
  return (
    <Suspense fallback={<ResearchSkeleton />}>
      <ResearchPageInner />
    </Suspense>
  );
}

function ResearchSkeleton() {
  return (
    <div className="space-y-8">
      <div className="h-8 w-48 animate-pulse bg-bg-elevated" aria-hidden />
      <div className="card h-64 animate-pulse" aria-hidden />
      <span className="sr-only">Loading research…</span>
    </div>
  );
}

function ResearchPageInner() {
  const router = useRouter();
  // Seeded by "Ask this question again" on a failed run. Read once, into form state.
  const seeded = useSearchParams()?.get("q") ?? "";
  // `activeId` is undefined while the switcher loads; scoped fetches hold off on that.
  const { activeId: projectId, active, isLoading: projectsLoading } = useActiveProject();
  const { data: runs, isLoading, isError, refetch } = useRuns(projectId ?? null);

  const waiting =
    runs?.filter((r) => r.status === "AWAITING_REVIEW" || r.status === "AWAITING_PLAN") ?? [];
  // Anything already surfaced above is not repeated below. A run appearing twice on one
  // screen reads as two runs, which is the opposite of what a list is for.
  const promoted = new Set(waiting.map((r) => r.id));
  const rest = runs?.filter((r) => !promoted.has(r.id)) ?? [];
  const recent = rest.slice(0, 8);

  return (
    <div className="space-y-8">
      {/* Above the form, not inside it: someone with no model configured needs to see the
          next step before they type a question they cannot run. */}
      <FirstRunNotice />

      <section aria-labelledby="new-research">
        <h1
          id="new-research"
          className="mb-1 font-serif text-2xl font-bold tracking-tight text-text-primary"
        >
          Research
        </h1>
        <p className="mb-5 max-w-2xl text-sm leading-relaxed text-text-muted">
          Ask a question. What comes back is a report whose every claim traces to a piece of
          evidence, a source, and a review decision you made — and a frozen artifact anyone
          can check without trusting this app.
        </p>

        <StartResearchForm
          initialQuestion={seeded}
          onStarted={(runId) => router.push(`/research/run?id=${runId}`)}
        />
      </section>

      {waiting.length > 0 && (
        <section aria-labelledby="waiting-on-you">
          <h2
            id="waiting-on-you"
            className="mb-3 font-serif text-lg font-bold tracking-tight text-text-primary"
          >
            Waiting on you
          </h2>
          <ul className="grid gap-3.5 sm:grid-cols-2">
            {waiting.map((r) => (
              <li key={r.id} className="h-full">
                <RunCard run={r} />
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-labelledby="recent-research">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h2
            id="recent-research"
            className="font-serif text-lg font-bold tracking-tight text-text-primary"
          >
            Earlier in this project
          </h2>
          <div className="flex items-baseline gap-3">
            {active && (
              <span className="font-mono text-xs text-text-muted">in {active.name}</span>
            )}
            {rest.length > recent.length && (
              <Link href="/history" className="font-mono text-xs text-accent hover:underline">
                All research →
              </Link>
            )}
          </div>
        </div>

        {projectsLoading || isLoading ? (
          <div className="grid gap-3.5 sm:grid-cols-2">
            {[0, 1].map((i) => (
              <div key={i} className="card h-28 animate-pulse" aria-hidden />
            ))}
            <span className="sr-only">Loading this project&apos;s research…</span>
          </div>
        ) : isError ? (
          <EmptyState
            title="Couldn't load this project's research"
            description="The list request failed. Your runs are not lost — this page could not read them."
            action={
              <button type="button" onClick={() => refetch()} className="btn btn-secondary">
                Try again
              </button>
            }
          />
        ) : recent.length === 0 ? (
          <EmptyState
            title={waiting.length > 0 ? "Nothing else here yet" : "No research yet"}
            description={
              waiting.length > 0
                ? "Every run in this project is waiting for a decision from you, above."
                : "Ask your first question above. Every run you start appears here with its review state and whether it produced a verified artifact."
            }
          />
        ) : (
          <ul className="grid gap-3.5 sm:grid-cols-2">
            {recent.map((r) => (
              <li key={r.id} className="h-full">
                <RunCard run={r} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
