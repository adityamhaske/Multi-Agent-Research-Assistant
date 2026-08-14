"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import toast from "react-hot-toast";

import { useActiveProject } from "@/components/ActiveProject";
import { SessionCard } from "@/components/SessionCard";
import { StartModelPicker } from "@/components/StartModelPicker";
import { useSessions, useStartResearch } from "@/hooks/queries";
import { ApiError } from "@/lib/api";
import { sessionHref } from "@/lib/desktop";
import type { ModelRouting, ResearchDepth } from "@/lib/types";

/**
 * Start a research run (docs/07).
 *
 * The form used to stack four decisions at equal visual weight — question, depth, corpus
 * mode, model source — so asking a question meant first resolving three settings that
 * almost never change. Only two are load-bearing per run: what you want to know, and how
 * much of a run you are willing to pay for. The rest sit behind a disclosure.
 *
 * Collapsed is not hidden: the disclosure carries a summary of its own state, so a run
 * restricted to a corpus or pinned to a local model says so on the closed row. Silent
 * non-default state is worse than clutter.
 */

const MIN_QUERY = 10;
const MAX_QUERY = 2000;

const DEPTHS: { value: ResearchDepth; label: string; hint: string }[] = [
  { value: "fast", label: "Fast", hint: "A quick scan — fewer sources, lowest cost." },
  {
    value: "balanced",
    label: "Balanced",
    hint: "Solid coverage at moderate cost. Recommended for most questions.",
  },
  {
    value: "comprehensive",
    label: "Comprehensive",
    hint: "A deep dive — most sources, highest cost and longest run.",
  },
];

const SAMPLE_QUERY =
  "What are the leading approaches to long-term memory in LLM agents, and their trade-offs?";

export default function DashboardPage() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [depth, setDepth] = useState<ResearchDepth>("balanced");
  const [corpusMode, setCorpusMode] = useState(false);
  // null = use the saved per-role routing (user preference, else deployment default).
  const [modelRouting, setModelRouting] = useState<ModelRouting | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const start = useStartResearch();
  const { activeId, active } = useActiveProject();
  const { data, isLoading, isError, refetch } = useSessions(1, 5, false, activeId);

  const trimmed = query.trim();
  const tooShort = trimmed.length > 0 && trimmed.length < MIN_QUERY;
  const canSubmit = trimmed.length >= MIN_QUERY && trimmed.length <= MAX_QUERY && !start.isPending;
  const activeDepth = DEPTHS.find((d) => d.value === depth);

  // What the closed disclosure reports. Defaults stay quiet; anything else is named.
  const overrides = [corpusMode ? "Corpus only" : null, modelRouting ? "Custom model" : null].filter(
    Boolean,
  );

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    try {
      const res = await start.mutateAsync({
        query: trimmed,
        depth,
        project_id: activeId ?? null,
        model_routing: modelRouting,
        corpus_mode: corpusMode,
      });
      router.push(sessionHref(res.session_id));
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not start research.");
    }
  };

  return (
    <div className="space-y-10">
      <section aria-labelledby="new-research">
        <h1
          id="new-research"
          className="mb-1 font-serif text-2xl font-bold tracking-tight text-text-primary"
        >
          New Research
        </h1>
        <p className="mb-5 max-w-2xl text-sm leading-relaxed text-text-muted">
          Ask a question. The agents plan, gather cited evidence, and draft a report for your
          review.{" "}
          {active && (
            <>
              Saved to <strong className="text-text-secondary">{active.name}</strong>.
            </>
          )}
        </p>

        <form onSubmit={submit} className="card space-y-6 p-5 sm:p-6">
          {/* The question is the page. Everything else is a setting. */}
          <div>
            <label htmlFor="query" className="sr-only">
              Research question
            </label>
            <textarea
              id="query"
              rows={4}
              value={query}
              onChange={(e) => setQuery(e.target.value.slice(0, MAX_QUERY))}
              placeholder={`e.g. ${SAMPLE_QUERY}`}
              className="textarea-base w-full resize-y font-serif text-base leading-relaxed"
              aria-describedby="query-counter"
            />
            <div id="query-counter" className="mt-1 flex justify-between font-mono text-xs">
              <span style={{ color: tooShort ? "var(--warning)" : "var(--text-muted)" }}>
                {tooShort ? `At least ${MIN_QUERY} characters` : " "}
              </span>
              <span className="tabular-nums text-text-muted">
                {trimmed.length} / {MAX_QUERY}
              </span>
            </div>
          </div>

          {/* Depth as one segmented control rather than three competing cards. Real radios
              underneath, so keyboard and screen-reader behaviour is unchanged. */}
          <fieldset>
            <legend className="mb-2 font-mono text-xs font-semibold uppercase tracking-wider text-text-secondary">
              Depth
            </legend>
            <div className="flex w-full border border-border">
              {DEPTHS.map((d) => {
                const selected = depth === d.value;
                return (
                  <label
                    key={d.value}
                    className="flex-1 cursor-pointer border-r border-border px-3 py-2 text-center text-sm font-medium transition-colors last:border-r-0"
                    style={{
                      backgroundColor: selected ? "var(--accent)" : "var(--bg-surface)",
                      color: selected ? "var(--accent-contrast)" : "var(--text-secondary)",
                    }}
                  >
                    <input
                      type="radio"
                      name="depth"
                      value={d.value}
                      checked={selected}
                      onChange={() => setDepth(d.value)}
                      className="sr-only"
                    />
                    {d.label}
                  </label>
                );
              })}
            </div>
            {/* One line of guidance for the current choice, instead of three at once. */}
            <p className="mt-1.5 text-xs text-text-muted">{activeDepth?.hint}</p>
          </fieldset>

          {/* Settings that almost never change from run to run. */}
          <div className="border-t border-border pt-4">
            <button
              type="button"
              onClick={() => setShowAdvanced((v) => !v)}
              aria-expanded={showAdvanced}
              className="flex w-full items-center gap-2 font-mono text-xs text-text-muted transition-colors hover:text-text-primary"
            >
              <span aria-hidden className="inline-block w-3">
                {showAdvanced ? "▾" : "▸"}
              </span>
              <span className="uppercase tracking-wider">Options</span>
              {!showAdvanced &&
                (overrides.length > 0 ? (
                  <span className="ml-1 font-semibold text-accent">{overrides.join(" · ")}</span>
                ) : (
                  <span className="ml-1">Web search · your saved model</span>
                ))}
            </button>

            {showAdvanced && (
              <div className="mt-4 space-y-5">
                <label className="flex cursor-pointer items-start gap-3 border border-border bg-bg-surface p-3">
                  <input
                    type="checkbox"
                    checked={corpusMode}
                    onChange={(e) => setCorpusMode(e.target.checked)}
                    className="mt-0.5 h-4 w-4 shrink-0 border-border accent-[var(--accent)]"
                  />
                  <span>
                    <span className="block text-sm font-medium text-text-primary">
                      Restrict to uploaded corpus
                    </span>
                    <span className="block text-xs text-text-muted">
                      No web search. Evidence comes only from this project&apos;s documents,
                      using a local model.
                    </span>
                  </span>
                </label>

                <StartModelPicker value={modelRouting} onChange={setModelRouting} />
              </div>
            )}
          </div>

          <button type="submit" disabled={!canSubmit} className="btn btn-primary">
            {start.isPending && <span className="spinner" />}
            Start research
          </button>
        </form>
      </section>

      <section aria-labelledby="recent">
        <div className="mb-4 flex items-center justify-between">
          <h2 id="recent" className="font-serif text-lg font-bold tracking-tight text-text-primary">
            Recent Sessions
          </h2>
          {data && data.total > 5 && (
            <Link href="/history" className="font-mono text-xs text-accent hover:underline">
              View all →
            </Link>
          )}
        </div>

        {isLoading ? (
          <div className="grid gap-3 sm:grid-cols-2">
            {[0, 1].map((i) => (
              <div key={i} className="card h-28 animate-pulse" aria-hidden />
            ))}
          </div>
        ) : isError ? (
          <div className="card text-sm text-text-muted">
            Couldn&apos;t load recent sessions.{" "}
            <button onClick={() => refetch()} className="text-accent hover:underline">
              Retry
            </button>
          </div>
        ) : data && data.sessions.length > 0 ? (
          <div className="grid gap-3 sm:grid-cols-2">
            {data.sessions.map((s) => (
              <SessionCard key={s.session_id} session={s} />
            ))}
          </div>
        ) : (
          <div className="card flex flex-col items-center py-10 text-center">
            <span aria-hidden className="mb-2 text-2xl opacity-60">
              ◇
            </span>
            <p className="text-sm font-medium text-text-primary">No research yet</p>
            <p className="mt-0.5 text-xs text-text-muted">
              Your completed reports will appear here.
            </p>
            <button
              type="button"
              onClick={() => setQuery(SAMPLE_QUERY)}
              className="mt-2 text-sm text-accent hover:underline"
            >
              Try a sample question
            </button>
          </div>
        )}
      </section>
    </div>
  );
}
