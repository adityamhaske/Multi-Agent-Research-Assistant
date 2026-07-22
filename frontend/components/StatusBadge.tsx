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
      className="badge"
      style={{
        color: c,
        backgroundColor: `color-mix(in srgb, ${c} 14%, transparent)`,
        borderColor: `color-mix(in srgb, ${c} 32%, transparent)`,
      }}
    >
      <span
        className={pulse ? "inline-block h-1.5 w-1.5 rounded-full" : "hidden"}
        style={pulse ? { backgroundColor: c, animation: "pulse-ring 1.4s ease-in-out infinite" } : undefined}
        aria-hidden
      />
      {label}
    </span>
  );
}
