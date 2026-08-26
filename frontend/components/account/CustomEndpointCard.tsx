"use client";

import { useState } from "react";
import toast from "react-hot-toast";

import {
  useCustomEndpointStatus,
  useModelRouting,
  useSetModelRouting,
} from "@/hooks/queries";
import { ApiError } from "@/lib/api";
import type { ModelRouting } from "@/lib/types";

/**
 * The custom OpenAI-compatible endpoint (OmniRoute, LiteLLM, vLLM, a gateway), in Settings.
 *
 * **Why this card has to exist separately from the model picker below it.** That picker
 * renders `catalog.models`, and this provider has no catalog entries by nature — its model
 * list belongs to the endpoint and changes without us. So a deployment whose entire routing
 * is `custom:` could not select its own models anywhere in the product: the only pickable
 * options were models the deployment does not route to.
 *
 * **Reachability is shown, never worked around.** The dot says whether the gateway answered
 * just now. When it is down this still saves the choice and says the endpoint is down; it
 * does not quietly rewrite the routing to another provider, because a substitution made
 * here would surface for the first time in a finished report's model attribution.
 *
 * Saving writes one model into every role, which is what this control is for. Per-role
 * routing stays in the picker below — the two write the same `PUT /models/routing`.
 */

const ROLES = ["planner", "executor", "critic", "synthesizer", "chat"] as const;

export function CustomEndpointCard() {
  const status = useCustomEndpointStatus();
  const routing = useModelRouting();
  const setRouting = useSetModelRouting();

  // Seeded from whatever is saved, so the field opens on the model actually in use rather
  // than empty — an empty box beside a live gateway reads as "nothing configured".
  const savedRoute = routing.data?.effective_routing?.planner ?? "";
  const savedModel = savedRoute.startsWith("custom:") ? savedRoute.slice("custom:".length) : "";
  const [model, setModel] = useState<string | null>(null);
  const value = model ?? savedModel;

  const reachable = Boolean(status.data?.reachable);
  const models = status.data?.models ?? [];

  const save = async () => {
    const id = value.trim();
    if (!id) return toast.error("Enter a model id first.");
    const next = Object.fromEntries(ROLES.map((r) => [r, `custom:${id}`])) as ModelRouting;
    try {
      await setRouting.mutateAsync(next);
      toast.success("Research will run on this endpoint.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not save that routing.");
    }
  };

  return (
    <section className="card" aria-labelledby="custom-endpoint-heading">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2
          id="custom-endpoint-heading"
          className="font-serif text-base font-bold text-text-primary"
        >
          Custom Endpoint
        </h2>
        <span className="flex items-center gap-1.5">
          <span
            aria-hidden
            className={`inline-block h-2 w-2 ${
              reachable ? "bg-success" : "bg-danger"
            }`}
          />
          <span className={`font-mono text-xs ${reachable ? "text-success" : "text-danger"}`}>
            {status.isLoading ? "checking…" : reachable ? "running" : "stopped"}
          </span>
        </span>
      </div>

      <p className="mt-1 text-sm leading-relaxed text-text-secondary">
        An OpenAI-compatible gateway. Research prefers this endpoint when it is reachable.
      </p>
      <p className="mt-1 font-mono text-[length:var(--text-micro)] text-text-muted">
        {status.data?.configured_base_url || "No endpoint configured"}
      </p>

      <label htmlFor="custom-endpoint-model" className="mt-4 block text-sm text-text-primary">
        Model
      </label>
      {/* Free text with suggestions rather than a dropdown: this endpoint advertised 2,461
          ids on the machine this was built against, and a gateway may serve one it does not
          list at all. The id is kept verbatim — it is what resolves at call time. */}
      <input
        id="custom-endpoint-model"
        type="text"
        list="custom-endpoint-models"
        value={value}
        placeholder="e.g. auto/best-fast"
        onChange={(e) => setModel(e.target.value)}
        className="input-base mt-1.5 w-full font-mono text-xs"
      />
      <datalist id="custom-endpoint-models">
        {models.map((id) => (
          <option key={id} value={id} />
        ))}
      </datalist>

      <p className="mt-1.5 text-xs text-text-muted">
        {status.isLoading
          ? "Asking the endpoint what it serves…"
          : reachable
            ? models.length > 0
              ? `${models.length.toLocaleString()} models available.`
              : (status.data?.hint ?? "Reachable, but it listed no models.")
            : (status.data?.hint ?? status.data?.error ?? "The endpoint did not answer.")}
      </p>

      {/* Cost is not measurable here and the run will report $0.00 regardless of what it
          spent — the catalog has no price for this provider, so the per-session cap cannot
          bind. Said where the choice is made, not left for the run to imply otherwise. */}
      <p className="mt-2 text-xs leading-relaxed text-text-secondary">
        Spend through this endpoint cannot be measured or capped here — a run will report
        <span className="font-mono"> $0.00 </span>
        whatever it costs. Cap spend at the gateway.
      </p>

      <div className="mt-3 flex justify-end">
        <button
          type="button"
          className="btn btn-primary"
          disabled={setRouting.isPending || !value.trim()}
          onClick={save}
        >
          {setRouting.isPending && <span className="spinner" />}
          Use this endpoint
        </button>
      </div>
    </section>
  );
}
