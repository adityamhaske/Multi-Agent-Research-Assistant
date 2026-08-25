"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback } from "react";

import { useActiveProject } from "@/components/ActiveProject";
import { EmptyState } from "@/components/ui/EmptyState";
import { RunProgress } from "@/components/v2/RunProgress";
import { CancelButton, RunWorkspace } from "@/components/v2/RunWorkspace";
import { RunStatusBadge, runTotals } from "@/components/v2/primitives";
import { isLive, useV2Run, useV2RunStream } from "@/hooks/v2";
import { ApiError } from "@/lib/api";
import { formatCost } from "@/lib/format";
import { shouldOpenStream } from "@/lib/sessionStream";
import { v2StatusMeta } from "@/lib/v2Status";
import { isTab, type Tab } from "@/lib/v2Tabs";
import type { V2RunGraph } from "@/lib/types";

/**
 * One research run, from question to verified artifact.
 *
 * **A query parameter, not a path segment.** The desktop host is a static export and cannot
 * pre-render `/research/[runId]` without enumerating every run id at build time. The repo
 * already carries one workaround for that (`app-routes/session/{web,desktop}` plus a copy
 * script), and a second copy of the same trick would be a second implementation of one page
 * — which is exactly what frontend/AGENTS.md says not to do. One static route, read from
 * the query string, works identically on both hosts.
 *
 * The workspace tab lives in the query string too, for the same reason a tab should: a
 * refresh, a bookmark, a shared link and the browser's Back button all have to land where
 * the reader was. It was component state, so all four lost the reader's place.
 *
 * Live runs subscribe to the real event stream: no simulated progress, and no aggressive
 * polling — a dropped stream reconnects with `Last-Event-ID` and the backend replays what
 * was missed.
 */
export default function RunPage() {
  return (
    <Suspense fallback={<RunSkeleton />}>
      <RunPageInner />
    </Suspense>
  );
}

function RunSkeleton() {
  return (
    <div className="space-y-4">
      <div className="h-6 w-2/3 animate-pulse bg-bg-elevated" aria-hidden />
      <div className="h-4 w-1/3 animate-pulse bg-bg-elevated" aria-hidden />
      <div className="card h-40 animate-pulse" aria-hidden />
      <span className="sr-only">Loading this research run…</span>
    </div>
  );
}

function RunPageInner() {
  const router = useRouter();
  const params = useSearchParams();
  const runId = params.get("id") ?? "";
  const tabParam = params.get("tab");
  const initialTab: Tab | null = isTab(tabParam) ? tabParam : null;

  const { data: graph, isLoading, error, refetch, isFetching } = useV2Run(runId || null);
  const live = isLive(graph?.run.status);
  // Subscribe for every loaded run, finished ones included — not just while `live`.
  // The stream is the only path by which this host reads `agent_logs`: the V2 stream
  // endpoint replays them on connect and then ends the response at a terminal event, so
  // a finished run costs one short request and yields its history. Gating on `live`
  // discarded that history entirely, and made the reconnect journey a race the page
  // usually lost — a fake-mode run reaches the review gate in well under a second, so the
  // first fetch often resolved after the run was already terminal and no stream was ever
  // opened. `lib/sessionStream.ts` records V1 hitting and fixing exactly this; V2 shipped
  // with the unfixed copy.
  const { events, degraded } = useV2RunStream(
    runId,
    shouldOpenStream(graph?.run.status),
    graph?.run.status,
  );

  // `push`, so Back undoes the last thing the reader did rather than throwing them out of
  // the run. `replace` was tried first and reads worse in practice: clicking Evidence and
  // then pressing Back left the run entirely, which is not what "back" meant to anyone who
  // had just clicked a tab. The cost is that walking all eight tabs leaves eight entries;
  // the benefit is that the first Back is always an undo.
  //
  // Only a tab a *person* picked lands here. The automatic re-route when a run reaches a
  // gate deliberately does not, so a run moving to AWAITING_REVIEW under the reader does
  // not rewrite their history behind them.
  const setTab = useCallback(
    (tab: Tab) => {
      const next = new URLSearchParams(params.toString());
      next.set("tab", tab);
      router.push(`/research/run?${next.toString()}`, { scroll: false });
    },
    [params, router],
  );

  if (!runId) {
    return (
      <EmptyState
        title="No run selected"
        description="This link is missing a run id."
        action={
          <Link href="/research" className="btn btn-primary">
            Go to Research
          </Link>
        }
      />
    );
  }

  if (isLoading) return <RunSkeleton />;

  if (error || !graph) {
    const status = error instanceof ApiError ? error.status : null;
    return (
      <EmptyState
        title={status === 404 ? "Run not found" : "Couldn't load this run"}
        description={
          status === 404
            ? "It may have been deleted, or it belongs to another account."
            : error instanceof ApiError
              ? error.message
              : "The request failed before it reached the server. Check your connection and try again."
        }
        action={
          <div className="flex flex-wrap items-center justify-center gap-3">
            {status !== 404 && (
              <button
                type="button"
                onClick={() => refetch()}
                className="btn btn-primary"
                disabled={isFetching}
              >
                {isFetching && <span className="spinner" />}
                Try again
              </button>
            )}
            <Link href="/research" className="btn btn-secondary">
              Back to Research
            </Link>
          </div>
        }
      />
    );
  }

  return (
    <div className="space-y-5">
      <RunHeader graph={graph} live={live} />

      {/* Progress is for a run that has not finished. On an approved run it would be a
          checklist of ticks nobody needs, above the thing they came for. */}
      {graph.run.status !== "COMPLETED" && (
        <RunProgress graph={graph} events={events} degraded={degraded && live} />
      )}

      <RunWorkspace graph={graph} initialTab={initialTab} onTabChange={setTab} />
    </div>
  );
}

function RunHeader({ graph, live }: { graph: V2RunGraph; live: boolean }) {
  const { active } = useActiveProject();
  const meta = v2StatusMeta(graph.run.status);
  const totals = runTotals(graph);
  const inActiveProject = active?.id === graph.run.project_id;

  const isFailed = graph.run.status === "FAILED";
  const isCancelled = graph.run.status === "CANCELLED";

  return (
    <header className="card space-y-4">
      {/* 1. Context Eyebrow & Actions Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="badge-frame uppercase tracking-wider">
            {inActiveProject && active ? active.name : "Research"}
          </span>
          <span className="font-mono text-[length:var(--text-micro)] text-text-muted">
            {new Date(graph.run.created_at).toLocaleString()}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {live && <CancelButton runId={graph.run.id} />}
          {(isFailed || isCancelled) && (
            <Link
              href={`/research?q=${encodeURIComponent(graph.run.question)}`}
              className="btn btn-secondary text-xs"
            >
              Ask again
            </Link>
          )}
        </div>
      </div>

      {/* 2. Research Question in a prominent typography container */}
      <div>
        <h1 className="break-words font-serif text-xl font-bold tracking-tight text-text-primary sm:text-2xl leading-snug">
          {graph.run.question}
        </h1>
      </div>

      {/* 3. Run Properties & Status Strip */}
      <div className="flex flex-wrap items-center justify-between gap-3 bg-bg-elevated p-2.5 sm:px-3">
        <div className="flex flex-wrap items-center gap-2">
          <RunStatusBadge status={graph.run.status} />
          {graph.run.demo && (
            <span
              className="badge font-mono text-[length:var(--text-micro)] font-semibold"
              style={{
                color: "var(--warning)",
                backgroundColor: "var(--warning-soft)",
                borderColor: "var(--warning-line)",
              }}
              title="Scripted models and fixture sources. Shows the whole pipeline without calling a provider — not real research."
            >
              Demo run
            </span>
          )}
          {graph.run.corpus_mode && (
            <span
              className="badge border-border font-mono text-[length:var(--text-micro)] text-text-secondary"
              title="No web search. Evidence comes only from this project's uploaded documents."
            >
              Corpus only
            </span>
          )}
          <span className="inline-flex items-center gap-1.5 font-mono text-[length:var(--text-micro)] text-text-muted">
            <span className="capitalize">{graph.run.depth}</span>
            <span>·</span>
            <span>{formatCost(graph.run.cost_usd)}</span>
            {graph.run.elapsed_seconds ? (
              <>
                <span>·</span>
                <span>{Math.round(graph.run.elapsed_seconds)}s</span>
              </>
            ) : null}
          </span>
        </div>

        {/* Status explanation phrase */}
        <p className="text-xs text-text-secondary">
          {meta.sentence}
        </p>
      </div>

      {/* Error Callout if Failed */}
      {isFailed && graph.run.error_message && (
        <div className="border border-danger-line bg-danger-soft p-3 text-xs text-danger">
          <span className="font-semibold">Failure reason: </span>
          {graph.run.error_message}
        </div>
      )}

      {/* 4. Evidence Chain Summary Grid (Academic 4-column KPI stats) */}
      {!live && totals.latest && (
        <div className="border-t border-border pt-3">
          <p className="mb-2 font-mono text-[length:var(--text-micro)] font-semibold uppercase tracking-wider text-text-muted">
            Evidence Chain Overview
          </p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <div className="border border-border bg-bg-surface p-2.5">
              <dt className="text-[length:var(--text-micro)] uppercase tracking-wider text-text-muted">
                Claims
              </dt>
              <dd className="mt-1 flex items-baseline gap-1.5 font-mono">
                <span className="text-lg font-bold text-text-primary">
                  {totals.claims.length}
                </span>
                <span className="text-xs text-text-secondary">
                  ({totals.supported} supported)
                </span>
              </dd>
            </div>

            <div className="border border-border bg-bg-surface p-2.5">
              <dt className="text-[length:var(--text-micro)] uppercase tracking-wider text-text-muted">
                Evidence
              </dt>
              <dd className="mt-1 flex items-baseline gap-1.5 font-mono">
                <span className="text-lg font-bold text-text-primary">
                  {totals.evidence}
                </span>
                <span className="text-xs text-text-secondary">snippets</span>
              </dd>
            </div>

            <div className="border border-border bg-bg-surface p-2.5">
              <dt className="text-[length:var(--text-micro)] uppercase tracking-wider text-text-muted">
                Sources
              </dt>
              <dd className="mt-1 flex items-baseline gap-1.5 font-mono">
                <span className="text-lg font-bold text-text-primary">
                  {totals.citedSources}
                </span>
                <span className="text-xs text-text-secondary">
                  cited ({totals.uncitedSources} uncited)
                </span>
              </dd>
            </div>

            <div
              className={`border p-2.5 ${
                totals.contradictions
                  ? "border-warning-line bg-warning-soft text-warning"
                  : "border-border bg-bg-surface"
              }`}
            >
              <dt className="text-[length:var(--text-micro)] uppercase tracking-wider text-text-muted">
                Contradictions
              </dt>
              <dd className="mt-1 flex items-baseline gap-1.5 font-mono">
                <span
                  className={`text-lg font-bold ${
                    totals.contradictions ? "text-warning" : "text-text-primary"
                  }`}
                >
                  {totals.contradictions}
                </span>
                <span className="text-xs text-text-secondary">
                  conflicting pair{totals.contradictions === 1 ? "" : "s"}
                </span>
              </dd>
            </div>
          </div>
        </div>
      )}
    </header>
  );
}
