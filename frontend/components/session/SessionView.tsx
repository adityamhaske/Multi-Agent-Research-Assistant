"use client";

import Link from "next/link";

import { RelativeTime } from "@/components/RelativeTime";
import { StatusBadge } from "@/components/StatusBadge";
import { ApprovalGate } from "@/components/session/ApprovalGate";
import { FailedState } from "@/components/session/FailedState";
import { LiveFeed } from "@/components/session/LiveFeed";
import { PipelineRail } from "@/components/session/PipelineRail";
import { ReportView } from "@/components/session/ReportView";
import { StatusBar } from "@/components/session/StatusBar";
import { useSession } from "@/hooks/queries";
import { useSessionStream } from "@/hooks/useSessionStream";
import { ApiError } from "@/lib/api";

/**
 * The session detail body, shared by the dynamic `/session/[sessionId]` route (web)
 * and the static `/session?id=` route (desktop export, docs/13 §7). It lives in its
 * own client module because `generateStaticParams` cannot be exported from a
 * "use client" page file.
 */
export function SessionView({ sessionId }: { sessionId: string }) {
  // useSession self-polls every 5s while the run is active (docs/07 §3) — SSE is the
  // fast path for live events, polling is the safety net for state transitions. The page
  // used to hang on the monitor forever if the terminal event was ever missed.
  const sessionQuery = useSession(sessionId);
  const session = sessionQuery.data;
  const status = session?.status;

  // Stream while the pipeline is doing work. Approve/rework flips status back to RUNNING
  // (optimistically), which re-enables this and re-subscribes through the same path.
  const streamEnabled = status === "PENDING" || status === "RUNNING";
  const stream = useSessionStream(sessionId, streamEnabled);

  if (sessionQuery.isLoading) {
    return (
      <div className="space-y-4">
        <div className="card h-16 animate-pulse" aria-hidden />
        <div className="card h-64 animate-pulse" aria-hidden />
        <span className="sr-only">Loading session…</span>
      </div>
    );
  }

  if (sessionQuery.isError || !session) {
    const notFound = sessionQuery.error instanceof ApiError && sessionQuery.error.status === 404;
    return (
      <div className="card text-center">
        <p className="text-sm text-text-secondary">
          {notFound ? "This research session doesn't exist." : "Couldn't load this session."}
        </p>
        <div className="mt-3 flex justify-center gap-3">
          {!notFound && (
            <button onClick={() => sessionQuery.refetch()} className="btn btn-secondary">
              Retry
            </button>
          )}
          <Link href="/history" className="btn btn-primary">
            Back to history
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <Link href="/history" className="text-sm text-text-muted hover:text-text-secondary">
          ← All sessions
        </Link>
        <div className="mt-2 flex flex-wrap items-start justify-between gap-3">
          <h1 className="max-w-3xl text-lg font-semibold text-text-primary">{session.prompt}</h1>
          <div className="flex items-center gap-3 whitespace-nowrap">
            <StatusBadge status={session.status} />
            <span className="text-xs text-text-muted">
              <RelativeTime iso={session.created_at} />
            </span>
          </div>
        </div>
      </div>

      {/* State-driven body */}
      {(status === "PENDING" || status === "RUNNING") && (
        <div className="space-y-4">
          <div className="card">
            <PipelineRail events={stream.events} status={session.status} />
          </div>
          <StatusBar session={session} events={stream.events} running />
          <div className="h-[28rem]">
            <LiveFeed events={stream.events} state={stream.state} />
          </div>
        </div>
      )}

      {status === "AWAITING_APPROVAL" && <ApprovalGate session={session} />}
      {status === "COMPLETED" && <ReportView session={session} />}
      {status === "FAILED" && <FailedState session={session} />}
    </div>
  );
}
