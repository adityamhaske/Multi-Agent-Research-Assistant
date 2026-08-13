"use client";

import { useRouter } from "next/navigation";
import toast from "react-hot-toast";

import { useStartResearch } from "@/hooks/queries";
import { ApiError } from "@/lib/api";
import { SourcesPanel } from "@/lib/citations";
import { sessionHref } from "@/lib/desktop";
import type { ResearchDepth, SessionDetail } from "@/lib/types";

export function FailedState({ session }: { session: SessionDetail }) {
  const router = useRouter();
  const start = useStartResearch();
  const sources = session.sources ?? [];

  const restart = async () => {
    try {
      const res = await start.mutateAsync({
        query: session.prompt,
        depth: (session.research_depth as ResearchDepth) ?? "balanced",
        project_id: session.project_id ?? null,
        corpus_mode: session.corpus_mode,
      });
      router.push(sessionHref(res.session_id));
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not restart research.");
    }
  };

  return (
    <div className="card">
      <div className="flex items-start gap-3">
        <span
          aria-hidden
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full"
          style={{ backgroundColor: "color-mix(in srgb, var(--danger) 14%, transparent)", color: "var(--danger)" }}
        >
          ✕
        </span>
        <div className="min-w-0">
          <h1 className="text-lg font-semibold text-text-primary">Research failed</h1>
          <p className="mt-1 text-sm text-text-secondary">
            {session.error_message || "The pipeline stopped unexpectedly before producing a report."}
          </p>
        </div>
      </div>

      <div className="mt-4 rounded-lg bg-bg-elevated p-3">
        <p className="text-xs text-text-muted">Original query</p>
        <p className="mt-0.5 text-sm text-text-primary">{session.prompt}</p>
      </div>

      {sources.length > 0 && (
        <>
          <p className="mt-4 text-sm text-text-secondary">
            {sources.length} source{sources.length > 1 ? "s were" : " was"} gathered before the failure.
          </p>
          <SourcesPanel sources={sources} />
        </>
      )}

      <button type="button" onClick={restart} disabled={start.isPending} className="btn btn-primary mt-6">
        {start.isPending && <span className="spinner" />}
        Start new research from this query
      </button>
    </div>
  );
}
