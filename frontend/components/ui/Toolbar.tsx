import type { ReactNode } from "react";

/**
 * A card's title row: label (+ meta) on the left, actions on the right.
 * Lifted from LiveFeed's "Activity Log" header bar so any card needing the
 * same title/meta/actions row reuses it instead of one-off flex markup.
 */
export function Toolbar({
  title,
  meta,
  actions,
}: {
  title: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
      <div className="flex items-center gap-3">
        <h3 className="text-sm font-serif font-semibold text-text-primary">{title}</h3>
        {meta}
      </div>
      {actions}
    </div>
  );
}
