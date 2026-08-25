"use client";

import Link from "next/link";

import { useCorpusStatus, useMemoryStatus } from "@/hooks/queries";
import { isDesktop } from "@/lib/desktop";
import { formatCost } from "@/lib/format";
import type { V2RunSummary } from "@/lib/types";

/**
 * Three compact, honest questions about this project, side by side: what does it know,
 * what can it draw on, and what has that cost. One bordered strip (`.academic-grid`'s 1px
 * hairlines between cells) rather than three separate `.card` boxes — the old page's six
 * independent cards were the "stack of large repetitive cards" problem this page exists to
 * fix, and three cards that always say something short do not need three borders each.
 *
 * **Corpus and project memory are kept as distinct concepts, on purpose.** A corpus
 * document is embedded synchronously at upload (`app/(app)/corpus/page.tsx`) — there is no
 * "still indexing" state for a document once it is listed. What *can* be silently
 * incomplete is project **memory**: an approved report that failed to embed
 * (`pending_reports`), or one embedded under an embedding model that is no longer current
 * (`stale_models`). Labelling both "indexing" would blur a corpus problem (go to Corpus,
 * re-upload) with a memory problem (nothing to do there — it is the report that needs
 * re-indexing), which is exactly the kind of imprecise warning this section exists to
 * avoid.
 *
 * Every cell owns an explicit unmeasured branch. `runs` is `undefined` rather than `[]`
 * when the run list has not answered, because `[].reduce` produces a perfectly plausible
 * `$0.00` that is not a measurement of anything — the failure mode AGENTS.md calls a P0.
 */
export function ProjectHealth({
  projectId,
  runs,
  runsLoading,
  runsError,
}: {
  projectId: string;
  /** `undefined` until the run list has actually answered. Never defaulted to `[]` here. */
  runs: V2RunSummary[] | undefined;
  runsLoading: boolean;
  runsError: boolean;
}) {
  const memory = useMemoryStatus(isDesktop ? undefined : projectId);
  const corpus = useCorpusStatus(projectId);

  const spend = runs?.reduce((total, r) => total + (r.cost_usd || 0), 0) ?? 0;

  return (
    <section aria-labelledby="project-health" className="space-y-4">
      <div className="flex items-center justify-between border-b border-border pb-3">
        <h2
          id="project-health"
          className="font-serif text-xl font-bold tracking-tight text-text-primary"
        >
          Project health
        </h2>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {/* Card 1: Project memory */}
        <div className="card flex flex-col justify-between space-y-3 p-4">
          <div>
            <div className="flex items-center justify-between border-b border-border/40 pb-2 mb-3">
              <div className="flex items-center gap-2">
                <svg
                  aria-hidden
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="h-4 w-4 text-accent"
                >
                  <path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
                </svg>
                <h3 className="text-sm font-bold text-text-primary">Project memory</h3>
              </div>
              <Link href="/chat" className="font-mono text-xs font-semibold text-accent hover:underline">
                Chat →
              </Link>
            </div>

            {isDesktop ? (
              <p className="text-xs leading-relaxed text-text-secondary">
                Needs Postgres with pgvector, so it isn&apos;t part of the desktop app. Your
                reports and corpus are all here — only cross-report recall is missing.
              </p>
            ) : memory.isLoading ? (
              <div className="h-12 animate-pulse bg-bg-elevated" aria-hidden />
            ) : memory.isError || !memory.data ? (
              <p className="text-xs text-text-secondary">Couldn&apos;t read memory status.</p>
            ) : !memory.data.available ? (
              <p className="text-xs leading-relaxed text-text-secondary">
                No embedding model is configured, so nothing can be indexed into memory.{" "}
                <Link href="/settings/models" className="font-semibold text-accent hover:underline">
                  Configure one
                </Link>
                .
              </p>
            ) : (
              <div className="space-y-3">
                <dl className="grid grid-cols-2 gap-2 bg-bg-elevated p-2.5">
                  <div>
                    <dt className="font-mono text-[length:var(--text-micro)] uppercase tracking-wider text-text-muted">
                      Approved
                    </dt>
                    <dd className="mt-0.5 font-mono text-xl font-bold text-text-primary">
                      {memory.data.approved_reports}
                    </dd>
                  </div>
                  <div>
                    <dt className="font-mono text-[length:var(--text-micro)] uppercase tracking-wider text-text-muted">
                      Indexed
                    </dt>
                    <dd className="mt-0.5 font-mono text-xl font-bold text-text-primary">
                      {memory.data.indexed_reports}
                    </dd>
                  </div>
                </dl>

                <p className="text-xs leading-relaxed text-text-muted">
                  Built from approved legacy sessions; research runs are not indexed into it.
                </p>

                {memory.data.pending_reports > 0 && (
                  <p className="border border-warning-line bg-warning-soft p-2 text-xs leading-snug text-warning">
                    {memory.data.pending_reports} approved report
                    {memory.data.pending_reports === 1 ? "" : "s"} not indexed — follow-up
                    chat can&apos;t draw on{" "}
                    {memory.data.pending_reports === 1 ? "it" : "them"} yet.
                  </p>
                )}

                {memory.data.stale_models.length > 0 && (
                  <p className="border border-warning-line bg-warning-soft p-2 text-xs leading-snug text-warning">
                    Some excerpts were embedded with a model this project no longer uses and
                    are invisible to it now — a re-index would bring them back.
                  </p>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Card 2: Corpus */}
        <div className="card flex flex-col justify-between space-y-3 p-4">
          <div>
            <div className="flex items-center justify-between border-b border-border/40 pb-2 mb-3">
              <div className="flex items-center gap-2">
                <svg
                  aria-hidden
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="h-4 w-4 text-accent"
                >
                  <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z" />
                  <path d="M6 6h10M6 10h10" />
                </svg>
                <h3 className="text-sm font-bold text-text-primary">Corpus</h3>
              </div>
              <Link href="/corpus" className="font-mono text-xs font-semibold text-accent hover:underline">
                Manage →
              </Link>
            </div>

            {corpus.isLoading ? (
              <div className="h-12 animate-pulse bg-bg-elevated" aria-hidden />
            ) : corpus.isError ? (
              <p className="text-xs text-text-secondary">Couldn&apos;t read the corpus.</p>
            ) : corpus.data && corpus.data.documents > 0 ? (
              <div className="space-y-3">
                <dl className="grid grid-cols-2 gap-2 bg-bg-elevated p-2.5">
                  <div>
                    <dt className="font-mono text-[length:var(--text-micro)] uppercase tracking-wider text-text-muted">
                      Documents
                    </dt>
                    <dd className="mt-0.5 font-mono text-xl font-bold text-text-primary">
                      {corpus.data.documents}
                    </dd>
                  </div>
                  <div>
                    <dt className="font-mono text-[length:var(--text-micro)] uppercase tracking-wider text-text-muted">
                      Chunks
                    </dt>
                    <dd className="mt-0.5 font-mono text-xl font-bold text-text-primary">
                      {corpus.data.chunks}
                    </dd>
                  </div>
                </dl>
                <p className="text-xs leading-relaxed text-text-muted">
                  Embedded source literature available for grounded retrieval.
                </p>
              </div>
            ) : (
              <div className="space-y-2 bg-bg-elevated/40 p-3">
                <p className="text-xs leading-relaxed text-text-secondary">
                  No documents yet.{" "}
                  <Link href="/corpus" className="font-semibold text-accent hover:underline">
                    Upload some
                  </Link>{" "}
                  to restrict a run to this project&apos;s own material.
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Card 3: Recent runs */}
        <div className="card flex flex-col justify-between space-y-3 p-4">
          <div>
            <div className="flex items-center justify-between border-b border-border/40 pb-2 mb-3">
              <div className="flex items-center gap-2">
                <svg
                  aria-hidden
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="h-4 w-4 text-accent"
                >
                  <circle cx="12" cy="12" r="10" />
                  <polyline points="12 6 12 12 16 14" />
                </svg>
                <h3 className="text-sm font-bold text-text-primary">Recent runs</h3>
              </div>
              <Link href="/history" className="font-mono text-xs font-semibold text-accent hover:underline">
                History →
              </Link>
            </div>

            {runsLoading ? (
              <div className="h-12 animate-pulse bg-bg-elevated" aria-hidden />
            ) : runsError || runs === undefined ? (
              <p className="text-xs text-text-secondary">Couldn&apos;t read recent runs.</p>
            ) : (
              <div className="space-y-3">
                <dl className="grid grid-cols-2 gap-2 bg-bg-elevated p-2.5">
                  <div>
                    <dt className="font-mono text-[length:var(--text-micro)] uppercase tracking-wider text-text-muted">
                      Runs
                    </dt>
                    <dd className="mt-0.5 font-mono text-xl font-bold text-text-primary">
                      {runs.length}
                    </dd>
                  </div>
                  <div>
                    <dt className="font-mono text-[length:var(--text-micro)] uppercase tracking-wider text-text-muted">
                      Cost
                    </dt>
                    <dd className="mt-0.5 font-mono text-xl font-bold text-text-primary">
                      {formatCost(spend)}
                    </dd>
                  </div>
                </dl>
                <p className="text-xs leading-relaxed text-text-muted">
                  Across the {runs.length} most recent research run
                  {runs.length === 1 ? "" : "s"} — not a project total, and not counting
                  legacy sessions.
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
