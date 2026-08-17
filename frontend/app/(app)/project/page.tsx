"use client";

import Link from "next/link";

import { useActiveProject } from "@/components/ActiveProject";
import { RelativeTime } from "@/components/RelativeTime";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/ui/EmptyState";
import {
  useCorpusDocuments,
  useCorpusStatus,
  useMemoryStatus,
  useModelRouting,
  useSessions,
} from "@/hooks/queries";
import { isDesktop, sessionHref } from "@/lib/desktop";
import { formatCost } from "@/lib/format";

/**
 * The project workspace hub (docs/07 §2, Phase 6; req 9).
 *
 * A project used to be a filter applied to four unrelated pages: you could scope History
 * to it, scope Corpus to it, scope Chat to it, and never see the project itself. This is
 * the view where those are one thing — recent runs, what the corpus holds, what memory
 * knows, and which models this project's research is dialling.
 *
 * Every panel states its own emptiness rather than rendering a zero. "0 documents"
 * and "we could not read the corpus" look identical as a number, and only one of them is
 * the user's to fix — the same unmeasured-vs-zero rule the rest of the product runs on.
 */
export default function ProjectPage() {
  const { activeId, active } = useActiveProject();
  const sessions = useSessions(1, 5, false, activeId);
  const corpus = useCorpusStatus(activeId);
  const documents = useCorpusDocuments(activeId);
  const memory = useMemoryStatus(activeId ?? undefined);
  const routing = useModelRouting();

  if (!activeId || !active) {
    return (
      <EmptyState
        title="No project selected"
        description="Pick a project from the switcher above to see its workspace."
      />
    );
  }

  const runs = sessions.data?.sessions ?? [];
  const spend = runs.reduce((total, s) => total + (s.total_cost_usd || 0), 0);

  return (
    <div className="space-y-8" key={activeId}>
      <header>
        <h1 className="font-serif text-2xl font-bold tracking-tight text-text-primary">
          {active.name}
        </h1>
        {active.description && (
          <p className="mt-1 max-w-2xl text-sm leading-relaxed text-text-secondary">
            {active.description}
          </p>
        )}
      </header>

      <div className="grid gap-4 lg:grid-cols-3">
        {/* Recent runs */}
        <section aria-labelledby="runs" className="card lg:col-span-2">
          <div className="mb-3 flex items-baseline justify-between">
            <h2 id="runs" className="font-serif text-base font-bold text-text-primary">
              Recent research
            </h2>
            <Link href="/history" className="font-mono text-xs text-accent hover:underline">
              All runs →
            </Link>
          </div>

          {sessions.isLoading ? (
            <div className="h-24 animate-pulse bg-bg-elevated" aria-hidden />
          ) : sessions.isError ? (
            <p className="text-sm text-text-secondary">
              Couldn&apos;t load this project&apos;s runs.
            </p>
          ) : runs.length === 0 ? (
            <p className="text-sm text-text-secondary">
              Nothing researched here yet.{" "}
              <Link href="/dashboard" className="text-accent hover:underline">
                Ask a question
              </Link>{" "}
              to start.
            </p>
          ) : (
            <ul className="divide-y divide-border">
              {runs.map((s) => (
                <li key={s.session_id} className="flex items-center justify-between gap-3 py-2.5">
                  <Link
                    href={sessionHref(s.session_id)}
                    className="min-w-0 flex-1 truncate text-sm text-text-primary hover:text-accent"
                  >
                    {s.prompt}
                  </Link>
                  <div className="flex shrink-0 items-center gap-2.5">
                    <StatusBadge status={s.status} />
                    <span className="font-mono text-xs text-text-muted">
                      <RelativeTime iso={s.created_at} />
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Spend across the runs actually listed. Deliberately not "project total": these
            are the five most recent, and labelling a partial sum as a total would be a
            number that reads as a measurement it is not. */}
        <section aria-labelledby="spend" className="card">
          <h2 id="spend" className="mb-3 font-serif text-base font-bold text-text-primary">
            These runs
          </h2>
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between">
              <dt className="text-text-muted">Shown</dt>
              <dd className="font-mono tabular-nums text-text-primary">{runs.length}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-text-muted">Their cost</dt>
              <dd className="font-mono tabular-nums text-text-primary">{formatCost(spend)}</dd>
            </div>
          </dl>
          <p className="mt-2 text-xs leading-snug text-text-muted">
            The five most recent runs, not the project total — a partial sum labelled as a
            total is a number that lies.
          </p>
        </section>

        {/* Corpus */}
        <section aria-labelledby="corpus" className="card">
          <div className="mb-3 flex items-baseline justify-between">
            <h2 id="corpus" className="font-serif text-base font-bold text-text-primary">
              Corpus
            </h2>
            <Link href="/corpus" className="font-mono text-xs text-accent hover:underline">
              Manage →
            </Link>
          </div>
          {corpus.isLoading ? (
            <div className="h-12 animate-pulse bg-bg-elevated" aria-hidden />
          ) : corpus.isError ? (
            <p className="text-sm text-text-secondary">Couldn&apos;t read the corpus.</p>
          ) : (
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-text-muted">Documents</dt>
                <dd className="font-mono tabular-nums text-text-primary">
                  {corpus.data?.documents ?? 0}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-text-muted">Chunks</dt>
                <dd className="font-mono tabular-nums text-text-primary">
                  {corpus.data?.chunks ?? 0}
                </dd>
              </div>
            </dl>
          )}
          {documents.data && documents.data.length > 0 && (
            <ul className="mt-3 space-y-1 border-t border-border pt-3">
              {documents.data.slice(0, 4).map((d) => (
                <li key={d.id} className="truncate font-mono text-xs text-text-muted">
                  {d.filename}
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* What this project knows. Absent on desktop, and said so rather than shown
            empty — project memory is pgvector-only (backend/desktop/sidecar.py). */}
        <section aria-labelledby="memory" className="card">
          <h2 id="memory" className="mb-3 font-serif text-base font-bold text-text-primary">
            What this project knows
          </h2>
          {isDesktop ? (
            <p className="text-sm leading-relaxed text-text-secondary">
              Project memory needs a Postgres with pgvector, so it isn&apos;t part of the
              desktop app. Your reports and corpus are all here — only cross-report recall
              is missing.
            </p>
          ) : memory.isLoading ? (
            <div className="h-12 animate-pulse bg-bg-elevated" aria-hidden />
          ) : memory.isError || !memory.data ? (
            <p className="text-sm text-text-secondary">Couldn&apos;t read memory status.</p>
          ) : (
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-text-muted">Approved reports</dt>
                <dd className="font-mono tabular-nums text-text-primary">
                  {memory.data.approved_reports}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-text-muted">Indexed</dt>
                <dd className="font-mono tabular-nums text-text-primary">
                  {memory.data.indexed_reports}
                </dd>
              </div>
              {memory.data.pending_reports > 0 && (
                <p className="pt-1 text-xs leading-snug" style={{ color: "var(--warning)" }}>
                  {memory.data.pending_reports} approved report
                  {memory.data.pending_reports === 1 ? "" : "s"} not yet indexed — follow-ups
                  can&apos;t draw on them until they are.
                </p>
              )}
            </dl>
          )}
        </section>

        {/* Agents. The same truthful attribution the report carries, one level up. */}
        <section aria-labelledby="agents" className="card lg:col-span-3">
          <div className="mb-3 flex items-baseline justify-between">
            <h2 id="agents" className="font-serif text-base font-bold text-text-primary">
              Agents this project runs on
            </h2>
            <Link href="/settings/models" className="font-mono text-xs text-accent hover:underline">
              Change →
            </Link>
          </div>
          {routing.isLoading ? (
            <div className="h-10 animate-pulse bg-bg-elevated" aria-hidden />
          ) : routing.data?.routing ? (
            <dl className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
              {Object.entries(routing.data.routing as Record<string, string>).map(([role, route]) => (
                <div key={role}>
                  <dt className="font-mono text-[0.6875rem] uppercase tracking-wider text-text-muted">
                    {role}
                  </dt>
                  <dd className="truncate font-mono text-xs text-text-primary" title={route}>
                    {route}
                  </dd>
                </div>
              ))}
            </dl>
          ) : (
            // Never a guessed default: an unresolved routing reads as unresolved.
            <p className="text-sm text-text-secondary">
              No model routing resolved yet — it is recorded per run, on the run.
            </p>
          )}
        </section>
      </div>
    </div>
  );
}
