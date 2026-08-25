"use client";

import { useCustomEndpointStatus, useLocalLLMStatus, useModelCatalog } from "@/hooks/queries";
import type { ModelRouting } from "@/lib/types";

/**
 * Which kind of model backend this run uses. Three buttons, nothing else.
 *
 * **Why the run form only picks a backend.** Choosing an individual model is a setting: it
 * changes rarely, it needs the price and context window next to it, and it belongs beside
 * the keys that make a provider reachable at all. What changes per run is which *kind* of
 * backend to spend on — the gateway, the machine under the desk, or a metered API — so
 * that is the only decision here. Everything else lives in Settings → Models.
 *
 * **The default is the first backend that is actually reachable**, in the order custom →
 * local → API. That order is a *selection* default, resolved once before the run starts
 * and shown on the button. It is deliberately **not** a runtime fallback: nothing
 * substitutes a provider mid-run, because the finished report's attribution would then be
 * the first place a substitution became visible — which is the failure this whole surface
 * exists to prevent. If the chosen backend is down, the run fails saying so.
 */

export type ProviderKind = "custom" | "local" | "api";

/**
 * Only the parts of each source these helpers actually read.
 *
 * Narrower than `ModelCatalog`/`LocalLLMStatus`/`CustomEndpointStatus` on purpose: it says
 * exactly which fields the resolution depends on, and it keeps a caller (or a test) from
 * having to construct a whole catalog to ask one question.
 */
export interface RoutingSource {
  user_routing?: ModelRouting | null;
  deployment_routing?: ModelRouting | null;
  models?: { route: string; provider: string; available: boolean }[];
}
export interface CustomSource {
  reachable?: boolean;
  models?: string[];
  configured_base_url?: string;
  hint?: string | null;
  error?: string | null;
}
export interface LocalSource {
  models?: { route: string | null; is_embedding: boolean }[];
}

const ROLE_ORDER = ["planner", "executor", "critic", "synthesizer", "chat"] as const;

/** One route applied to every role — the shape the create-run endpoint validates. */
export function routingFor(route: string): ModelRouting {
  return Object.fromEntries(ROLE_ORDER.map((r) => [r, route])) as ModelRouting;
}

/** `provider:model` split on the FIRST colon — `ollama:qwen2.5:7b` keeps its tag. */
export function splitRoute(route: string): { provider: string; model: string } {
  const i = route.indexOf(":");
  if (i < 0) return { provider: route, model: "" };
  return { provider: route.slice(0, i), model: route.slice(i + 1) };
}

/**
 * Whether a route's spend can be measured at all.
 *
 * The catalog carries no price for these two, so `estimate_cost()` returns 0.0 and a run
 * on one reports `$0.00` whatever it really cost. Naming that is what stops the UI
 * printing an unmeasured zero as a measured total. Ollama is excluded deliberately: local
 * inference is genuinely free, which is a different statement from unknown.
 */
export function isUnpricedRoute(route: string | null | undefined): boolean {
  if (!route) return false;
  const { provider } = splitRoute(route);
  return provider === "custom" || provider === "openrouter";
}

export const PROVIDER_LABEL: Record<ProviderKind, string> = {
  custom: "Custom Endpoint",
  local: "Local LLM",
  api: "API",
};

const PROVIDER_NOTE: Record<ProviderKind, string> = {
  custom: "OpenAI-compatible gateway",
  local: "Runs on this machine",
  api: "Gemini, Claude, OpenAI…",
};

/** The three sources a route for a backend can come from, best first. */
export function routeForKind(
  kind: ProviderKind,
  catalog: RoutingSource | undefined,
  custom: CustomSource | undefined,
  local: LocalSource | undefined,
): string | null {
  // Settings wins wherever it names this backend: the whole point of moving the model
  // choice there is that the run form then honours it rather than guessing.
  const saved = catalog?.user_routing?.planner ?? null;
  const deployed = catalog?.deployment_routing?.planner ?? null;
  const savedProvider = saved ? splitRoute(saved).provider : null;
  const deployedProvider = deployed ? splitRoute(deployed).provider : null;

  if (kind === "custom") {
    if (savedProvider === "custom") return saved;
    if (deployedProvider === "custom") return deployed;
    const first = custom?.models?.[0];
    return first ? `custom:${first}` : null;
  }
  if (kind === "local") {
    if (savedProvider === "ollama") return saved;
    if (deployedProvider === "ollama") return deployed;
    const first = (local?.models ?? []).find((m) => !m.is_embedding && m.route);
    return first?.route ?? null;
  }
  // API: a catalogued, priced provider the user can actually reach.
  if (savedProvider && !["custom", "ollama"].includes(savedProvider)) return saved;
  if (deployedProvider && !["custom", "ollama"].includes(deployedProvider)) return deployed;
  const firstApi = (catalog?.models ?? []).find(
    (m) => m.available && m.provider !== "ollama" && m.provider !== "custom",
  );
  return firstApi?.route ?? null;
}

/** Reachable *right now*, which is a different question from "configured". */
export function isKindReady(
  kind: ProviderKind,
  catalog: RoutingSource | undefined,
  custom: CustomSource | undefined,
  local: LocalSource | undefined,
): boolean {
  if (kind === "custom") return Boolean(custom?.reachable);
  if (kind === "local") return (local?.models ?? []).some((m) => !m.is_embedding);
  return Boolean(routeForKind("api", catalog, custom, local));
}

/**
 * The backend a run should start on: custom → local → API, first one that is reachable.
 *
 * `null` while the probes are still in flight, so the caller can wait rather than briefly
 * showing a default it is about to change — a button that moves under the cursor is worse
 * than one that appears a moment late.
 */
export function defaultKind(
  catalog: RoutingSource | undefined,
  custom: CustomSource | undefined,
  local: LocalSource | undefined,
): ProviderKind | null {
  for (const kind of ["custom", "local", "api"] as ProviderKind[]) {
    if (isKindReady(kind, catalog, custom, local)) return kind;
  }
  return null;
}

export function ProviderPicker({
  value,
  onChange,
  disabled,
}: {
  value: ProviderKind;
  onChange: (next: ProviderKind) => void;
  disabled?: boolean;
}) {
  const catalog = useModelCatalog();
  const custom = useCustomEndpointStatus();
  const local = useLocalLLMStatus();

  const kinds: ProviderKind[] = ["custom", "local", "api"];

  return (
    <div>
      <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Model backend">
        {kinds.map((kind) => {
          const ready = isKindReady(kind, catalog.data, custom.data, local.data);
          const route = routeForKind(kind, catalog.data, custom.data, local.data);
          const active = value === kind;
          return (
            <button
              key={kind}
              type="button"
              role="radio"
              aria-checked={active}
              disabled={disabled}
              onClick={() => onChange(kind)}
              // `bg-accent-soft` is not a token this theme defines, and a utility naming
              // one that does not exist is silently dropped rather than failing — so the
              // selected state is carried by a real token plus `aria-checked`.
              className={`min-w-[9rem] flex-1 border p-2.5 text-left ${
                active ? "border-accent bg-bg-elevated" : "border-border bg-bg-surface"
              }`}
            >
              <span className="flex items-center gap-1.5">
                {/* Status is a dot AND a word: colour alone carries nothing to a screen
                    reader, and "running/stopped" is the fact the dot is standing in for. */}
                <span
                  aria-hidden
                  className={`inline-block h-2 w-2 shrink-0 rounded-full ${
                    ready ? "bg-success" : "bg-danger"
                  }`}
                />
                <span className="text-sm font-medium text-text-primary">
                  {PROVIDER_LABEL[kind]}
                </span>
                {/* Self-contained rather than a bare " — stopped": a screen reader may
                    reach this out of order, and "stopped" on its own names nothing. */}
                <span className="sr-only">
                  {PROVIDER_LABEL[kind]} is {ready ? "running" : "stopped"}
                </span>
              </span>
              <span className="mt-0.5 block text-xs text-text-muted">{PROVIDER_NOTE[kind]}</span>
              <span className="mt-1 block break-all font-mono text-[length:var(--text-micro)] text-text-secondary">
                {route ?? "not configured"}
              </span>
            </button>
          );
        })}
      </div>

      {/* The chosen backend is down. Said plainly, and the choice is left alone — the run
          will fail naming the provider rather than quietly succeeding on another one. */}
      {!isKindReady(value, catalog.data, custom.data, local.data) && (
        <p role="alert" className="mt-2 text-xs text-danger">
          {PROVIDER_LABEL[value]} is not reachable right now. Starting a run on it will fail
          rather than switch to another provider.
        </p>
      )}

      <p className="mt-2 text-xs text-text-secondary">
        Which models each of these uses is set in{" "}
        <span className="text-text-primary">Settings → Models</span>.
      </p>
    </div>
  );
}
