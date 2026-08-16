import type { ReactNode } from "react";

export type StatusTone = "success" | "warning" | "danger" | "info" | "muted";

const TONE_COLOR: Record<StatusTone, string> = {
  success: "var(--success)",
  warning: "var(--warning)",
  danger: "var(--danger)",
  info: "var(--info)",
  muted: "var(--text-muted)",
};

/**
 * A colored marker plus its label, always together (docs/07 §2, "Honest
 * three-state status" / "Agent hue as reinforcement") — color is never the
 * only signal. Wraps the `.badge` + `.status-marker` combination that was
 * being hand-assembled per call site (LiveFeed's connection pill, the
 * settings API-key status row, …).
 */
export function StatusDot({ tone, children }: { tone: StatusTone; children: ReactNode }) {
  return (
    <span className="badge font-mono text-[length:var(--text-micro)] text-text-muted border-border">
      <span aria-hidden className="status-marker" style={{ backgroundColor: TONE_COLOR[tone] }} />
      {children}
    </span>
  );
}
