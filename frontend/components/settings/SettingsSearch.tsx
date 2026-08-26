"use client";

import Link from "next/link";
import { useState } from "react";

/**
 * Type-to-filter across every setting (docs/07 §2, Phase 3) — the thing that makes
 * "as much customization as possible" survivable instead of another 452-line scroll,
 * just split into seven scrolls. A static index rather than a live DOM search: it
 * works even before the target section has ever been rendered, and stays honest
 * about which settings actually exist (docs/07 §2 — "never fake").
 */
type Entry = { section: string; label: string; keywords: string };

const INDEX: Entry[] = [
  { section: "models", label: "Per-role model routing", keywords: "model routing role planner executor critic synthesizer chat" },
  { section: "models", label: "Local models (Ollama)", keywords: "ollama local llm model server" },
  { section: "connections", label: "API key (BYOK)", keywords: "api key byok provider anthropic openai google gemini claude openrouter custom endpoint token" },
  { section: "connections", label: "Connection health", keywords: "connection test probe status red yellow green" },
  { section: "search", label: "Tavily Search API key", keywords: "tavily search provider retriever web key" },
  { section: "search", label: "Brave Search API key", keywords: "brave search provider retriever web key" },
  { section: "search", label: "DuckDuckGo fallback", keywords: "duckduckgo ddg fallback keyless web search" },
  { section: "research", label: "Search results per query", keywords: "retrieval search results web count k" },
  { section: "research", label: "Minimum sources per task", keywords: "sources evidence minimum critic floor" },
  { section: "research", label: "Snippet length", keywords: "snippet citation length characters truncate" },
  { section: "projects", label: "Create, rename, archive, delete projects", keywords: "project projects delete archive restore rename history" },
  { section: "appearance", label: "Theme", keywords: "appearance theme dark light mode" },
  { section: "advanced", label: "Token usage", keywords: "usage tokens cost spend" },
  { section: "advanced", label: "Monthly spending limit", keywords: "spending limit budget cap monthly token" },
];

export function SettingsSearch() {
  const [q, setQ] = useState("");
  const query = q.trim().toLowerCase();
  const matches = query.length < 2 ? [] : INDEX.filter((e) => e.keywords.includes(query) || e.label.toLowerCase().includes(query));

  return (
    <div className="relative">
      <div className="relative flex items-center">
        <svg
          className="pointer-events-none absolute left-3.5 h-4 w-4 text-text-muted"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search settings…"
          aria-label="Search settings"
          className="input-base w-full pl-9.5 pr-8 py-2 text-sm border-border/80 bg-bg-surface/90 focus:border-accent focus:ring-1 focus:ring-accent/40 shadow-xs"
        />
        {q && (
          <button
            type="button"
            onClick={() => setQ("")}
            className="absolute right-2.5 p-0.5 text-text-muted hover:text-text-primary hover:bg-bg-elevated transition-colors"
            title="Clear search"
            aria-label="Clear search"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
            </svg>
          </button>
        )}
      </div>

      {matches.length > 0 && (
        <ul className="absolute left-0 right-0 z-30 mt-1.5 max-h-72 overflow-y-auto border border-border/80 bg-bg-surface/95 p-1.5 shadow-lg backdrop-blur-md">
          {matches.map((m) => (
            <li key={`${m.section}-${m.label}`}>
              <Link
                href={`/settings/${m.section}`}
                onClick={() => setQ("")}
                className="flex items-center justify-between px-3 py-2 text-xs font-medium text-text-primary transition-colors hover:bg-bg-elevated"
              >
                <span>{m.label}</span>
                <span className="bg-bg-elevated px-1.5 py-0.5 font-mono text-[0.625rem] uppercase tracking-wider text-text-muted border border-border/60">
                  {m.section}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {query.length >= 2 && matches.length === 0 && (
        <div className="absolute left-0 right-0 z-30 mt-1.5 border border-border/80 bg-bg-surface/95 px-3 py-2.5 text-xs text-text-muted shadow-lg backdrop-blur-md">
          No matching settings found.
        </div>
      )}
    </div>
  );
}
