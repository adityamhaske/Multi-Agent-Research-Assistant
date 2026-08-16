"use client";

import { useTheme } from "next-themes";
import Link from "next/link";
import { useState, type JSX } from "react";
import toast from "react-hot-toast";

import { ConnectionStatus } from "@/components/account/ConnectionStatus";
import { DesktopKeysCard } from "@/components/account/DesktopKeysCard";
import { LocalLLMCard } from "@/components/account/LocalLLMCard";
import { ModelPicker } from "@/components/account/ModelPicker";
import { Field, Section } from "@/components/account/Section";
import { ResetToDefault } from "@/components/settings/ResetToDefault";
import {
  useDeleteApiKey,
  useMe,
  useProviderHealth,
  useSetApiKey,
  useUpdateProfile,
  useUsage,
} from "@/hooks/queries";
import { ApiError } from "@/lib/api";
import { isDesktop } from "@/lib/desktop";
import { formatCost, formatNumber } from "@/lib/format";
import type { ApiKeyProvider, UsageWindow } from "@/lib/types";

const PROVIDERS: { value: ApiKeyProvider; label: string; help: string; url: string }[] = [
  { value: "anthropic", label: "Anthropic (Claude)", help: "sk-ant-…", url: "https://console.anthropic.com/settings/keys" },
  { value: "google", label: "Google (Gemini)", help: "From Google AI Studio", url: "https://aistudio.google.com/apikey" },
  { value: "openai", label: "OpenAI", help: "sk-…", url: "https://platform.openai.com/api-keys" },
  { value: "openrouter", label: "OpenRouter", help: "sk-or-…", url: "https://openrouter.ai/keys" },
  { value: "custom", label: "Custom Endpoint", help: "API Key / Bearer Token", url: "#" },
];

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
      <LocalLLMCard />
      <ModelPicker />
    </>
  );
}

// ─── Connections ─────────────────────────────────────────────────────────────────

function WebConnectionsSection() {
  const { data: user, isLoading } = useMe();
  const setApiKey = useSetApiKey();
  const deleteApiKey = useDeleteApiKey();
  const [provider, setProvider] = useState<ApiKeyProvider>("anthropic");
  const [keyInput, setKeyInput] = useState("");
  const [baseUrlInput, setBaseUrlInput] = useState("");
  const providerHealth = useProviderHealth(user?.api_key_provider ?? null, false);

  if (isLoading || !user) {
    return <div className="card h-64 animate-pulse" aria-hidden />;
  }

  const selected = PROVIDERS.find((p) => p.value === provider)!;
  const activeProvider = user.api_key_provider
    ? PROVIDERS.find((p) => p.value === user.api_key_provider)
    : null;

  const saveKey = async (e: React.FormEvent) => {
    e.preventDefault();
    const key = keyInput.trim();
    const base_url = baseUrlInput.trim();
    if (key.length < 8) return toast.error("That key looks too short.");
    try {
      await setApiKey.mutateAsync({
        provider,
        api_key: key,
        ...(provider === "custom" && base_url ? { api_base_url: base_url } : {}),
      });
      setKeyInput("");
      toast.success("Key saved. Your research now runs on your account.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not save the key.");
    }
  };

  const removeKey = async () => {
    try {
      await deleteApiKey.mutateAsync();
      toast.success("Key removed.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not remove the key.");
    }
  };

  return (
    <form onSubmit={saveKey}>
      <Section
        title="API key"
        description="Bring your own key and research runs on your provider account instead of this server's. It's encrypted before storage and never shown again."
        footer={
          <>
            <span className="font-mono text-xs text-text-muted">Only the last 4 characters are ever displayed.</span>
            <button type="submit" disabled={setApiKey.isPending || keyInput.trim().length < 8} className="btn btn-primary">
              {setApiKey.isPending && <span className="spinner" />}
              {user.api_key_provider ? "Replace key" : "Save key"}
            </button>
          </>
        }
      >
        {activeProvider ? (
          <div className="mb-5 flex flex-wrap items-start justify-between gap-3 border border-border bg-bg-surface px-4 py-3">
            <div className="min-w-0 text-[0.8125rem]">
              <span className="font-medium text-text-primary">{activeProvider.label}</span>{" "}
              <span className="font-mono text-text-muted">{user.api_key_hint}</span>
              <div className="mt-2">
                <ConnectionStatus
                  verdict={providerHealth.data ?? setApiKey.data?.connection_verdict ?? null}
                  loading={providerHealth.isFetching}
                  retesting={providerHealth.isFetching}
                  onRetest={() => providerHealth.refetch()}
                />
              </div>
            </div>
            <button type="button" onClick={removeKey} disabled={deleteApiKey.isPending} className="btn btn-danger shrink-0">
              {deleteApiKey.isPending && <span className="spinner" />}
              Remove
            </button>
          </div>
        ) : (
          <p className="mb-5 border border-border bg-bg-surface px-4 py-3 font-mono text-xs text-text-secondary">
            No key stored — research runs on this deployment&apos;s shared key, subject to your monthly limit.
          </p>
        )}

        <div className="grid gap-4 sm:grid-cols-[13rem_1fr]">
          <Field label="Provider" htmlFor="provider">
            <select id="provider" value={provider} onChange={(e) => setProvider(e.target.value as ApiKeyProvider)} className="input-base">
              {PROVIDERS.map((p) => (
                <option key={p.value} value={p.value}>{p.label}</option>
              ))}
            </select>
          </Field>
          <Field
            label={user.api_key_provider ? "Replace with a new key" : "Paste your key"}
            htmlFor="apikey"
            hint={
              provider === "custom" ? (
                <>The bearer token for the endpoint.</>
              ) : (
                <>Get one from{" "}
                  <a href={selected.url} target="_blank" rel="noopener noreferrer" className="font-medium text-accent hover:underline">
                    {selected.label}
                  </a>.
                </>
              )
            }
          >
            <input
              id="apikey"
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={keyInput}
              onChange={(e) => setKeyInput(e.target.value)}
              placeholder={selected.help}
              className="input-base font-mono"
            />
          </Field>
        </div>

        {provider === "custom" && (
          <div className="mt-4">
            <Field label="Base URL" htmlFor="baseurl" hint="Used when selecting a 'custom:...' model route.">
              <input
                id="baseurl"
                type="url"
                autoComplete="off"
                spellCheck={false}
                value={baseUrlInput}
                onChange={(e) => setBaseUrlInput(e.target.value)}
                placeholder="https://api.together.xyz/v1"
                className="input-base w-full max-w-md font-mono"
              />
            </Field>
          </div>
        )}
      </Section>
    </form>
  );
}

function ConnectionsSection() {
  return isDesktop ? <DesktopKeysCard /> : <WebConnectionsSection />;
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

// ─── Corpus / Exports (light — no dedicated settings exist yet) ───────────────────

function CorpusSection() {
  return (
    <Section title="Corpus" description="Manage the documents research can cite and, in airgapped mode, must cite exclusively.">
      <p className="text-sm text-text-secondary">
        Upload, remove, and inspect documents from the{" "}
        <Link href="/corpus" className="text-accent hover:underline">Corpus</Link> page — restricting a run to
        it is a per-run choice on the research form, not a global setting.
      </p>
    </Section>
  );
}

function ExportsSection() {
  return (
    <Section title="Exports" description="What a downloaded report carries.">
      <p className="text-sm text-text-secondary">
        Every export (.md, PDF, .bundle.json) includes the full citation table and, once
        resolved, the per-role model breakdown automatically — nothing to configure yet.
        Export a report from its own page once research completes.
      </p>
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

// ─── Router ──────────────────────────────────────────────────────────────────────

const SECTIONS: Record<string, () => JSX.Element> = {
  models: ModelsSection,
  connections: ConnectionsSection,
  research: ResearchSection,
  corpus: CorpusSection,
  exports: ExportsSection,
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
