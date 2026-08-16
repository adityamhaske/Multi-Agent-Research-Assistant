import type { ReactNode } from "react";

/**
 * Label + control + hint, in the proportions used throughout the account
 * pages (`account/Section.tsx`'s original `Field`). Canonical home moved to
 * `components/ui` so surfaces outside the account pages — Phase 3's settings
 * IA, Phase 4's plan gate — have one place to import it from.
 */
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
