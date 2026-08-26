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
    <div className="border border-border bg-bg-surface px-4 py-3.5">
      <div className="font-mono text-xs font-semibold uppercase tracking-wider text-text-secondary">{label}</div>
      <div className="font-mono text-[0.6875rem] text-text-muted">{sub}</div>
      <div className="mt-2.5 font-mono text-xl font-medium tracking-tight text-text-primary tabular-nums">
        {formatNumber(w.tokens_total)}
      </div>
      <div className="mt-1.5 flex items-center gap-2 font-mono text-[0.6875rem] text-text-muted">
        <span className="tabular-nums">{formatCost(w.cost_usd)}</span>
        <span aria-hidden>·</span>
        <span className="tabular-nums">{w.sessions} session{w.sessions === 1 ? "" : "s"}</span>
      </div>
    </div>
  );
}

// ─── Models ──────────────────────────────────────────────────────────────────────

function ModelsSection() {
  return (
    <>
      {/* Ordered the way the run form resolves a backend: custom endpoint, then local,
          then the catalogued API providers in the picker. */}
      <CustomEndpointCard />
      <LocalLLMCard />
      <ModelPicker />
    </>
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
        <button type="button" onClick={save} disabled={!dirty || updateProfile.isPending} className="btn btn-primary">
          {updateProfile.isPending && <span className="spinner" />}
          Save
        </button>
      }
    >
      <div className="space-y-4">
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
  const { data: user } = useMe();
  const updateProfile = useUpdateProfile();
  const density = user?.preferences.density ?? "comfortable";

  const setDensity = async (value: "comfortable" | "compact") => {
    try {
      await updateProfile.mutateAsync({ preferences: { density: value } });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not save.");
    }
  };

  return (
    <>
      <Section title="Theme" description="Choose how the interface looks on this device.">
        <div className="segmented" role="radiogroup" aria-label="Theme">
          {(["light", "dark"] as const).map((t) => (
            <button
              key={t}
              type="button"
              role="radio"
              aria-checked={resolvedTheme === t}
              onClick={() => setTheme(t)}
              className="segmented-item capitalize font-mono text-xs"
            >
              {t}
            </button>
          ))}
        </div>
      </Section>
      <Section title="Density" description="Compact tightens spacing in long lists and the activity feed.">
        <div className="segmented" role="radiogroup" aria-label="Density">
          {(["comfortable", "compact"] as const).map((d) => (
            <button
              key={d}
              type="button"
              role="radio"
              aria-checked={density === d}
              onClick={() => setDensity(d)}
              className="segmented-item capitalize font-mono text-xs"
            >
              {d}
            </button>
          ))}
        </div>
      </Section>
    </>
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
    <>
      <Section title="Token usage" description="Measured from your own sessions — the same numbers that bill against your key.">
        {limitNum > 0 && (
          <div className="mb-4">
            <div className="mb-2 flex items-baseline justify-between">
              <span className="text-[0.8125rem] font-medium text-text-secondary">This month</span>
              <span className="font-mono text-xs text-text-muted tabular-nums">{formatNumber(used)} / {formatNumber(limitNum)}</span>
            </div>
            <div className="h-1.5 overflow-hidden border border-border bg-bg-elevated" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100} aria-label="Monthly token usage">
              <div className="h-full transition-[width] duration-500" style={{ width: `${pct}%`, backgroundColor: usage?.limit_reached ? "var(--danger)" : "var(--accent)" }} />
            </div>
            <p className="mt-2 font-mono text-xs text-text-muted">
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
          <>
            <span className="text-xs text-text-muted">0 means unlimited.</span>
            <button type="button" onClick={saveLimit} disabled={!limitDirty || updateProfile.isPending} className="btn btn-primary">
              {updateProfile.isPending && <span className="spinner" />}
              Save limit
            </button>
          </>
        }
      >
        <Field label="Monthly token limit" htmlFor="limit">
          <input id="limit" type="number" min={0} step={10000} value={currentLimit} onChange={(e) => setLimit(e.target.value)} className="input-base max-w-xs font-mono" />
        </Field>
      </Section>
    </>
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
    <>
      {/* Chain Overview */}
      <Section
        title="Web Search Pipeline"
        description="The research engine uses an ordered fallback chain for live web queries. First responsive search engine wins."
      >
        <div className="border border-border bg-bg-surface p-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between text-xs font-mono">
            <div className="flex items-center gap-2">
              <span className={`inline-block h-2 w-2 rounded-full ${hasTavily ? "bg-success" : "bg-text-muted"}`} />
              <span className="font-semibold text-text-primary">1. Tavily</span>
              <span className="text-text-muted">({hasTavily ? "Active" : "Not configured"})</span>
            </div>
            <span className="text-text-muted hidden sm:inline">→</span>
            <div className="flex items-center gap-2">
              <span className={`inline-block h-2 w-2 rounded-full ${hasBrave ? "bg-success" : "bg-text-muted"}`} />
              <span className="font-semibold text-text-primary">2. Brave Search</span>
              <span className="text-text-muted">({hasBrave ? "Active" : "Not configured"})</span>
            </div>
            <span className="text-text-muted hidden sm:inline">→</span>
            <div className="flex items-center gap-2">
              <span className="inline-block h-2 w-2 rounded-full bg-success" />
              <span className="font-semibold text-text-primary">3. DuckDuckGo</span>
              <span className="text-success font-medium">(Always Ready)</span>
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
            <>
              <span className="font-mono text-xs text-text-muted">
                Get a key at{" "}
                <a href="https://app.tavily.com" target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">
                  app.tavily.com
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
                    className="btn btn-ghost"
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
            </>
          }
        >
          <Field
            label="Tavily API Key"
            htmlFor="tavily-key"
            hint="Starts with tvly-... Key is stored with your account preferences."
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
            <>
              <span className="font-mono text-xs text-text-muted">
                Get a key at{" "}
                <a href="https://brave.com/search/api/" target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">
                  brave.com/search/api
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
                    className="btn btn-ghost"
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
            </>
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
        <div className="flex items-center gap-2 border border-border bg-bg-surface px-4 py-3 font-mono text-xs text-text-secondary">
          <span className="inline-block h-2 w-2 rounded-full bg-success" />
          <span>Active — No API key or credit card required.</span>
        </div>
      </Section>
    </>
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
