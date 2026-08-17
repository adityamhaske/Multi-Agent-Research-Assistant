"use client";

import { useOutlineTemplates } from "@/hooks/queries";
import type { OutlineSection } from "@/lib/types";

/**
 * Pick a report structure at the design gate (docs/07 §2, Phase 4).
 *
 * The four templates — Literature Review, Systematic Comparison, Methods Survey, Custom
 * — are **not defined here**. They come from `GET /research/outline-templates`, which
 * serves `research_engine/outlines.py`, so the sections previewed below are the same
 * objects the synthesizer is handed. A copy in TypeScript would be a second home for one
 * contract, and the drift would be silent: the picker would promise a structure the
 * report never used.
 *
 * Choosing a template *replaces* the current section list rather than merging into it.
 * Merging would make "pick a different template" produce something that is neither, and
 * the sections stay editable afterwards — the template is a starting point, not a lock.
 */
export function OutlineTemplatePicker({
  sections,
  onChange,
  disabled,
}: {
  sections: OutlineSection[];
  onChange: (sections: OutlineSection[]) => void;
  disabled?: boolean;
}) {
  const templates = useOutlineTemplates();

  // Which template the current sections match, if any. Derived by comparing titles
  // rather than stored, so editing a section away from its template stops claiming that
  // template — the selection always describes what is actually there.
  const activeId = templates.data?.find(
    (t) =>
      t.sections.length === sections.length &&
      t.sections.every((s, i) => s.title === sections[i]?.title),
  )?.id;

  if (templates.isLoading) {
    return (
      <div className="grid gap-2 sm:grid-cols-2" aria-hidden>
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-16 animate-pulse bg-bg-elevated" />
        ))}
      </div>
    );
  }

  if (templates.isError || !templates.data) {
    // Not fatal: the outline is optional and the sections below are still editable by
    // hand. Say what is missing rather than rendering four buttons that do nothing.
    return (
      <p className="text-xs text-text-muted">
        Couldn&apos;t load the report templates. You can still write sections by hand below.
      </p>
    );
  }

  return (
    <div role="radiogroup" aria-label="Report structure" className="grid gap-2 sm:grid-cols-2">
      {templates.data.map((template) => {
        const selected = template.id === activeId;
        return (
          <button
            key={template.id}
            type="button"
            role="radio"
            aria-checked={selected}
            disabled={disabled}
            onClick={() => onChange(template.sections.map((s) => ({ ...s })))}
            className="border p-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50"
            style={{
              borderColor: selected ? "var(--accent)" : "var(--border)",
              backgroundColor: selected
                ? "color-mix(in srgb, var(--accent) 8%, var(--bg-surface))"
                : "var(--bg-surface)",
            }}
          >
            <span
              className="block font-mono text-xs font-semibold uppercase tracking-wider"
              style={{ color: selected ? "var(--accent)" : "var(--text-primary)" }}
            >
              {template.label}
            </span>
            <span className="mt-1 block text-xs leading-relaxed text-text-muted">
              {template.summary}
            </span>
            {template.sections.length > 0 && (
              <span className="mt-1.5 block truncate font-mono text-[length:var(--text-micro)] text-text-muted">
                {template.sections.map((s) => s.title).join(" → ")}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
