import { routeModelLabel } from "@/lib/pipeline";

/**
 * "Models used" — the per-role provider:model breakdown (docs/07 §2, "truthful
 * per-agent model attribution", requirement 1: disclosure "in the report/export").
 * Mirrors the same section `research_engine/bundle.py`'s `render_model_attribution_md`
 * and `app/services/export.py`'s `_models_html` append to a downloaded `.md`/`.pdf`, so
 * what a reader sees on screen and what they download agree. Renders nothing when
 * routing was never resolved — a run that failed before the planner, or a session that
 * predates this field — never a guessed default (the unmeasured-vs-zero rule).
 */
export function ModelAttribution({
  modelRouting,
}: {
  modelRouting: Record<string, string> | null | undefined;
}) {
  const roles = modelRouting ? Object.keys(modelRouting).sort() : [];
  if (roles.length === 0) return null;

  return (
    <div className="border-y border-border py-3">
      <h2 className="font-mono text-[0.6875rem] font-semibold uppercase tracking-wider text-text-muted">
        Models used
      </h2>
      <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1.5 sm:grid-cols-3">
        {roles.map((role) => (
          <div key={role} className="flex items-baseline gap-2 min-w-0">
            <dt className="shrink-0 text-xs font-medium capitalize text-text-secondary">{role}</dt>
            <dd
              className="min-w-0 truncate font-mono text-xs text-text-muted"
              title={modelRouting?.[role]}
            >
              {routeModelLabel(modelRouting?.[role])}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
