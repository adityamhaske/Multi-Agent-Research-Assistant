import type { SessionStatus } from "@/lib/types";

/** Status → token name + human label. Colors flow from tokens only (docs/07 §1). */
const CONFIG: Record<SessionStatus, { token: string; label: string; pulse?: boolean }> = {
  PENDING: { token: "text-muted", label: "Queued" },
  RUNNING: { token: "info", label: "Running", pulse: true },
  AWAITING_APPROVAL: { token: "warning", label: "Needs review" },
  COMPLETED: { token: "success", label: "Completed" },
  FAILED: { token: "danger", label: "Failed" },
};

export function StatusBadge({ status }: { status: SessionStatus }) {
  const { token, label, pulse } = CONFIG[status] ?? CONFIG.PENDING;
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
