"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useActiveProject } from "@/components/ActiveProject";
import { EmptyState } from "@/components/ui/EmptyState";
import { useStartV2Research, useV2Runs } from "@/hooks/v2";

/**
 * Research: start a run, and see the ones this project already has.
 *
 * Start and History live on one page deliberately. A research tool's first screen should
 * show what has already been established, not an empty box — the list is the reason to
 * trust the box.
 *
 * Project scoping comes from the switcher's context, not a second control here and not a
 * route param: one choice, one source of truth (frontend/AGENTS.md).
 */
export default function ResearchPage() {
  const router = useRouter();
  // `activeId` is undefined while the switcher loads; scoped fetches hold off on that.
  const { activeId: projectId, isLoading: projectsLoading } = useActiveProject();
  const [question, setQuestion] = useState("");
  const start = useStartV2Research();
  const { data: runs, isLoading } = useV2Runs(projectId ?? null);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!projectId || !question.trim()) return;
    start.mutate(
      { project_id: projectId, question: question.trim() },
      { onSuccess: (r) => router.push(`/research/run?id=${r.run_id}`) },
    );
  };

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-4 sm:p-6">
      <header>
        <h1 className="text-xl font-semibold text-text-primary">Research</h1>
        <p className="mt-1 text-sm text-text-secondary">
          Ask a question. What comes back is a report whose every claim traces to evidence, a
          source, and a review decision you made.
        </p>
      </header>

      <form onSubmit={submit} className="card space-y-3 p-4">
        <div>
          <label htmlFor="question" className="text-xs font-medium text-text-secondary">
            Research question
          </label>
          <textarea
            id="question"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            rows={3}
            placeholder="What does the evidence say about…?"
            className="input mt-1 w-full"
          />
        </div>
        <div className="flex items-center justify-between gap-3">
          {/* A disabled button with no reason is the worst state a first-run user can meet:
              it looks broken rather than blocked. Say which of the two it is. */}
          <p className="text-xs text-text-muted">
            {projectsLoading
              ? "Loading your projects…"
              : projectId
                ? "The run pauses for your review before anything is finalised."
                : "Create a project first — research is always scoped to one."}
          </p>
          <button
            type="submit"
            className="btn-primary"
            disabled={start.isPending || !question.trim() || !projectId}
          >
            {start.isPending ? "Starting…" : "Start research"}
          </button>
        </div>
        {start.isError && (
          <p className="text-xs text-status-danger">{(start.error as Error).message}</p>
        )}
      </form>

      <section>
        <h2 className="text-sm font-semibold text-text-primary">History</h2>
        {isLoading && <p className="mt-2 text-sm text-text-muted">Loading…</p>}
        {!isLoading && (!runs || runs.length === 0) && (
          <EmptyState
            title="No research yet"
            description="Runs you start appear here with their review and artifact state."
          />
        )}
        <ul className="mt-2 space-y-2">
          {runs?.map((r) => (
            <li key={r.id}>
              <Link href={`/research/run?id=${r.id}`} className="card block p-3 hover:border-accent">
                <div className="flex items-start justify-between gap-3">
                  <p className="text-sm text-text-primary">{r.question}</p>
                  <span className="shrink-0 rounded bg-bg-elevated px-1.5 py-0.5 text-[0.6875rem] text-text-secondary">
                    {r.status.replace(/_/g, " ").toLowerCase()}
                  </span>
                </div>
                <div className="mt-1.5 flex flex-wrap gap-3 text-[0.6875rem] text-text-muted">
                  <span>{new Date(r.created_at).toLocaleString()}</span>
                  {r.has_artifact && (
                    <span className="text-status-success">✓ verified artifact</span>
                  )}
                  {r.demo && <span>demo</span>}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
