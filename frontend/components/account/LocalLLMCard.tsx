"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { queryKeys, useLocalLLMStatus } from "@/hooks/queries";
import type { LocalModelInfo } from "@/lib/types";

import { Section } from "./Section";

/**
 * Local model server status (docs/12 M15).
 *
 * The point of this card is honesty. `available_providers()` marks Ollama usable
 * whenever the app is built, because local inference needs no key — so before this
 * existed, a user could pick a local model and only learn it was unreachable minutes
 * into a run. Here they see, before starting anything: is a server there, which models
 * does it have, and which of those are actually strong enough for the pipeline.
 */

function statusTone(reachable: boolean, usable: boolean) {
  if (usable) return { label: "Connected", color: "var(--success)" };
  if (reachable) return { label: "No models", color: "var(--warning)" };
  return { label: "Not detected", color: "var(--text-muted)" };
}

function formatSize(bytes: number | null) {
  if (!bytes) return null;
  const gb = bytes / 1_000_000_000;
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${Math.round(bytes / 1_000_000)} MB`;
}

/** Three distinct kinds, because "not research ready" has two different causes. */
function modelBadge(model: LocalModelInfo) {
  if (model.is_embedding) {
    return {
      label: "embedding",
      tone: "var(--text-muted)",
      title: "Powers retrieval. Cannot be used as a planner/executor/critic/chat model.",
    };
  }
  if (model.likely_underpowered) {
    return {
      label: "chat only",
      tone: "var(--warning)",
      title:
        "Small models usually fail the research pipeline's structured-evidence step. Fine for chat.",
    };
  }
  return { label: "research ready", tone: "var(--success)", title: undefined };
}

function ModelRow({ model }: { model: LocalModelInfo }) {
  const size = formatSize(model.size_bytes);
  const badge = modelBadge(model);
  return (
    <li className="flex flex-wrap items-center gap-x-2.5 gap-y-1 py-2">
      <code className="font-mono text-[0.8125rem] text-text-primary">{model.name}</code>
      {size && <span className="text-[0.6875rem] text-text-muted tabular-nums">{size}</span>}
      <span
        className="rounded-full px-2 py-0.5 text-[0.6875rem]"
        style={{
          background: `color-mix(in srgb, ${badge.tone} 12%, transparent)`,
          color: badge.tone,
        }}
        title={badge.title}
      >
        {badge.label}
      </span>
      {model.route && !model.is_embedding && (
        <code className="ml-auto font-mono text-[0.6875rem] text-text-muted">{model.route}</code>
      )}
    </li>
  );
}

export function LocalLLMCard() {
  const qc = useQueryClient();
  const { data, isLoading, isFetching } = useLocalLLMStatus();
  const [expanded, setExpanded] = useState(false);

  const tone = data ? statusTone(data.reachable, data.usable) : null;
  const models = data?.models ?? [];
  const shown = expanded ? models : models.slice(0, 5);

  return (
    <Section
      title="Local models (Ollama)"
      description={
        <>
          Run the assistant against a model on your own machine — no API key, no cost, and
          nothing leaves your computer.{" "}
          <a
            className="underline underline-offset-2 hover:text-text-secondary"
            href="https://github.com/adityamhaske/multi-agent-research-assistant/blob/main/docs/guides/Local_LLM_Setup.md"
            target="_blank"
            rel="noopener noreferrer nofollow"
          >
            Setup guide
          </a>
        </>
      }
      footer={
        <button
          type="button"
          className="btn btn-secondary"
          disabled={isFetching}
          onClick={() => qc.invalidateQueries({ queryKey: queryKeys.localLLM })}
        >
          {isFetching ? "Checking…" : "Test connection"}
        </button>
      }
    >
      {isLoading ? (
        <div className="h-16 animate-pulse rounded-lg bg-bg-base" aria-hidden />
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <span className="flex items-center gap-2 text-[0.8125rem] font-medium">
              <span
                aria-hidden
                className="inline-block h-2 w-2 rounded-full"
                style={{ background: tone?.color }}
              />
              <span style={{ color: tone?.color }}>{tone?.label}</span>
            </span>
            <code className="font-mono text-[0.6875rem] text-text-muted">
              {data?.configured_base_url}
            </code>
          </div>

          {data?.hint && (
            <p
              className="rounded-lg px-3 py-2.5 text-[0.8125rem] leading-relaxed"
              style={{
                background: "color-mix(in srgb, var(--warning) 8%, transparent)",
                color: "var(--text-secondary)",
              }}
            >
              {data.hint}
            </p>
          )}

          {models.length > 0 && (
            <div>
              <ul className="divide-y divide-border">
                {shown.map((m) => (
                  <ModelRow key={m.name} model={m} />
                ))}
              </ul>
              {models.length > 5 && (
                <button
                  type="button"
                  className="mt-1 text-[0.75rem] text-text-muted underline underline-offset-2 hover:text-text-secondary"
                  onClick={() => setExpanded((v) => !v)}
                >
                  {expanded ? "Show fewer" : `Show all ${models.length}`}
                </button>
              )}
              <p className="mt-3 text-[0.75rem] leading-relaxed text-text-muted">
                Pick a local model per role in <strong>Model routing</strong> below. Models
                marked <em>chat only</em> are usually too small for research runs — they
                search fine but fail to return citable evidence in the required format.
              </p>
            </div>
          )}
        </div>
      )}
    </Section>
  );
}
