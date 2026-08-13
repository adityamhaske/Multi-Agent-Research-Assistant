"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import toast from "react-hot-toast";

import { queryKeys, useApprove } from "@/hooks/queries";
import { ApiError } from "@/lib/api";
import { Report } from "@/lib/citations";
import { formatCost } from "@/lib/format";
import type { SessionDetail } from "@/lib/types";

const MAX_REWORK = 3;
const MAX_FEEDBACK = 1000;

function DraftSkeleton() {
  return (
    <div className="space-y-3" aria-hidden>
      {[90, 100, 80, 95, 70, 100, 85].map((w, i) => (
        <div key={i} className="h-3.5 animate-pulse bg-bg-elevated" style={{ width: `${w}%` }} />
      ))}
    </div>
  );
}

export function ApprovalGate({ session }: { session: SessionDetail }) {
  const qc = useQueryClient();
  const approve = useApprove(session.session_id);
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState<string | null>(null);

  const reworksUsed = session.rework_count;
  const canRework = reworksUsed < MAX_REWORK;
  const sources = session.sources ?? [];

  // Optimistically flip to RUNNING so the monitor re-subscribes immediately; a failure
  // re-fetches the true status.
  const optimisticRunning = () =>
    qc.setQueryData<SessionDetail>(queryKeys.session(session.session_id), (old) =>
      old ? { ...old, status: "RUNNING" } : old,
    );

  const onApprove = async () => {
    optimisticRunning();
    try {
      await approve.mutateAsync({ approved: true });
      toast.success("Approved — finalizing the report.");
    } catch (err) {
      qc.invalidateQueries({ queryKey: queryKeys.session(session.session_id) });
      toast.error(err instanceof ApiError ? err.message : "Could not approve.");
    }
  };

  const onRework = async () => {
    if (feedback.trim().length < 3) {
      setError("Please describe what to improve (the pipeline needs specific feedback).");
      return;
    }
    setError(null);
    const fb = feedback.trim();
    optimisticRunning();
    try {
      await approve.mutateAsync({ approved: false, feedback: fb });
      toast.success("Rework requested.");
      setFeedback("");
    } catch (err) {
      qc.invalidateQueries({ queryKey: queryKeys.session(session.session_id) });
      toast.error(err instanceof ApiError ? err.message : "Could not request rework.");
    }
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
      {/* Draft */}
      <section aria-labelledby="draft-heading" className="card min-w-0 p-6">
        <h2 id="draft-heading" className="mb-4 font-serif text-lg font-bold text-text-primary">
          Draft Report
        </h2>
        {session.draft_report ? (
          <Report markdown={session.draft_report} sources={sources} />
        ) : (
          <DraftSkeleton />
        )}
      </section>

      {/* Decision panel */}
      <aside className="lg:sticky lg:top-20 lg:self-start">
        <div className="card space-y-4 p-5">
          <div>
            <h2 className="font-serif text-base font-bold text-text-primary">Review Gate</h2>
            <p className="mt-1 text-xs text-text-muted">
              Approve to finalize, or request a targeted revision.
            </p>
          </div>

          <dl className="space-y-2 text-sm border-y border-border py-3">
            <div className="flex justify-between">
              <dt className="text-text-muted">Sources</dt>
              <dd className="font-mono text-text-primary tabular-nums">{sources.length}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-text-muted">Cost so far</dt>
              <dd className="font-mono text-text-primary tabular-nums">{formatCost(session.total_cost_usd)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-text-muted">Rework rounds</dt>
              <dd className="font-mono text-text-primary tabular-nums">
                {reworksUsed} of {MAX_REWORK} used
              </dd>
            </div>
          </dl>

          <button
            type="button"
            onClick={onApprove}
            disabled={approve.isPending}
            className="btn btn-primary w-full"
          >
            {approve.isPending && <span className="spinner" />}
            Approve &amp; finalize
          </button>

          <div className="border-t border-border pt-4">
            <label htmlFor="feedback" className="mb-1.5 block text-sm font-medium text-text-secondary">
              Request changes
            </label>
            <textarea
              id="feedback"
              rows={4}
              value={feedback}
              onChange={(e) => setFeedback(e.target.value.slice(0, MAX_FEEDBACK))}
              disabled={!canRework || approve.isPending}
              placeholder={
                canRework
                  ? "e.g. Add more on cost trade-offs and cite a primary source for the 2025 figures."
                  : "Rework limit reached."
              }
              className="textarea-base text-sm"
              aria-describedby="feedback-help"
            />
            <div id="feedback-help" className="mt-1 flex justify-between text-xs text-text-muted">
              <span>{canRework ? "Specific feedback yields better revisions." : "Approve or abandon."}</span>
              <span className="tabular-nums">
                {feedback.length}/{MAX_FEEDBACK}
              </span>
            </div>
            {error && (
              <p role="alert" className="mt-1 text-xs" style={{ color: "var(--danger)" }}>
                {error}
              </p>
            )}
            <button
              type="button"
              onClick={onRework}
              disabled={!canRework || approve.isPending || feedback.trim().length < 3}
              className="btn btn-secondary mt-2 w-full"
            >
              Request rework
            </button>
          </div>
        </div>
      </aside>
    </div>
  );
}
