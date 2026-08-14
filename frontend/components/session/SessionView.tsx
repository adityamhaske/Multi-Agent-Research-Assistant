"use client";

import Link from "next/link";

import toast from "react-hot-toast";

import { RelativeTime } from "@/components/RelativeTime";
import { StatusBadge } from "@/components/StatusBadge";
import { ApprovalGate } from "@/components/session/ApprovalGate";
import { FailedState } from "@/components/session/FailedState";
import { LiveFeed } from "@/components/session/LiveFeed";
import { PipelineRail } from "@/components/session/PipelineRail";
import { ReportView } from "@/components/session/ReportView";
import { StatusBar } from "@/components/session/StatusBar";
import { useCancelSession, useSession } from "@/hooks/queries";
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
  const cancelSession = useCancelSession();
  const session = sessionQuery.data;
  const status = session?.status;

  // Stream while the pipeline is doing work. Approve/rework flips status back to RUNNING
  // (optimistically), which re-enables this and re-subscribes through the same path.
  const streamEnabled = status === "PENDING" || status === "RUNNING";
  const stream = useSessionStream(sessionId, streamEnabled);

  const handleStop = async () => {
    try {
      await cancelSession.mutateAsync(sessionId);
      toast.success("Research stopped.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not stop research.");
    }
  };

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
        <Link href="/history" className="font-mono text-xs text-text-muted hover:text-text-secondary">
          ← All sessions
        </Link>
        <div className="mt-2 flex flex-wrap items-start justify-between gap-3">
          <h1 className="max-w-3xl font-serif text-xl font-bold tracking-tight text-text-primary">{session.prompt}</h1>
          <div className="flex items-center gap-2.5 whitespace-nowrap">
            <StatusBadge status={session.status} />
            {(status === "PENDING" || status === "RUNNING") && (
              <button
                type="button"
                onClick={handleStop}
                disabled={cancelSession.isPending}
                className="badge font-mono text-[0.6875rem] font-semibold uppercase tracking-wider text-danger border-danger/40 bg-danger/10 hover:bg-danger/20 hover:border-danger transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                title="Stop current research run"
              >
                {cancelSession.isPending ? (
                  <span className="spinner" style={{ width: 8, height: 8 }} />
                ) : (
                  <span className="status-marker" style={{ backgroundColor: "var(--danger)" }} />
                )}
                Stop research
              </button>
            )}
            <span className="font-mono text-xs text-text-muted ml-1">
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

      {status === "AWAITING_APPROVAL" && (
        <div className="space-y-4">
          {/* The rail stays up at the gate. It used to unmount the moment the run paused —
              exactly when its last node, Review, becomes the active step — so the one
              stage the user is personally responsible for was never shown as current. */}
          <div className="card">
            <PipelineRail events={stream.events} status={session.status} />
          </div>
          <ApprovalGate session={session} />
        </div>
      )}
      {status === "COMPLETED" && <ReportView session={session} />}
      {status === "FAILED" && <FailedState session={session} />}
    </div>
  );
}
