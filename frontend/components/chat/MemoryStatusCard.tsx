"use client";

import { useMemoryStatus } from "@/hooks/queries";

/**
 * What this project remembers (docs/14 §8).
 *
 * Memory is invisible by nature — a user cannot tell the difference between "chat has
 * nothing on that" and "ingestion has been silently failing for a week". This card is
 * the difference. It states the two ways memory can be incomplete rather than waiting
 * for the user to infer them from bad answers.
 */
export function MemoryStatusCard({ projectId }: { projectId: string | undefined }) {
  const { data, isLoading } = useMemoryStatus(projectId);

  if (isLoading || !data) return null;

  if (!data.available) {
    return (
      <div className="border border-warning-line bg-warning-soft p-4 text-sm text-text-primary">
        <div className="flex items-center gap-2 font-semibold text-warning">
          <span className="h-2 w-2 rounded-full bg-warning" aria-hidden />
          <h3>Project memory is offline</h3>
        </div>
        <p className="mt-1.5 leading-relaxed text-text-secondary">
          No embedding provider is configured, so chat cannot read this project&rsquo;s
          research. Install Ollama and run{" "}
          <code className="border border-border bg-bg-surface px-1.5 py-0.5 font-mono text-xs">
            ollama pull nomic-embed-text
          </code>
          , or set <code className="border border-border bg-bg-surface px-1.5 py-0.5 font-mono text-xs">EMBEDDINGS_PROVIDER</code>{" "}
          with that provider&rsquo;s key.
        </p>
      </div>
    );
  }

  const isFullyIndexed = data.indexed_reports > 0 && data.pending_reports === 0;

  return (
    <div className="card border border-border bg-bg-surface p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/60 pb-3">
        <div className="flex items-center gap-2">
          <span
            className={`h-2.5 w-2.5 rounded-full ${
              isFullyIndexed
                ? "bg-success"
                : data.pending_reports > 0
                  ? "bg-warning"
                  : "bg-text-muted"
            }`}
            aria-hidden
          />
          <h3 className="font-serif text-sm font-bold text-text-primary">Project Memory</h3>
          <span className="font-mono text-[length:var(--text-micro)] text-text-muted">
            · Grounded retrieval
          </span>
        </div>
        {data.current_model && (
          <span className="border border-border bg-bg-elevated px-2 py-0.5 font-mono text-xs font-medium text-accent">
            {data.current_model}
          </span>
        )}
      </div>

      <div className="mt-3.5 grid grid-cols-2 gap-3 sm:grid-cols-3">
        <div className="border border-border/60 bg-bg-elevated/40 p-2.5">
          <div className="font-mono text-[length:var(--text-micro)] uppercase tracking-wider text-text-muted">
            Indexed Reports
          </div>
          <div className="mt-1 font-mono text-lg font-semibold tabular-nums text-text-primary">
            {data.indexed_reports}
          </div>
        </div>

        <div className="border border-border/60 bg-bg-elevated/40 p-2.5">
          <div className="font-mono text-[length:var(--text-micro)] uppercase tracking-wider text-text-muted">
            Excerpts / Chunks
          </div>
          <div className="mt-1 font-mono text-lg font-semibold tabular-nums text-text-primary">
            {data.chunk_count}
          </div>
        </div>

        <div className="col-span-2 border border-border/60 bg-bg-elevated/40 p-2.5 sm:col-span-1">
          <div className="font-mono text-[length:var(--text-micro)] uppercase tracking-wider text-text-muted">
            Memory Status
          </div>
          <div className="mt-1 font-mono text-xs font-medium">
            {data.approved_reports === 0 ? (
              <span className="text-text-muted">No approved reports</span>
            ) : isFullyIndexed ? (
              <span className="text-success">Ready & Citable</span>
            ) : (
              <span className="text-warning">Indexing Pending</span>
            )}
          </div>
        </div>
      </div>

      {data.pending_reports > 0 && (
        <div className="mt-3 border border-warning-line bg-warning-soft p-3 text-xs leading-relaxed text-warning">
          <p className="font-semibold">
            {data.pending_reports} approved{" "}
            {data.pending_reports === 1 ? "report is" : "reports are"} pending index
          </p>
          <p className="mt-0.5 text-text-secondary">
            Chat cannot cite {data.pending_reports === 1 ? "it" : "them"} until indexed. This usually means the embedding provider was offline when research completed.
          </p>
        </div>
      )}

      {data.stale_models.length > 0 && (
        <div className="mt-3 border border-warning-line bg-warning-soft p-3 text-xs leading-relaxed text-warning">
          <p className="font-semibold">Embedding model mismatch</p>
          <p className="mt-0.5 text-text-secondary">
            Some excerpts were embedded with {data.stale_models.join(", ")} and are invisible to the current model. A re-index is needed to bring them back.
          </p>
        </div>
      )}

      {data.approved_reports === 0 && (
        <p className="mt-3 text-xs leading-relaxed text-text-muted">
          No reports have been approved in this project yet. Reports you approve automatically enter memory so chat answers can cite verified claims.
        </p>
      )}
    </div>
  );
}
