/**
 * Marks a corpus document as an auto-saved report rather than an uploaded source
 * (app/services/report_corpus.py, docs/12 M10 follow-up).
 *
 * Same shape as `DemoBadge` and the same reasoning: this is not a neutral attribute like
 * file size or chunk count, it is the one fact that changes what the document *is* — a
 * generated document is never used as retrieval evidence (`research_engine/corpus.py`
 * excludes `origin='generated'` unconditionally), so a user scanning the Corpus page for
 * "what can this project's research cite" needs to see the distinction at a glance rather
 * than discover it by reading a report that cites nothing it uploaded.
 */
export function GeneratedBadge({ className = "" }: { className?: string }) {
  const c = "var(--warning)";
  return (
    <span
      className={`badge font-mono text-[0.6875rem] font-semibold uppercase tracking-wider ${className}`}
      style={{
        color: c,
        backgroundColor: `color-mix(in srgb, ${c} 10%, var(--bg-surface))`,
        borderColor: `color-mix(in srgb, ${c} 35%, var(--border))`,
      }}
      title="Auto-saved from an approved report in this project — never used as research evidence, unlike an uploaded document."
    >
      Generated
    </span>
  );
}
