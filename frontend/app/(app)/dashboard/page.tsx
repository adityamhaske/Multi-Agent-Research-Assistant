"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import toast from "react-hot-toast";

import { SessionCard } from "@/components/SessionCard";
import { useSessions, useStartResearch } from "@/hooks/queries";
import { ApiError } from "@/lib/api";
import type { ResearchDepth } from "@/lib/types";

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
  const start = useStartResearch();
  const { data, isLoading, isError, refetch } = useSessions(1, 5);

  const trimmed = query.trim();
  const tooShort = trimmed.length > 0 && trimmed.length < MIN_QUERY;
  const canSubmit = trimmed.length >= MIN_QUERY && trimmed.length <= MAX_QUERY && !start.isPending;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    try {
      const res = await start.mutateAsync({ query: trimmed, depth });
      router.push(`/session/${res.session_id}`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not start research.");
    }
  };

  return (
    <div className="space-y-10">
      <section aria-labelledby="new-research">
        <h1 id="new-research" className="mb-1 text-xl font-semibold text-text-primary">
          New research
        </h1>
        <p className="mb-4 text-sm text-text-muted">
          Describe what you want to know. The agents will plan, gather cited evidence, and draft a
          report for your review.
        </p>

        <form onSubmit={submit} className="card space-y-5">
          <div>
            <label htmlFor="query" className="mb-1.5 block text-sm font-medium text-text-secondary">
              Research question
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
            <div id="query-counter" className="mt-1 flex justify-between text-xs">
              <span style={{ color: tooShort ? "var(--warning)" : "var(--text-muted)" }}>
                {tooShort ? `At least ${MIN_QUERY} characters` : " "}
              </span>
              <span className="text-text-muted tabular-nums">
                {trimmed.length} / {MAX_QUERY}
              </span>
            </div>
          </div>

          <fieldset>
            <legend className="mb-2 text-sm font-medium text-text-secondary">Depth</legend>
            <div className="grid gap-2 sm:grid-cols-3">
              {DEPTHS.map((d) => (
                <label
                  key={d.value}
                  className="flex cursor-pointer flex-col gap-1 rounded-lg border p-3 transition-colors"
                  style={{
                    borderColor: depth === d.value ? "var(--accent)" : "var(--border)",
                    backgroundColor:
                      depth === d.value ? "var(--accent-muted)" : "var(--bg-elevated)",
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

          <button type="submit" disabled={!canSubmit} className="btn btn-primary">
            {start.isPending && <span className="spinner" />}
            Start research
          </button>
        </form>
      </section>

      <section aria-labelledby="recent">
        <div className="mb-4 flex items-center justify-between">
          <h2 id="recent" className="text-lg font-semibold text-text-primary">
            Recent sessions
          </h2>
          {data && data.total > 5 && (
            <Link href="/history" className="text-sm text-accent hover:underline">
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
          <div className="card text-center">
            <p className="text-sm text-text-secondary">No research yet.</p>
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
