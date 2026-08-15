/**
 * Marks a session as produced by scripted models rather than real research (docs/17 §6.2).
 *
 * Uses `--warning` rather than the accent or a muted grey. A demo is not a neutral
 * attribute like depth or cost — it is the one fact that invalidates everything else on
 * the card, so it has to read as a caution at a glance and survive being scanned past.
 *
 * `title` carries the full sentence because the badge itself is two words, and two words
 * cannot carry "none of this was researched".
 */
export function DemoBadge({ className = "" }: { className?: string }) {
  const c = "var(--warning)";
  return (
    <span
      className={`badge font-mono text-[0.6875rem] font-semibold uppercase tracking-wider ${className}`}
      style={{
        color: c,
        backgroundColor: `color-mix(in srgb, ${c} 10%, var(--bg-surface))`,
        borderColor: `color-mix(in srgb, ${c} 35%, var(--border))`,
      }}
      title="Scripted models and fixture sources — nothing here was researched or verified."
    >
      Demo
    </span>
  );
}
