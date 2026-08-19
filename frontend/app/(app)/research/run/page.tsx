"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { EmptyState } from "@/components/ui/EmptyState";
import { CancelButton, RunWorkspace } from "@/components/v2/RunWorkspace";
import { runTotals } from "@/components/v2/primitives";
import { isLive, useV2Run, useV2RunStream } from "@/hooks/v2";
import { shouldOpenStream } from "@/lib/sessionStream";

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
 * Live runs subscribe to the real event stream: no simulated progress, and no aggressive
 * polling — a dropped stream reconnects with `Last-Event-ID` and the backend replays what
 * was missed.
 */
export default function RunPage() {
  return (
    <Suspense fallback={<p className="p-6 text-sm text-text-muted">Loading run…</p>}>
      <RunPageInner />
    </Suspense>
  );
}

function RunPageInner() {
  const runId = useSearchParams().get("id") ?? "";
  const { data: graph, isLoading, error } = useV2Run(runId || null);
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
  const { degraded } = useV2RunStream(runId, shouldOpenStream(graph?.run.status), graph?.run.status);

  if (!runId) {
    return (
      <div className="p-6">
        <EmptyState title="No run selected" description="Open a run from the Research page." />
      </div>
    );
  }
  if (isLoading) return <p className="p-6 text-sm text-text-muted">Loading run…</p>;
  if (error || !graph)
    return (
      <div className="p-6">
        <EmptyState title="Run not found" description="It may belong to another account." />
      </div>
    );

  const totals = runTotals(graph);

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
      <header className="space-y-2">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-lg font-semibold text-text-primary">{graph.run.question}</h1>
            <p className="mt-1 text-xs text-text-secondary">
              <StatusLine status={graph.run.status} error={graph.run.error_message} />
            </p>
          </div>
          {live && <CancelButton runId={runId} />}
        </div>

        {degraded && live && (
          <p className="rounded border border-status-warning/40 bg-status-warning-bg p-2 text-xs text-status-warning">
            The live connection dropped. It reconnects automatically and replays anything
            missed; this page is not stuck.
          </p>
        )}

        {!live && (
          <div className="flex flex-wrap gap-4 text-xs text-text-secondary">
            <span>{totals.claims.length} claims</span>
            <span>{totals.evidence} evidence</span>
            <span>
              {totals.citedSources} cited / {totals.uncitedSources} retrieved-only sources
            </span>
            <span className={totals.contradictions ? "text-status-warning" : undefined}>
              {totals.contradictions} conflicting pairs
            </span>
          </div>
        )}
      </header>

      <RunWorkspace graph={graph} />
    </div>
  );
}

function StatusLine({ status, error }: { status: string; error: string | null }) {
  switch (status) {
    case "PENDING":
      return <>Queued. Waiting for a worker.</>;
    case "RUNNING":
      return <>Running — planning, retrieving and drafting. This page updates as it goes.</>;
    case "AWAITING_PLAN":
      return <>Paused: the research plan is waiting for your approval.</>;
    case "AWAITING_REVIEW":
      return <>Paused: a draft report is waiting for your review.</>;
    case "COMPLETED":
      return <>Approved. A verifiable artifact exists for this run.</>;
    case "CANCELLED":
      return <>A stop was requested. Work already in flight ran to its next checkpoint.</>;
    case "FAILED":
      return <span className="text-status-danger">Failed: {error ?? "no reason recorded"}</span>;
    default:
      return <>{status}</>;
  }
}
