"use client";

import { useTheme } from "next-themes";
import Link from "next/link";
import { useState, type JSX } from "react";
import toast from "react-hot-toast";

import { ApiKeyCard } from "@/components/account/ApiKeyCard";
import { DesktopKeysCard } from "@/components/account/DesktopKeysCard";
import { LocalLLMCard } from "@/components/account/LocalLLMCard";
import { CustomEndpointCard } from "@/components/account/CustomEndpointCard";
import { ModelPicker } from "@/components/account/ModelPicker";
import { Field, Section } from "@/components/account/Section";
import { ProjectsSection } from "@/components/settings/ProjectsSection";
import { ResetToDefault } from "@/components/settings/ResetToDefault";
import { useMe, useUpdateProfile, useUsage } from "@/hooks/queries";
import { ApiError } from "@/lib/api";
import { isDesktop } from "@/lib/desktop";
import { formatCost, formatNumber } from "@/lib/format";
import type { UsageWindow } from "@/lib/types";

const EMPTY: UsageWindow = { tokens_input: 0, tokens_output: 0, tokens_total: 0, cost_usd: 0, sessions: 0 };

function UsageStat({ label, sub, window: w }: { label: string; sub: string; window: UsageWindow }) {
  return (
    <div className="border border-border/80 bg-bg-surface/90 p-4 shadow-xs hover:border-border transition-all">
      <div className="flex items-center justify-between">
        <div className="font-mono text-xs font-semibold uppercase tracking-wider text-text-secondary">{label}</div>
        <span className="font-mono text-[0.6875rem] text-text-muted">{sub}</span>
      </div>
      <div className="mt-3 font-mono text-2xl font-bold tracking-tight text-text-primary tabular-nums">
        {formatNumber(w.tokens_total)}
      </div>
      <div className="mt-2 flex items-center gap-2 font-mono text-xs text-text-muted border-t border-border/40 pt-2">
        <span className="tabular-nums font-medium text-text-secondary">{formatCost(w.cost_usd)}</span>
        <span aria-hidden>·</span>
        <span className="tabular-nums">{w.sessions} session{w.sessions === 1 ? "" : "s"}</span>
      </div>
    </div>
  );
}

// ─── Models ──────────────────────────────────────────────────────────────────────

function ModelsSection() {
  return (
    <div className="space-y-6">
      {/* Ordered the way the run form resolves a backend: custom endpoint, then local,
          then the catalogued API providers in the picker. */}
      <CustomEndpointCard />
      <LocalLLMCard />
      <ModelPicker />
    </div>
  );
}

// ─── Connections ─────────────────────────────────────────────────────────────────
//
// The card itself lives in components/account/ApiKeyCard.tsx so it can be unit-tested
// — app/** is outside vitest's include glob, the same reason the Overview page's logic
// lives in lib/ rather than in app/(app)/project/.

function ConnectionsSection() {
  return isDesktop ? <DesktopKeysCard /> : <ApiKeyCard />;
}

// ─── Research ────────────────────────────────────────────────────────────────────

const RESEARCH_DEFAULTS = { retrieval_k: 5, min_sources_per_task: 0, snippet_max_chars: 500 };

function ResearchSection() {
  const { data: user, isLoading } = useMe();
  const updateProfile = useUpdateProfile();
  const [retrievalK, setRetrievalK] = useState<number | null>(null);
  const [minSources, setMinSources] = useState<number | null>(null);
  const [snippetChars, setSnippetChars] = useState<number | null>(null);

  if (isLoading || !user) return <div className="card h-40 animate-pulse" aria-hidden />;

  const effective = {
    retrieval_k: retrievalK ?? user.preferences.retrieval_k ?? RESEARCH_DEFAULTS.retrieval_k,
    min_sources_per_task: minSources ?? user.preferences.min_sources_per_task ?? RESEARCH_DEFAULTS.min_sources_per_task,
    snippet_max_chars: snippetChars ?? user.preferences.snippet_max_chars ?? RESEARCH_DEFAULTS.snippet_max_chars,
  };

  const save = async () => {
    try {
      await updateProfile.mutateAsync({
        preferences: {
          retrieval_k: effective.retrieval_k,
          min_sources_per_task: effective.min_sources_per_task,
          snippet_max_chars: effective.snippet_max_chars,
        },
      });
      setRetrievalK(null);
      setMinSources(null);
      setSnippetChars(null);
      toast.success("Research settings saved.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not save.");
    }
  };

  const dirty =
    (retrievalK !== null && retrievalK !== (user.preferences.retrieval_k ?? RESEARCH_DEFAULTS.retrieval_k)) ||
    (minSources !== null && minSources !== (user.preferences.min_sources_per_task ?? RESEARCH_DEFAULTS.min_sources_per_task)) ||
    (snippetChars !== null && snippetChars !== (user.preferences.snippet_max_chars ?? RESEARCH_DEFAULTS.snippet_max_chars));

  return (
    <Section
      title="Retrieval"
      description="How the executor gathers and grades evidence for each research task. Every value below defaults to what today's runs already do."
      footer={
        <div className="flex items-center justify-between w-full">
          <span className="text-xs text-text-muted">Changes apply to all future runs.</span>
          <button type="button" onClick={save} disabled={!dirty || updateProfile.isPending} className="btn btn-primary">
            {updateProfile.isPending && <span className="spinner" />}
            Save changes
          </button>
        </div>
      }
    >
      <div className="space-y-5">
        <Field label="Search results per query" htmlFor="retrieval_k" hint="How many web results the executor requests per search call.">
          <div className="flex items-center gap-3">
            <input
              id="retrieval_k"
              type="number"
              min={1}
              max={20}
              value={effective.retrieval_k}
              onChange={(e) => setRetrievalK(Number(e.target.value))}
              className="input-base max-w-[8rem] font-mono"
            />
            <ResetToDefault
              isDefault={effective.retrieval_k === RESEARCH_DEFAULTS.retrieval_k}
              onReset={() => setRetrievalK(RESEARCH_DEFAULTS.retrieval_k)}
            />
          </div>
        </Field>
        <Field label="Minimum sources per task" htmlFor="min_sources" hint="A task with fewer sources than this fails the critic without spending a model call. 0 = no floor.">
          <div className="flex items-center gap-3">
            <input
              id="min_sources"
              type="number"
              min={0}
              max={20}
              value={effective.min_sources_per_task}
              onChange={(e) => setMinSources(Number(e.target.value))}
              className="input-base max-w-[8rem] font-mono"
            />
            <ResetToDefault
              isDefault={effective.min_sources_per_task === RESEARCH_DEFAULTS.min_sources_per_task}
              onReset={() => setMinSources(RESEARCH_DEFAULTS.min_sources_per_task)}
            />
          </div>
        </Field>
        <Field label="Snippet length (characters)" htmlFor="snippet_chars" hint="Caps each cited quotation. Cannot exceed 500 — the platform-wide ceiling.">
          <div className="flex items-center gap-3">
            <input
              id="snippet_chars"
              type="number"
              min={100}
              max={500}
              value={effective.snippet_max_chars}
              onChange={(e) => setSnippetChars(Number(e.target.value))}
              className="input-base max-w-[8rem] font-mono"
            />
            <ResetToDefault
              isDefault={effective.snippet_max_chars === RESEARCH_DEFAULTS.snippet_max_chars}
              onReset={() => setSnippetChars(RESEARCH_DEFAULTS.snippet_max_chars)}
            />
          </div>
        </Field>
      </div>
    </Section>
  );
}

// ─── Appearance ──────────────────────────────────────────────────────────────────

function AppearanceSection() {
  const { resolvedTheme, setTheme } = useTheme();

  return (
    <Section title="Theme" description="Choose how the interface looks on this device.">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4" role="radiogroup" aria-label="Theme">
        {/* Light Option */}
        <button
          type="button"
          role="radio"
          aria-checked={resolvedTheme === "light"}
          onClick={() => setTheme("light")}
          className={`group flex items-center justify-between p-4 border text-left transition-all ${
            resolvedTheme === "light"
              ? "border-accent bg-accent/5 ring-1 ring-accent/30 shadow-sm"
              : "border-border/80 bg-bg-surface hover:border-border hover:bg-bg-elevated/40"
          }`}
        >
          <div className="flex items-center gap-3.5">
            <div className={`p-2.5 border transition-colors ${
              resolvedTheme === "light"
                ? "bg-accent/15 border-accent/30 text-accent"
                : "bg-bg-elevated border-border text-text-muted group-hover:text-text-primary"
            }`}>
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
              </svg>
            </div>
            <div>
              <div className="font-semibold text-sm text-text-primary">Light Mode</div>
              <div className="text-xs text-text-muted mt-0.5">Crisp, high-contrast light theme</div>
            </div>
          </div>
          <div className={`h-5 w-5 border flex items-center justify-center transition-colors ${
            resolvedTheme === "light" ? "border-accent bg-accent text-white" : "border-border"
          }`}>
            {resolvedTheme === "light" && (
              <svg className="w-3 h-3" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
              </svg>
            )}
          </div>
        </button>

        {/* Dark Option */}
        <button
          type="button"
          role="radio"
          aria-checked={resolvedTheme === "dark"}
          onClick={() => setTheme("dark")}
          className={`group flex items-center justify-between p-4 border text-left transition-all ${
            resolvedTheme === "dark"
              ? "border-accent bg-accent/5 ring-1 ring-accent/30 shadow-sm"
              : "border-border/80 bg-bg-surface hover:border-border hover:bg-bg-elevated/40"
          }`}
        >
          <div className="flex items-center gap-3.5">
            <div className={`p-2.5 border transition-colors ${
              resolvedTheme === "dark"
                ? "bg-accent/15 border-accent/30 text-accent"
                : "bg-bg-elevated border-border text-text-muted group-hover:text-text-primary"
            }`}>
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
              </svg>
            </div>
            <div>
              <div className="font-semibold text-sm text-text-primary">Dark Mode</div>
              <div className="text-xs text-text-muted mt-0.5">Sleek, low-glare dark theme</div>
            </div>
          </div>
          <div className={`h-5 w-5 border flex items-center justify-center transition-colors ${
            resolvedTheme === "dark" ? "border-accent bg-accent text-white" : "border-border"
          }`}>
            {resolvedTheme === "dark" && (
              <svg className="w-3 h-3" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
              </svg>
            )}
          </div>
        </button>
      </div>
    </Section>
  );
}

// ─── Advanced ────────────────────────────────────────────────────────────────────

function AdvancedSection() {
  const { data: user, isLoading } = useMe();
  const { data: usage } = useUsage();
  const updateProfile = useUpdateProfile();
  const [limit, setLimit] = useState<string | null>(null);

  if (isDesktop) {
    return (
      <Section title="Advanced" description="Usage tracking and spending limits are account features — the desktop build has no server-side account, so there is nothing to show here.">
        <p className="text-sm text-text-muted">Nothing to configure.</p>
      </Section>
    );
  }

  if (isLoading || !user) return <div className="card h-56 animate-pulse" aria-hidden />;

  const limitNum = usage?.monthly_token_limit ?? user.monthly_token_limit;
  const used = usage?.month.tokens_total ?? 0;
  const pct = limitNum > 0 ? Math.min(100, (used / limitNum) * 100) : 0;
  const currentLimit = limit ?? String(user.monthly_token_limit ?? 0);
  const limitDirty = Number(currentLimit) !== user.monthly_token_limit;

  const saveLimit = async () => {
    try {
      await updateProfile.mutateAsync({ monthly_token_limit: Math.max(0, Number(currentLimit) || 0) });
      toast.success("Limit updated.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not update the limit.");
    }
  };

  return (
    <div className="space-y-6">
      <Section title="Token usage" description="Measured from your own sessions — the same numbers that bill against your key.">
        {limitNum > 0 && (
          <div className="mb-5 border border-border/80 bg-bg-surface/80 p-4">
            <div className="mb-2 flex items-baseline justify-between">
              <span className="text-xs font-semibold text-text-secondary uppercase tracking-wider font-mono">Monthly Budget</span>
              <span className="font-mono text-xs font-medium text-text-primary tabular-nums">
                {formatNumber(used)} / {formatNumber(limitNum)} tokens
              </span>
            </div>
            <div className="h-2 overflow-hidden bg-bg-elevated border border-border/60" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100} aria-label="Monthly token usage">
              <div className="h-full transition-[width] duration-500" style={{ width: `${pct}%`, backgroundColor: usage?.limit_reached ? "var(--danger)" : "var(--accent)" }} />
            </div>
            <p className="mt-2.5 font-mono text-xs text-text-muted">
              {usage?.limit_reached
                ? "Limit reached — new research is blocked until the 1st. Add your own key in Connections to keep going."
                : `${formatNumber(usage?.limit_remaining ?? limitNum - used)} remaining · resets on the 1st`}
            </p>
          </div>
        )}
        <div className="grid gap-3 sm:grid-cols-3">
          <UsageStat label="This month" sub="Resets on the 1st" window={usage?.month ?? EMPTY} />
          <UsageStat label="Last 7 days" sub="Rolling week" window={usage?.week ?? EMPTY} />
          <UsageStat label="Last session" sub="Most recent run" window={usage?.last_session ?? EMPTY} />
        </div>
      </Section>

      <Section
        title="Spending limit"
        description="A ceiling on tokens per calendar month. Research is blocked once you pass it."
        footer={
          <div className="flex items-center justify-between w-full">
            <span className="text-xs text-text-muted font-mono">0 means unlimited.</span>
            <button type="button" onClick={saveLimit} disabled={!limitDirty || updateProfile.isPending} className="btn btn-primary">
              {updateProfile.isPending && <span className="spinner" />}
              Save limit
            </button>
          </div>
        }
      >
        <Field label="Monthly token limit" htmlFor="limit">
          <input id="limit" type="number" min={0} step={10000} value={currentLimit} onChange={(e) => setLimit(e.target.value)} className="input-base max-w-xs font-mono" />
        </Field>
      </Section>
    </div>
  );
}

// ─── Search Providers ─────────────────────────────────────────────────────────────

function SearchProvidersSection() {
  const { data: user, isLoading } = useMe();
  const updateProfile = useUpdateProfile();

  const [tavilyInput, setTavilyInput] = useState<string | null>(null);
  const [braveInput, setBraveInput] = useState<string | null>(null);

  if (isLoading || !user) return <div className="card h-64 animate-pulse" aria-hidden />;

  const savedTavily = user.preferences.tavily_api_key ?? "";
  const savedBrave = user.preferences.brave_api_key ?? "";

  const tavilyValue = tavilyInput !== null ? tavilyInput : savedTavily;
  const braveValue = braveInput !== null ? braveInput : savedBrave;

  const tavilyDirty = tavilyInput !== null && tavilyInput !== savedTavily;
  const braveDirty = braveInput !== null && braveInput !== savedBrave;

  const saveTavily = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await updateProfile.mutateAsync({
        preferences: {
          tavily_api_key: tavilyValue.trim() || null,
        },
      });
      setTavilyInput(null);
      toast.success(tavilyValue.trim() ? "Tavily API key saved." : "Tavily API key removed.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not update Tavily key.");
    }
  };

  const saveBrave = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await updateProfile.mutateAsync({
        preferences: {
          brave_api_key: braveValue.trim() || null,
        },
      });
      setBraveInput(null);
      toast.success(braveValue.trim() ? "Brave API key saved." : "Brave API key removed.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not update Brave key.");
    }
  };

  const hasTavily = Boolean(savedTavily);
  const hasBrave = Boolean(savedBrave);

  return (
    <div className="space-y-6">
      {/* Chain Overview */}
      <Section
        title="Web Search Pipeline"
        description="The research engine uses an ordered fallback chain for live web queries. First responsive search engine wins."
      >
        <div className="border border-border/80 bg-bg-surface/80 p-4 shadow-xs">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
            {/* Step 1: Tavily */}
            <div className={`p-3.5 border flex items-center justify-between ${
              hasTavily ? "border-success/30 bg-success/5 text-text-primary" : "border-border/70 bg-bg-base/40 text-text-muted"
            }`}>
              <div className="flex items-center gap-2.5">
                <span className={`inline-block h-2 w-2 ${hasTavily ? "bg-success shadow-xs shadow-success/50" : "bg-text-muted"}`} />
                <span className="font-semibold">1. Tavily</span>
              </div>
              <span className={`font-mono text-[0.6875rem] px-2 py-0.5 ${hasTavily ? "bg-success/15 text-success font-medium" : "bg-bg-elevated text-text-muted"}`}>
                {hasTavily ? "Active" : "Not Set"}
              </span>
            </div>

            {/* Step 2: Brave */}
            <div className={`p-3.5 border flex items-center justify-between ${
              hasBrave ? "border-success/30 bg-success/5 text-text-primary" : "border-border/70 bg-bg-base/40 text-text-muted"
            }`}>
              <div className="flex items-center gap-2.5">
                <span className={`inline-block h-2 w-2 ${hasBrave ? "bg-success shadow-xs shadow-success/50" : "bg-text-muted"}`} />
                <span className="font-semibold">2. Brave</span>
              </div>
              <span className={`font-mono text-[0.6875rem] px-2 py-0.5 ${hasBrave ? "bg-success/15 text-success font-medium" : "bg-bg-elevated text-text-muted"}`}>
                {hasBrave ? "Active" : "Not Set"}
              </span>
            </div>

            {/* Step 3: DuckDuckGo */}
            <div className="p-3.5 border border-success/30 bg-success/5 text-text-primary flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <span className="inline-block h-2 w-2 bg-success shadow-xs shadow-success/50" />
                <span className="font-semibold">3. DuckDuckGo</span>
              </div>
              <span className="font-mono text-[0.6875rem] px-2 py-0.5 bg-success/15 text-success font-medium">
                Built-in
              </span>
            </div>
          </div>
        </div>
      </Section>

      {/* Tavily */}
      <form onSubmit={saveTavily}>
        <Section
          title="Tavily Search"
          description="AI-native search engine designed specifically for research agents. Provides real-time clean content snippets."
          footer={
            <div className="flex items-center justify-between w-full">
              <span className="font-mono text-xs text-text-muted">
                Get a key at{" "}
                <a href="https://app.tavily.com" target="_blank" rel="noopener noreferrer" className="text-accent hover:underline inline-flex items-center gap-1 font-medium">
                  app.tavily.com
                  <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" /></svg>
                </a>
              </span>
              <div className="flex items-center gap-2">
                {hasTavily && (
                  <button
                    type="button"
                    onClick={() => {
                      setTavilyInput("");
                      updateProfile.mutate({ preferences: { tavily_api_key: null } });
                      toast.success("Tavily key removed.");
                    }}
                    className="btn btn-ghost text-xs"
                  >
                    Remove key
                  </button>
                )}
                <button
                  type="submit"
                  disabled={!tavilyDirty || updateProfile.isPending}
                  className="btn btn-primary"
                >
                  {updateProfile.isPending && <span className="spinner" />}
                  Save key
                </button>
              </div>
            </div>
          }
        >
          <Field
            label="Tavily API Key"
            htmlFor="tavily-key"
            hint="Starts with tvly-... Key is stored securely with your account preferences."
          >
            <input
              id="tavily-key"
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={tavilyValue}
              onChange={(e) => setTavilyInput(e.target.value)}
              placeholder={hasTavily ? "••••••••••••••••" : "tvly-..."}
              className="input-base w-full font-mono text-sm"
            />
          </Field>
        </Section>
      </form>

      {/* Brave Search */}
      <form onSubmit={saveBrave}>
        <Section
          title="Brave Search API"
          description="Independent, privacy-first web search index. High-volume coverage."
          footer={
            <div className="flex items-center justify-between w-full">
              <span className="font-mono text-xs text-text-muted">
                Get a key at{" "}
                <a href="https://brave.com/search/api/" target="_blank" rel="noopener noreferrer" className="text-accent hover:underline inline-flex items-center gap-1 font-medium">
                  brave.com/search/api
                  <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" /></svg>
                </a>
              </span>
              <div className="flex items-center gap-2">
                {hasBrave && (
                  <button
                    type="button"
                    onClick={() => {
                      setBraveInput("");
                      updateProfile.mutate({ preferences: { brave_api_key: null } });
                      toast.success("Brave key removed.");
                    }}
                    className="btn btn-ghost text-xs"
                  >
                    Remove key
                  </button>
                )}
                <button
                  type="submit"
                  disabled={!braveDirty || updateProfile.isPending}
                  className="btn btn-primary"
                >
                  {updateProfile.isPending && <span className="spinner" />}
                  Save key
                </button>
              </div>
            </div>
          }
        >
          <Field
            label="Brave Search API Key"
            htmlFor="brave-key"
            hint="Subscription token from the Brave Search API developer console."
          >
            <input
              id="brave-key"
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={braveValue}
              onChange={(e) => setBraveInput(e.target.value)}
              placeholder={hasBrave ? "••••••••••••••••" : "BSA-..."}
              className="input-base w-full font-mono text-sm"
            />
          </Field>
        </Section>
      </form>

      {/* DuckDuckGo */}
      <Section
        title="DuckDuckGo (Zero-Config Fallback)"
        description="Built-in, keyless fallback search. Runs automatically when no API keys are provided or when providers encounter rate limits."
      >
        <div className="flex items-center gap-2.5 border border-success/30 bg-success/5 px-4 py-3.5 font-mono text-xs text-text-secondary">
          <span className="inline-block h-2 w-2 bg-success shadow-xs shadow-success/50" />
          <span className="font-semibold text-text-primary">Always Active</span>
          <span className="text-text-muted">— No API key or credit card required.</span>
        </div>
      </Section>
    </div>
  );
}

// ─── Router ──────────────────────────────────────────────────────────────────────

const SECTIONS: Record<string, () => JSX.Element> = {
  models: ModelsSection,
  connections: ConnectionsSection,
  search: SearchProvidersSection,
  research: ResearchSection,
  projects: ProjectsSection,
  appearance: AppearanceSection,
  advanced: AdvancedSection,
};

export function SectionContent({ section }: { section: string }) {
  const Content = SECTIONS[section];
  if (!Content) {
    return (
      <Section title="Not found" description="This settings section doesn't exist.">
        <Link href="/settings/models" className="text-sm text-accent hover:underline">← Back to Models</Link>
      </Section>
    );
  }
  return <Content />;
}
