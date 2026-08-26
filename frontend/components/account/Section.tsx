import type { ReactNode } from "react";

/**
 * The one section pattern used across Profile and Settings: a titled card with a
 * short description, optional footer for the action, and consistent rhythm.
 * Having a single primitive is what keeps the two pages feeling like one product
 * rather than two forms that happen to share a nav.
 */
export function Section({
  title,
  description,
  children,
  footer,
  tone = "default",
}: {
  title: string;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  tone?: "default" | "danger";
}) {
  return (
    <section
      className="border bg-bg-surface/90 shadow-xs backdrop-blur-sm overflow-hidden"
      style={{
        borderColor:
          tone === "danger"
            ? "color-mix(in srgb, var(--danger) 30%, var(--border))"
            : "var(--border)",
      }}
    >
      <div className="px-5 pt-5 sm:px-6 sm:pt-6 border-b border-border/40 pb-4">
        <h2
          className="font-serif text-[1.0625rem] font-bold tracking-tight"
          style={{ color: tone === "danger" ? "var(--danger)" : "var(--text-primary)" }}
        >
          {title}
        </h2>
        {description && (
          <p className="mt-1 max-w-2xl text-[0.8125rem] leading-relaxed text-text-muted">
            {description}
          </p>
        )}
      </div>

      <div className="px-5 py-5 sm:px-6">{children}</div>

      {footer && (
        <div className="flex items-center justify-between gap-3 border-t border-border/60 bg-bg-base/40 px-5 py-3.5 sm:px-6">
          {footer}
        </div>
      )}
    </section>
  );
}

/** Label + control + hint, in the proportions used throughout the account pages. */
export function Field({
  label,
  htmlFor,
  hint,
  children,
  className = "",
}: {
  label: string;
  htmlFor: string;
  hint?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <label
        htmlFor={htmlFor}
        className="mb-1.5 block text-[0.8125rem] font-medium text-text-secondary"
      >
        {label}
      </label>
      {children}
      {hint && <p className="mt-1.5 text-xs leading-relaxed text-text-muted">{hint}</p>}
    </div>
  );
}

/** Read-only key/value row — for facts the user can see but not edit. */
export function ReadOnlyRow({
  label,
  value,
  action,
}: {
  label: string;
  value: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-4 py-2.5">
      <div className="min-w-0">
        <div className="text-[0.8125rem] font-medium text-text-secondary">{label}</div>
        <div className="mt-0.5 truncate text-sm text-text-primary">{value}</div>
      </div>
      {action}
    </div>
  );
}

