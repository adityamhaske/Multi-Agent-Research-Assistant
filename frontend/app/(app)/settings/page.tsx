"use client";

import { useState } from "react";
import toast from "react-hot-toast";

import { AccountShell } from "@/components/account/AccountShell";
import { DesktopKeysCard } from "@/components/account/DesktopKeysCard";
import { LocalLLMCard } from "@/components/account/LocalLLMCard";
import { ModelPicker } from "@/components/account/ModelPicker";
import { Field, Section } from "@/components/account/Section";
import {
  useDeleteApiKey,
  useMe,
  useReadiness,
  useSetApiKey,
  useUpdateProfile,
  useUsage,
} from "@/hooks/queries";
import { ApiError } from "@/lib/api";
import { isDesktop } from "@/lib/desktop";
import { formatCost, formatNumber } from "@/lib/format";
import type { ApiKeyProvider, UsageWindow } from "@/lib/types";

const PROVIDERS: { value: ApiKeyProvider; label: string; help: string; url: string }[] = [
  {
    value: "anthropic",
    label: "Anthropic (Claude)",
    help: "sk-ant-…",
    url: "https://console.anthropic.com/settings/keys",
  },
  {
    value: "google",
    label: "Google (Gemini)",
    help: "From Google AI Studio",
    url: "https://aistudio.google.com/apikey",
  },
  {
    value: "openai",
    label: "OpenAI",
    help: "sk-…",
    url: "https://platform.openai.com/api-keys",
  },
  {
    value: "openrouter",
    label: "OpenRouter",
    help: "sk-or-…",
    url: "https://openrouter.ai/keys",
  },
  {
    value: "custom",
    label: "Custom Endpoint",
    help: "API Key / Bearer Token",
    url: "#",
  },
];

const EMPTY: UsageWindow = {
  tokens_input: 0,
  tokens_output: 0,
  tokens_total: 0,
  cost_usd: 0,
  sessions: 0,
};

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
        <span className="tabular-nums">
          {w.sessions} session{w.sessions === 1 ? "" : "s"}
        </span>
      </div>
    </div>
  );
}

/**
 * Desktop settings (docs/12 M9). There is no account on the desktop build — no
 * usage meters, no spending limits, no server-side BYOK — so the page keeps only
 * what exists locally: keychain keys, the local LLM bridge, and model routing.
 * Two components (not conditional hooks) keep both variants honest. Theme lives
 * only in the account menu's toggle now — a standalone Appearance section here
 * was a second, redundant place to do the same thing (docs/07 §2).
 */
function DesktopSettings() {
  return (
    <AccountShell title="Settings" description="Keys and preferences for this computer.">
      <DesktopKeysCard />

      <LocalLLMCard />

      <ModelPicker />
    </AccountShell>
  );
}

function WebSettings() {
  const { data: user, isLoading } = useMe();
  const { data: usage } = useUsage();
  const { data: readiness } = useReadiness();
  // Nothing configured yet: lead with the thing that makes the app work, and let usage
  // and spending limits wait their turn (docs/17 §8a). Absent data is treated as
  // configured — a slow request must not shuffle the page under someone mid-edit.
  const setupFirst = readiness ? !readiness.ready : false;
  const updateProfile = useUpdateProfile();
  const setApiKey = useSetApiKey();
  const deleteApiKey = useDeleteApiKey();

  const [limit, setLimit] = useState("0");
  const [provider, setProvider] = useState<ApiKeyProvider>("anthropic");
  const [keyInput, setKeyInput] = useState("");
  const [baseUrlInput, setBaseUrlInput] = useState("");

  const [seeded, setSeeded] = useState<string | null>(null);
  const seedKey = user ? `${user.id}|${user.monthly_token_limit}|${user.api_key_provider}` : null;
  if (user && seedKey !== seeded) {
    setSeeded(seedKey);
    setLimit(String(user.monthly_token_limit ?? 0));
    if (user.api_key_provider) setProvider(user.api_key_provider);
  }

  if (isLoading || !user) {
    return (
      <AccountShell title="Settings" description="Usage, keys, and preferences.">
        <div className="card h-56 animate-pulse" aria-hidden />
        <div className="card h-64 animate-pulse" aria-hidden />
      </AccountShell>
    );
  }

  const limitNum = usage?.monthly_token_limit ?? user.monthly_token_limit;
  const used = usage?.month.tokens_total ?? 0;
  const pct = limitNum > 0 ? Math.min(100, (used / limitNum) * 100) : 0;
  const selected = PROVIDERS.find((p) => p.value === provider)!;
  const limitDirty = Number(limit) !== user.monthly_token_limit;

  const saveLimit = async () => {
    try {
      await updateProfile.mutateAsync({ monthly_token_limit: Math.max(0, Number(limit) || 0) });
      toast.success("Limit updated.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not update the limit.");
    }
  };

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
      setKeyInput(""); // never keep plaintext in component state
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
    <AccountShell title="Settings" description="Usage, keys, and preferences.">
      {/* Says why the page is ordered the way it is. Without it the reshuffle looks like
          a glitch rather than the page helping. */}
      {setupFirst && (
        <div
          role="note"
          className="border px-4 py-3"
          style={{
            order: -3,
            borderColor: "color-mix(in srgb, var(--accent) 35%, var(--border))",
            backgroundColor: "color-mix(in srgb, var(--accent) 6%, var(--bg-surface))",
          }}
        >
          <p className="text-sm font-semibold text-text-primary">Finish setting up</p>
          <p className="mt-1 text-sm leading-relaxed text-text-secondary">
            Research needs one model source — a provider key below, or a local server.
            Everything else on this page is optional and can wait.
          </p>
        </div>
      )}

      {/* ── Usage ────────────────────────────────────────────────────────── */}
      <Section
        title="Token usage"
        description="Measured from your own sessions — the same numbers that bill against your key."
      >
        {limitNum > 0 && (
          <div className="mb-4">
            <div className="mb-2 flex items-baseline justify-between">
              <span className="text-[0.8125rem] font-medium text-text-secondary">This month</span>
              <span className="font-mono text-xs text-text-muted tabular-nums">
                {formatNumber(used)} / {formatNumber(limitNum)}
              </span>
            </div>
            <div
              className="h-1.5 overflow-hidden border border-border bg-bg-elevated"
              role="progressbar"
              aria-valuenow={Math.round(pct)}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label="Monthly token usage"
            >
              <div
                className="h-full transition-[width] duration-500"
                style={{
                  width: `${pct}%`,
                  backgroundColor: usage?.limit_reached ? "var(--danger)" : "var(--accent)",
                }}
              />
            </div>
            <p className="mt-2 font-mono text-xs text-text-muted">
              {usage?.limit_reached
                ? "Limit reached — new research is blocked until the 1st. Add your own key below to keep going."
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

      {/* ── BYOK ─────────────────────────────────────────────────────────── */}
      <form onSubmit={saveKey} style={setupFirst ? { order: -2 } : undefined}>
        <Section
          title="API key"
          description="Bring your own key and research runs on your provider account instead of this server's. It's encrypted before storage and never shown again."
          footer={
            <>
              <span className="font-mono text-xs text-text-muted">
                Only the last 4 characters are ever displayed.
              </span>
              <button
                type="submit"
                disabled={setApiKey.isPending || keyInput.trim().length < 8}
                className="btn btn-primary"
              >
                {setApiKey.isPending && <span className="spinner" />}
                {user.api_key_provider ? "Replace key" : "Save key"}
              </button>
            </>
          }
        >
          {user.api_key_provider ? (
            <div
              className="mb-5 flex flex-wrap items-center justify-between gap-3 border border-border bg-bg-surface px-4 py-3"
            >
              <div className="flex items-center gap-2.5">
                <span
                  aria-hidden
                  className="status-marker"
                  style={{ backgroundColor: "var(--success)" }}
                />
                <div className="text-[0.8125rem]">
                  <span className="font-medium text-text-primary">
                    {PROVIDERS.find((p) => p.value === user.api_key_provider)?.label}
                  </span>{" "}
                  <span className="font-mono text-text-muted">{user.api_key_hint}</span>
                  <div className="font-mono text-xs text-text-muted">Active — used for your research.</div>
                </div>
              </div>
              <button
                type="button"
                onClick={removeKey}
                disabled={deleteApiKey.isPending}
                className="btn btn-danger"
              >
                {deleteApiKey.isPending && <span className="spinner" />}
                Remove
              </button>
            </div>
          ) : (
            <p className="mb-5 border border-border bg-bg-surface px-4 py-3 font-mono text-xs text-text-secondary">
              No key stored — research runs on this deployment&apos;s shared key, subject to your
              monthly limit.
            </p>
          )}

          <div className="grid gap-4 sm:grid-cols-[13rem_1fr]">
            <Field label="Provider" htmlFor="provider">
              <select
                id="provider"
                value={provider}
                onChange={(e) => setProvider(e.target.value as ApiKeyProvider)}
                className="input-base"
              >
                {PROVIDERS.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
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
                  <>
                    Get one from{" "}
                    <a
                      href={selected.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-medium text-accent hover:underline"
                    >
                      {selected.label}
                    </a>
                    .
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
              <Field
                label="Base URL"
                htmlFor="baseurl"
                hint="Used when selecting a 'custom:...' model route."
              >
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

      {/* ── Limits ───────────────────────────────────────────────────────── */}
      <Section
        title="Spending limit"
        description="A ceiling on tokens per calendar month. Research is blocked once you pass it."
        footer={
          <>
            <span className="text-xs text-text-muted">0 means unlimited.</span>
            <button
              type="button"
              onClick={saveLimit}
              disabled={!limitDirty || updateProfile.isPending}
              className="btn btn-primary"
            >
              {updateProfile.isPending && <span className="spinner" />}
              Save limit
            </button>
          </>
        }
      >
        <Field label="Monthly token limit" htmlFor="limit">
          <input
            id="limit"
            type="number"
            min={0}
            step={10000}
            value={limit}
            onChange={(e) => setLimit(e.target.value)}
            className="input-base max-w-xs font-mono"
          />
        </Field>
      </Section>

      {/* ── Preferences ──────────────────────────────────────────────────── */}
      {/* Grouped so the two model cards move together and keep their spacing. Local
          models sit directly under the key form during setup, because "free, already on
          your machine" is the better first option to offer. */}
      <div className="flex flex-col gap-5" style={setupFirst ? { order: -1 } : undefined}>
        <LocalLLMCard />
        <ModelPicker />
      </div>
    </AccountShell>
  );
}

export default function SettingsPage() {
  // Build-time constant: the web bundle dead-code-eliminates the desktop branch.
  return isDesktop ? <DesktopSettings /> : <WebSettings />;
}
