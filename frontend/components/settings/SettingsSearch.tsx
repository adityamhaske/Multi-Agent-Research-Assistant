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
  { section: "corpus", label: "Uploaded documents", keywords: "corpus documents upload airgapped pdf" },
  { section: "exports", label: "Export formats", keywords: "export markdown pdf bundle citation" },
  { section: "appearance", label: "Theme", keywords: "appearance theme dark light mode" },
  { section: "appearance", label: "Density", keywords: "density compact comfortable spacing" },
  { section: "advanced", label: "Token usage", keywords: "usage tokens cost spend" },
  { section: "advanced", label: "Monthly spending limit", keywords: "spending limit budget cap monthly token" },
];

export function SettingsSearch() {
  const [q, setQ] = useState("");
  const query = q.trim().toLowerCase();
  const matches = query.length < 2 ? [] : INDEX.filter((e) => e.keywords.includes(query) || e.label.toLowerCase().includes(query));

  return (
    <div className="relative">
      <input
        type="search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Search settings…"
        aria-label="Search settings"
        className="input-base w-full text-sm"
      />
      {matches.length > 0 && (
        <ul className="menu-surface absolute z-20 mt-1 w-full max-h-72 overflow-y-auto">
          {matches.map((m) => (
            <li key={`${m.section}-${m.label}`}>
              <Link
                href={`/settings/${m.section}`}
                onClick={() => setQ("")}
                className="menu-item justify-between"
              >
                <span>{m.label}</span>
                <span className="font-mono text-[0.6875rem] uppercase tracking-wider text-text-muted">
                  {m.section}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {query.length >= 2 && matches.length === 0 && (
        <div className="menu-surface absolute z-20 mt-1 w-full px-3 py-2 text-xs text-text-muted">
          No matching setting.
        </div>
      )}
    </div>
  );
}
