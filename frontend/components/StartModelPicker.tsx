"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { useLocalLLMStatus, useModelCatalog } from "@/hooks/queries";
import type { ModelInfo, ModelRouting } from "@/lib/types";

/**
 * Per-run model choice on the start form (docs/12 M8/M15).
 *
 * Two steps, because "which model" is unanswerable until you have picked a *source*:
 * cloud models are a price/quality ladder gated on an API key, local models are free
 * but gated on a server that may not be running. Collapsing both into one long list
 * mixes those failure modes and buries the local option.
 *
 * Defaults to "your saved settings" so the common case stays one click — this control
 * is an override for a single run, not a second place to configure defaults. The
 * per-role picker lives in Settings; here one model fills every role, which is what
 * people actually want when they are choosing per run.
 */

const ROLES = ["planner", "executor", "critic", "synthesizer", "chat"] as const;

type Source = "default" | "cloud" | "local";

function routeToRouting(route: string): ModelRouting {
  return Object.fromEntries(ROLES.map((r) => [r, route])) as ModelRouting;
}

function priceLabel(m: ModelInfo) {
  if (m.provider === "ollama") return "free · local";
  if (m.input_per_mtok == null || m.output_per_mtok == null) return "price not set";
  return `$${m.input_per_mtok}/$${m.output_per_mtok} per 1M`;
}

export function StartModelPicker({
  value,
  onChange,
}: {
  value: ModelRouting | null;
  onChange: (routing: ModelRouting | null) => void;
}) {
  const { data: catalog } = useModelCatalog();
  const { data: local } = useLocalLLMStatus();
  const [source, setSource] = useState<Source>("default");

  const cloudModels = useMemo(
    () => (catalog?.models ?? []).filter((m) => m.provider !== "ollama" && m.available),
    [catalog]
  );

  // Models this deployment knows but cannot reach, because no key is configured for their
  // provider. These used to be filtered out silently, so a list of four Gemini entries
  // looked like the whole world — with nothing to suggest eight Anthropic models were one
  // API key away. Counted per provider and named, rather than hidden.
  const lockedProviders = useMemo(() => {
    const byProvider = new Map<string, number>();
    for (const m of catalog?.models ?? []) {
      if (m.provider === "ollama" || m.available) continue;
      byProvider.set(m.provider, (byProvider.get(m.provider) ?? 0) + 1);
    }
    return [...byProvider.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [catalog]);

  // Only models that can actually fill an agent role: an embedding model would fail
  // immediately, and a model the server doesn't have can't run at all.
  const localModels = useMemo(
    () => (local?.models ?? []).filter((m) => !m.is_embedding),
    [local]
  );

  const selectedRoute = value ? value.planner : "";

  const pick = (next: Source) => {
    setSource(next);
    if (next === "default") {
      onChange(null);
      return;
    }
    const first = next === "cloud" ? cloudModels[0]?.route : localModels[0]?.route;
    onChange(first ? routeToRouting(first) : null);
  };

  return (
    <div>
      <span className="mb-2 block font-mono text-[0.6875rem] uppercase tracking-wider text-text-muted">
        Model
      </span>

      {/* Step 1 — where the model runs. Same segmented shape and tinted-selection
          treatment as the Depth control on the form, so two adjacent choices of the same
          kind do not look like two different kinds of control. `text-white` was also
          wrong here: on a light accent it is legible, on the dark theme's mint accent it
          is not — the token pair exists precisely to survive both. */}
      <div className="inline-flex border border-border" role="radiogroup" aria-label="Model source">
        {(
          [
            { key: "default", label: "Use my settings" },
            { key: "cloud", label: "Cloud API" },
            { key: "local", label: "Local" },
          ] as { key: Source; label: string }[]
        ).map((opt) => {
          const selected = source === opt.key;
          return (
            <button
              key={opt.key}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => pick(opt.key)}
              className="border-r border-border px-2.5 py-1 text-xs font-medium transition-colors last:border-r-0"
              style={{
                backgroundColor: selected ? "var(--accent-muted)" : "var(--bg-surface)",
                color: selected ? "var(--accent)" : "var(--text-secondary)",
              }}
            >
              {opt.label}
            </button>
          );
        })}
      </div>

      {/* Step 2 — which model, scoped to the chosen source. */}
      {source === "default" && (
        <p className="mt-2 text-xs font-mono text-text-muted">
          Using your configured provider and endpoint from Settings (Custom Endpoint / OmniRoute).
        </p>
      )}
      {source === "cloud" && (
        <div className="mt-2.5 space-y-1.5">
          {cloudModels.length === 0 ? (
            <p className="text-[0.75rem] text-text-muted">
              No cloud models available — add an API key in Settings.
            </p>
          ) : (
            <select
              className="input-base w-full"
              value={selectedRoute}
              onChange={(e) => onChange(routeToRouting(e.target.value))}
              aria-label="Cloud model"
            >
              {cloudModels.map((m) => (
                <option key={m.route} value={m.route}>
                  {m.display_name} — {priceLabel(m)}
                </option>
              ))}
            </select>
          )}

          {/* Why the list is shorter than the catalog. Without this the omission looks
              like the product simply does not support those providers. */}
          {lockedProviders.length > 0 && (
            <p className="text-[0.6875rem] leading-relaxed text-text-muted">
              {lockedProviders
                .map(([provider, count]) => `${count} ${provider}`)
                .join(", ")}{" "}
              {lockedProviders.reduce((n, [, c]) => n + c, 0) === 1 ? "model is" : "models are"}{" "}
              hidden — no API key configured. Add one in{" "}
              <Link href="/settings" className="text-accent hover:underline">
                Settings
              </Link>
              .
            </p>
          )}
        </div>
      )}

      {source === "local" && (
        <div className="mt-2.5">
          {!local?.reachable ? (
            <p className="text-[0.75rem] text-text-muted">
              No local model server detected. Start Ollama, then check Settings → Local
              models.
            </p>
          ) : localModels.length === 0 ? (
            <p className="text-[0.75rem] text-text-muted">
              No usable local models installed — pull one, e.g. <code>ollama pull
              qwen2.5:14b</code>.
            </p>
          ) : (
            <>
              <select
                className="input-base w-full"
                value={selectedRoute}
                onChange={(e) => onChange(routeToRouting(e.target.value))}
                aria-label="Local model"
              >
                {localModels.map((m) => (
                  <option key={m.name} value={m.route ?? `ollama:${m.name}`}>
                    {m.name}
                    {m.likely_underpowered ? " — small, may struggle with research" : ""}
                  </option>
                ))}
              </select>
              <p className="mt-1.5 text-[0.6875rem] leading-relaxed text-text-muted">
                Runs entirely on your machine — free, and nothing leaves it. Models under
                14B often fail to return citable evidence.
              </p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
