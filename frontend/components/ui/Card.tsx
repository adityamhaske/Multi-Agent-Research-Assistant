import type { ReactNode } from "react";

export type CardTone = "default" | "danger" | "warning";
export type CardPadding = "sm" | "md" | "lg";

const TONE_BORDER: Record<CardTone, string> = {
  default: "var(--border)",
  danger: "color-mix(in srgb, var(--danger) 30%, var(--border))",
  warning: "color-mix(in srgb, var(--warning) 30%, var(--border))",
};

const TONE_TITLE: Record<CardTone, string> = {
  default: "var(--text-primary)",
  danger: "var(--danger)",
  warning: "var(--warning)",
};

const PAD: Record<CardPadding, string> = {
  sm: "var(--space-sm)",
  md: "var(--space-md)",
  lg: "var(--space-lg)",
};

/**
 * The one bordered-surface primitive (docs/07 §2). Every hand-rolled
 * `border border-border bg-bg-surface p-*` box in the app is this component
 * with a `padding` step and no header; every titled card (the pattern
 * `account/Section` established) is this component with `title` set. New
 * surfaces should reach for this instead of re-deriving the box.
 */
export function Card({
  title,
  description,
  footer,
  tone = "default",
  padding = "lg",
  className = "",
  children,
}: {
  title?: ReactNode;
  description?: ReactNode;
  footer?: ReactNode;
  tone?: CardTone;
  padding?: CardPadding;
  className?: string;
  children: ReactNode;
}) {
  const pad = PAD[padding];
  const hasHeader = Boolean(title || description);

  return (
    <section
      className={`border bg-bg-surface ${className}`}
      style={{ borderColor: TONE_BORDER[tone] }}
    >
      {hasHeader && (
        <div style={{ padding: pad, paddingBottom: 0 }}>
          {title && (
            <h2
              className="font-serif text-[1rem] font-bold tracking-tight"
              style={{ color: TONE_TITLE[tone] }}
            >
              {title}
            </h2>
          )}
          {description && (
            <p className="mt-1 max-w-2xl text-sm leading-relaxed text-text-muted">
              {description}
            </p>
          )}
        </div>
      )}
      <div style={{ padding: pad }}>{children}</div>
      {footer && (
        <div
          className="flex items-center justify-between gap-3 border-t border-border bg-bg-base/50"
          style={{ padding: `var(--space-sm) ${pad}` }}
        >
          {footer}
        </div>
      )}
    </section>
  );
}
