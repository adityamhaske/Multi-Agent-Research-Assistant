import type { ReactNode } from "react";

/**
 * The "nothing here yet" card: a title, a short description, and an optional
 * action — icon slot is opt-in. Replaces the ad-hoc `◇` glyph that stood in
 * for an icon in the corpus and research empty states (docs/07 §2): a glyph
 * with no meaning is decoration, so the default is no icon at all rather
 * than a placeholder shape.
 */
export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="card flex flex-col items-center py-10 text-center">
      {icon && (
        <span aria-hidden className="mb-2 text-text-muted opacity-60">
          {icon}
        </span>
      )}
      <p className="text-sm font-medium text-text-primary">{title}</p>
      {description && <p className="mt-0.5 text-xs text-text-muted">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
