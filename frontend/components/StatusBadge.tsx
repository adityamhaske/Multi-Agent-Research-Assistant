import { statusMeta } from "@/lib/status";
import type { SessionStatus } from "@/lib/types";

/** Colours flow from tokens only (docs/07 §1); the label vocabulary lives in
 *  `lib/status.ts` so the badge and the history filters cannot disagree. */

export function StatusBadge({ status }: { status: SessionStatus }) {
  const { token, label, pulse } = statusMeta(status);
  const c = `var(--${token})`;
  return (
    <span
      className="badge font-mono text-[0.6875rem] font-semibold uppercase tracking-wider"
      style={{
        color: c,
        backgroundColor: `color-mix(in srgb, ${c} 10%, var(--bg-surface))`,
        borderColor: `color-mix(in srgb, ${c} 30%, var(--border))`,
      }}
    >
      <span
        className="status-marker"
        style={{
          backgroundColor: c,
          animation: pulse ? "pulse-ring 1.4s ease-in-out infinite" : undefined,
        }}
        aria-hidden
      />
      {label}
    </span>
  );
}
