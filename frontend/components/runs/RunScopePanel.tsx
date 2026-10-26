import type { Run } from "@/lib/types";

/**
 * What a corpus run was allowed to read, and how its answer was checked (RFC V3.1 §5, §9.6).
 *
 * The file list is the frozen selection from the run's own record — never re-derived from
 * the corpus as it is now, which may have changed since. Grounding counts are shown as
 * recorded; a run with no record says nothing rather than implying zero.
 */
export function RunScopePanel({ run }: { run: Run }) {
  const files = run.corpus_selection?.resolved ?? [];
  const grounding = run.grounding_report;
  if (!run.corpus_mode && !run.offline) return null;
  return (
    <section aria-labelledby="run-scope" className="border-t border-border pt-3">
      <p
        id="run-scope"
        className="mb-2 font-mono text-[length:var(--text-micro)] font-semibold uppercase tracking-wider text-text-muted"
      >
        Files used
      </p>
      <div className="mb-2 flex flex-wrap gap-2 text-xs">
        {run.corpus_mode && (
          <span className="badge border-border">Only selected files</span>
        )}
        {run.offline && <span className="badge border-border">Offline</span>}
      </div>
      {files.length > 0 ? (
        <details>
          <summary className="cursor-pointer text-xs text-text-secondary">
            {files.length} file{files.length === 1 ? "" : "s"}
            {run.corpus_selection?.corpus_version != null
              ? ` · corpus version ${run.corpus_selection.corpus_version}`
              : ""}
          </summary>
          <ul className="mt-1 space-y-0.5 font-mono text-[length:var(--text-micro)] text-text-secondary">
            {files.map((f) => (
              <li key={f.document_id}>
                {f.path || f.filename} <span className="text-text-muted">v{f.version}</span>
              </li>
            ))}
          </ul>
        </details>
      ) : (
        <p className="text-xs text-text-muted">
          Created before file selections existed: the project&apos;s whole corpus.
        </p>
      )}
      {grounding && (
        <p className="mt-2 text-xs text-text-secondary">
          {grounding.status === "complete"
            ? `Every claim checked against these files: ${grounding.claims_supported ?? 0} supported, ${grounding.claims_rejected ?? 0} kept out of the answer, ${grounding.units_dropped ?? 0} passage(s) removed.`
            : grounding.status === "no_evidence"
              ? "These files don't answer the question. Nothing was answered from outside them."
              : `${grounding.claims_unmeasured ?? 0} claim(s) could not be checked, so the report was not offered for approval.`}
        </p>
      )}
    </section>
  );
}
