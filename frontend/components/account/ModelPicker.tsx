"use client";

import { useMemo, useState } from "react";
import toast from "react-hot-toast";

import {
  useCustomEndpointStatus,
  useModelCatalog,
  useResetModelRouting,
  useSetModelRouting,
} from "@/hooks/queries";
import type { AgentRole, ModelInfo, ModelRouting } from "@/lib/types";

import { Section } from "./Section";

/**
 * Per-role model selection (docs/12 M8).
 *
 * Presets are the front door and the per-role drawer sits behind "Customize", because
 * the useful default is one click and only a minority of users want five dropdowns.
 *
 * The framing is deliberate: routing different roles to different models is a *quality*
 * decision, not just a flexibility toggle. The executor runs many tool-calling rounds and
 * wants speed and breadth; the synthesizer writes the artifact the user actually reads and
 * wants the strongest model available. The copy says so, because a picker that only offers
 * knobs teaches nothing.
 */

const ROLE_COPY: Record<AgentRole, { label: string; blurb: string }> = {
  planner: { label: "Planner", blurb: "Breaks your question into research tasks." },
  executor: { label: "Executor", blurb: "Runs the searches and gathers evidence." },
  critic: { label: "Critic", blurb: "Grades that evidence and sends weak work back." },
  synthesizer: { label: "Synthesizer", blurb: "Writes the cited report you read." },
  chat: { label: "Follow-up chat", blurb: "Answers questions about a finished report." },
};

const PRESET_COPY: Record<string, string> = {
  fast: "Cheapest and quickest. Good for scoping a question.",
  balanced: "A strong model where it shows, a fast one where it doesn't.",
  best: "Highest quality, highest cost.",
};

const PROVIDER_NAMES: Record<string, string> = {
  custom: "Custom Endpoint (OpenAI-compatible)",
  google: "Google Gemini",
  anthropic: "Anthropic Claude",
  openai: "OpenAI",
  openrouter: "OpenRouter",
  ollama: "Local (Ollama)",
};

function formatPrice(model: ModelInfo): string {
  if (model.provider === "custom") return "custom endpoint";
  if (model.input_per_mtok === null || model.output_per_mtok === null) return "price not set";
  if (model.input_per_mtok === 0 && model.output_per_mtok === 0) return "free — runs locally";
  return `$${model.input_per_mtok}/$${model.output_per_mtok} per 1M`;
}

/** Rough per-run cost signal so "best" vs "fast" is a number, not a vibe. */
function relativeCost(routing: ModelRouting, byRoute: Map<string, ModelInfo>): number {
  return Object.values(routing).reduce((sum, route) => {
    const m = byRoute.get(route);
    return sum + (m?.output_per_mtok ?? 0);
  }, 0);
}

export function ModelPicker() {
  const { data: catalog, isLoading } = useModelCatalog();
  const customStatus = useCustomEndpointStatus();
  const setRouting = useSetModelRouting();
  const resetRouting = useResetModelRouting();

  const [customizing, setCustomizing] = useState(false);
  const [draft, setDraft] = useState<ModelRouting | null>(null);

  const current = draft ?? catalog?.effective_routing ?? null;

  const customModels = useMemo(() => {
    const models = customStatus.data?.models ?? [];
    const reachable = Boolean(customStatus.data?.reachable);
    const list: ModelInfo[] = models.map((m) => ({
      route: `custom:${m}`,
      provider: "custom",
      model_id: m,
      display_name: m,
      input_per_mtok: null,
      output_per_mtok: null,
      context_window: null,
      max_output_tokens: null,
      supports_tools: true,
      supports_structured_output: true,
      notes: "Served by your configured custom OpenAI-compatible endpoint.",
      available: reachable,
    }));

    // Ensure any currently active custom: route is present even if unadvertised
    if (current) {
      for (const route of Object.values(current)) {
        if (route.startsWith("custom:") && !list.some((m) => m.route === route)) {
          const id = route.slice("custom:".length);
          list.push({
            route,
            provider: "custom",
            model_id: id,
            display_name: id,
            input_per_mtok: null,
            output_per_mtok: null,
            context_window: null,
            max_output_tokens: null,
            supports_tools: true,
            supports_structured_output: true,
            notes: "Served by your configured custom OpenAI-compatible endpoint.",
            available: reachable,
          });
        }
      }
    }

    return list;
  }, [customStatus.data, current]);

  const allModels = useMemo(
    () => [...customModels, ...(catalog?.models ?? [])],
    [customModels, catalog?.models],
  );

  const byRoute = useMemo(
    () => new Map(allModels.map((m) => [m.route, m])),
    [allModels],
  );

  const groupedModels = useMemo(() => {
    const groups: Record<string, ModelInfo[]> = {};
    for (const m of allModels) {
      const p = m.provider;
      if (!groups[p]) groups[p] = [];
      groups[p].push(m);
    }
    return groups;
  }, [allModels]);

  if (isLoading || !catalog || !current) {
    return (
      <Section title="Models" description="Choose which model runs each stage of the pipeline.">
        <div className="h-24 animate-pulse border border-border bg-bg-surface" />
      </Section>
    );
  }

  // Only offer presets for providers the user can actually reach right now.
  const presetProviders = Object.keys(catalog.presets).filter((p) =>
    catalog.available_providers.includes(p),
  );

  const matchesPreset = (provider: string, name: string) =>
    JSON.stringify(catalog.presets[provider]?.[name]) === JSON.stringify(current);

  async function applyRouting(next: ModelRouting) {
    setDraft(next);
    try {
      await setRouting.mutateAsync(next);
      toast.success("Models updated. Applies to your next research run.");
    } catch (e) {
      setDraft(null);
      toast.error(e instanceof Error ? e.message : "Could not save model selection.");
    }
  }

  async function useDeploymentDefault() {
    setDraft(null);
    try {
      await resetRouting.mutateAsync();
      toast.success("Back to this deployment's default models.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not reset.");
    }
  }

  const busy = setRouting.isPending || resetRouting.isPending;

  return (
    <Section
      title="Models"
      description="Each stage of the pipeline can run on a different model. Cheap and fast where the work is mechanical, strongest where it writes what you read."
      footer={
        <>
          <span className="text-xs text-text-muted">
            {catalog.user_routing
              ? "Using your selection."
              : "Using this deployment's default models."}
          </span>
          <div className="flex items-center gap-2">
            {catalog.user_routing && (
              <button
                type="button"
                onClick={useDeploymentDefault}
                disabled={busy}
                className="btn btn-ghost"
              >
                Use defaults
              </button>
            )}
            <button
              type="button"
              onClick={() => setCustomizing((v) => !v)}
              className="btn btn-ghost"
              aria-expanded={customizing}
            >
              {customizing ? "Hide roles" : "Customize"}
            </button>
          </div>
        </>
      }
    >
      {/* Presets */}
      {presetProviders.length === 0 ? (
        <p className="border border-border bg-bg-surface px-4 py-3 font-mono text-xs text-text-secondary">
          No provider is configured yet. Add an API key above, or run a local model with
          Ollama, and presets will appear here.
        </p>
      ) : (
        presetProviders.map((provider) => (
          <div key={provider} className="mb-5 last:mb-0">
            <div className="mb-2 font-mono text-xs font-semibold uppercase tracking-wider text-text-muted">
              {provider}
            </div>
            <div className="grid gap-2 sm:grid-cols-3">
              {catalog.preset_names.map((name) => {
                const mapping = catalog.presets[provider]?.[name];
                if (!mapping) return null;
                const active = matchesPreset(provider, name);
                return (
                  <button
                    key={`${provider}-${name}`}
                    type="button"
                    disabled={busy}
                    onClick={() => applyRouting(mapping)}
                    aria-pressed={active}
                    className="border px-3.5 py-3 text-left transition-colors disabled:opacity-60"
                    style={{
                      borderColor: active ? "var(--accent)" : "var(--border)",
                      backgroundColor: active
                        ? "var(--accent-muted)"
                        : "var(--bg-surface)",
                    }}
                  >
                    <div className="font-serif text-sm font-bold capitalize text-text-primary">
                      {name}
                    </div>
                    <div className="mt-0.5 text-xs leading-relaxed text-text-muted">
                      {PRESET_COPY[name] ?? ""}
                    </div>
                    <div className="mt-1.5 font-mono text-[0.6875rem] text-text-muted">
                      {relativeCost(mapping, byRoute) === 0
                        ? "free"
                        : `~$${relativeCost(mapping, byRoute).toFixed(2)} / 1M out`}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        ))
      )}

      {/* Per-role drawer */}
      {customizing && (
        <div className="mt-5 space-y-3 border-t border-border pt-5">
          {catalog.roles.map((role) => {
            const selected = byRoute.get(current[role]);
            return (
              <div
                key={role}
                className="grid items-center gap-2 sm:grid-cols-[14rem_1fr]"
              >
                <div className="min-w-0">
                  <div className="text-[0.8125rem] font-medium text-text-secondary">
                    {ROLE_COPY[role].label}
                  </div>
                  <div className="text-xs leading-relaxed text-text-muted">
                    {ROLE_COPY[role].blurb}
                  </div>
                </div>
                <div>
                  <select
                    id={`model-${role}`}
                    aria-label={`Model for ${ROLE_COPY[role].label}`}
                    className="input-base w-full"
                    value={current[role]}
                    disabled={busy}
                    onChange={(e) => applyRouting({ ...current, [role]: e.target.value })}
                  >
                    {Object.entries(groupedModels).map(([providerKey, models]) => (
                      <optgroup
                        key={providerKey}
                        label={PROVIDER_NAMES[providerKey] ?? providerKey}
                      >
                        {models.map((m) => (
                          <option
                            key={m.route}
                            value={m.route}
                            // Unavailable models stay visible but unselectable: seeing the
                            // option is what tells you adding a key is worth it.
                            disabled={
                              !m.available ||
                              (m.provider !== "custom" && m.input_per_mtok === null)
                            }
                          >
                            {m.display_name} — {formatPrice(m)}
                            {m.available ? "" : " (needs a key)"}
                          </option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                  {selected?.notes && (
                    <p className="mt-1 text-xs leading-relaxed text-text-muted">
                      {selected.notes}
                    </p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Section>
  );
}
