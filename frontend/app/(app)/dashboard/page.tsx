"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import toast from "react-hot-toast";

import { SessionCard } from "@/components/SessionCard";
import { useActiveProject } from "@/components/ActiveProject";
import { StartModelPicker } from "@/components/StartModelPicker";
import { useSessions, useStartResearch } from "@/hooks/queries";
import { ApiError } from "@/lib/api";
import { sessionHref } from "@/lib/desktop";
import type { ModelRouting, ResearchDepth } from "@/lib/types";

const MIN_QUERY = 10;
const MAX_QUERY = 2000;

const DEPTHS: { value: ResearchDepth; label: string; hint: string }[] = [
  { value: "fast", label: "Fast", hint: "Quick scan · fewer sources · lowest cost" },
  { value: "balanced", label: "Balanced", hint: "Recommended · solid coverage · moderate cost" },
  { value: "comprehensive", label: "Comprehensive", hint: "Deep dive · most sources · highest cost" },
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
  const start = useStartResearch();
  const { activeId, active } = useActiveProject();
  const { data, isLoading, isError, refetch } = useSessions(1, 5, false, activeId);

  const trimmed = query.trim();
  const tooShort = trimmed.length > 0 && trimmed.length < MIN_QUERY;
  const canSubmit = trimmed.length >= MIN_QUERY && trimmed.length <= MAX_QUERY && !start.isPending;

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
          Describe what you want to know. The agents plan, gather cited evidence, and draft a report
          for your review.{" "}
          {active && (
            <>
              Saved to <strong className="text-text-secondary">{active.name}</strong>.
            </>
          )}
        </p>

        <form onSubmit={submit} className="card space-y-5 p-5 sm:p-6">
          <div>
            <label htmlFor="query" className="mb-1.5 block text-sm font-medium text-text-secondary">
              Research Question
            </label>
            <textarea
              id="query"
              rows={4}
              value={query}
              onChange={(e) => setQuery(e.target.value.slice(0, MAX_QUERY))}
              placeholder={`e.g. ${SAMPLE_QUERY}`}
              className="textarea-base"
              aria-describedby="query-counter"
            />
            <div id="query-counter" className="mt-1 flex justify-between font-mono text-xs">
              <span style={{ color: tooShort ? "var(--warning)" : "var(--text-muted)" }}>
                {tooShort ? `At least ${MIN_QUERY} characters` : " "}
              </span>
              <span className="text-text-muted tabular-nums">
                {trimmed.length} / {MAX_QUERY}
              </span>
            </div>
          </div>

          <fieldset>
            <legend className="mb-2 font-mono text-xs uppercase tracking-wider font-semibold text-text-secondary">Research Depth</legend>
            <div className="grid gap-2 sm:grid-cols-3">
              {DEPTHS.map((d) => (
                <label
                  key={d.value}
                  className="flex cursor-pointer flex-col gap-1 border p-3.5 transition-colors"
                  style={{
                    borderColor: depth === d.value ? "var(--accent)" : "var(--border)",
                    backgroundColor:
                      depth === d.value ? "var(--accent-muted)" : "var(--bg-surface)",
                  }}
                >
                  <span className="flex items-center gap-2">
                    <input
                      type="radio"
                      name="depth"
                      value={d.value}
                      checked={depth === d.value}
                      onChange={() => setDepth(d.value)}
                      className="accent-[var(--accent)]"
                    />
                    <span className="text-sm font-medium text-text-primary">{d.label}</span>
                  </span>
                  <span className="text-xs text-text-muted">{d.hint}</span>
                </label>
              ))}
            </div>
          </fieldset>

          <fieldset>
            <legend className="mb-2 font-mono text-xs uppercase tracking-wider font-semibold text-text-secondary">Airgapped Corpus Mode</legend>
            <label className="flex items-center gap-3 border border-border p-3 bg-bg-surface">
              <input
                type="checkbox"
                checked={corpusMode}
                onChange={(e) => setCorpusMode(e.target.checked)}
                className="h-4 w-4 border-border accent-[var(--accent)]"
              />
              <div>
                <span className="block text-sm font-medium text-text-primary">Restrict research to uploaded corpus</span>
                <span className="block text-xs text-text-muted">Disables web search. Enforces local embedding and LLM.</span>
              </div>
            </label>
          </fieldset>

          <StartModelPicker value={modelRouting} onChange={setModelRouting} />

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
            <span aria-hidden className="mb-2 text-2xl opacity-60">◇</span>
            <p className="text-sm font-medium text-text-primary">No research yet</p>
            <p className="mt-0.5 text-xs text-text-muted">Your completed reports will appear here.</p>
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
