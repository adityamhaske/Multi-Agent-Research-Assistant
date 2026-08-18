"use client";

import Link from "next/link";

import { useV2Runs } from "@/hooks/v2";

/**
 * The V2 research panel on the project overview.
 *
 * Deliberately operational, not analytical: what is running, what is waiting for a decision,
 * and what already has a verified artifact. No charts, no trends — a project overview should
 * answer "what needs me?" in one glance.
 */
export function ProjectResearch({ projectId }: { projectId: string | undefined }) {
  const { data: runs, isLoading } = useV2Runs(projectId ?? null);
  const recent = runs?.slice(0, 5) ?? [];
  const waiting = runs?.filter((r) => r.status === "AWAITING_REVIEW" || r.status === "AWAITING_PLAN")
    .length;

  return (
    <section aria-labelledby="v2-research" className="card">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 id="v2-research" className="font-serif text-base font-bold text-text-primary">
          Research
        </h2>
        <Link href="/research" className="font-mono text-xs text-accent hover:underline">
          + New research
        </Link>
      </div>

      {waiting ? (
        <p className="mb-3 rounded border border-status-warning/40 bg-status-warning-bg p-2 text-xs text-status-warning">
          {waiting} run{waiting === 1 ? "" : "s"} waiting for your decision.
        </p>
      ) : null}

      {isLoading && <div className="h-16 animate-pulse bg-bg-elevated" aria-hidden />}
      {!isLoading && recent.length === 0 && (
        <p className="text-sm text-text-secondary">
          No research yet. A run produces evidence, claims and sources you can inspect, and a
          verifiable artifact once you approve it.
        </p>
      )}

      <ul className="space-y-2">
        {recent.map((r) => (
          <li key={r.id}>
            <Link
              href={`/research/run?id=${r.id}`}
              className="block rounded border border-border-subtle p-2 hover:border-accent"
            >
              <div className="flex items-start justify-between gap-2">
                <p className="line-clamp-2 text-sm text-text-primary">{r.question}</p>
                <span className="shrink-0 text-[0.6875rem] text-text-secondary">
                  {r.status.replace(/_/g, " ").toLowerCase()}
                </span>
              </div>
              <div className="mt-1 flex flex-wrap gap-3 text-[0.6875rem] text-text-muted">
                <span>{new Date(r.created_at).toLocaleDateString()}</span>
                {r.has_artifact && (
                  <span className="text-status-success">✓ verified artifact</span>
                )}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
