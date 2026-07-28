"use client";

import { useState } from "react";
import toast from "react-hot-toast";

import { Avatar } from "@/components/Avatar";
import {
  useDeleteApiKey,
  useMe,
  useSetApiKey,
  useUpdateProfile,
  useUsage,
} from "@/hooks/queries";
import { ApiError } from "@/lib/api";
import { formatCost, formatNumber } from "@/lib/format";
import type { ApiKeyProvider, UsageWindow } from "@/lib/types";

const PROVIDERS: { value: ApiKeyProvider; label: string; help: string; url: string }[] = [
  {
    value: "anthropic",
    label: "Anthropic (Claude)",
    help: "Starts with sk-ant-",
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
    help: "Starts with sk-",
    url: "https://platform.openai.com/api-keys",
  },
];

function UsageCard({ title, subtitle, window }: { title: string; subtitle: string; window: UsageWindow }) {
  return (
    <div className="card">
      <div className="text-sm font-semibold text-text-primary">{title}</div>
      <div className="text-xs text-text-muted">{subtitle}</div>
      <div className="mt-3 font-mono text-2xl text-text-primary tabular-nums">
        {formatNumber(window.tokens_total)}
      </div>
      <div className="text-xs text-text-muted">tokens</div>
      <dl className="mt-3 space-y-1 border-t border-border pt-3 text-xs">
        <div className="flex justify-between">
          <dt className="text-text-muted">In / Out</dt>
          <dd className="text-text-secondary tabular-nums">
            {formatNumber(window.tokens_input)} / {formatNumber(window.tokens_output)}
          </dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-text-muted">Cost</dt>
          <dd className="text-text-secondary tabular-nums">{formatCost(window.cost_usd)}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-text-muted">Sessions</dt>
          <dd className="text-text-secondary tabular-nums">{window.sessions}</dd>
        </div>
      </dl>
    </div>
  );
}

export default function SettingsPage() {
  const { data: user, isLoading } = useMe();
  const { data: usage } = useUsage();
  const updateProfile = useUpdateProfile();
  const setApiKey = useSetApiKey();
  const deleteApiKey = useDeleteApiKey();

  const [name, setName] = useState("");
  const [avatar, setAvatar] = useState("");
  const [limit, setLimit] = useState("0");
  const [provider, setProvider] = useState<ApiKeyProvider>("anthropic");
  const [keyInput, setKeyInput] = useState("");
  const [copied, setCopied] = useState(false);

  // Seed the form from the server copy, and re-seed whenever it changes (React's
  // "adjust state when props change" pattern — a setState-in-effect would cause a
  // second render pass and is flagged by the hooks lint).
  const [seeded, setSeeded] = useState<string | null>(null);
  const seedKey = user
    ? [user.id, user.display_name, user.avatar_url, user.monthly_token_limit, user.api_key_provider].join("|")
    : null;
  if (user && seedKey !== seeded) {
    setSeeded(seedKey);
    setName(user.display_name ?? "");
    setAvatar(user.avatar_url ?? "");
    setLimit(String(user.monthly_token_limit ?? 0));
    if (user.api_key_provider) setProvider(user.api_key_provider);
  }

  if (isLoading || !user) {
    return (
      <div className="space-y-4">
        <div className="card h-32 animate-pulse" aria-hidden />
        <div className="card h-48 animate-pulse" aria-hidden />
        <span className="sr-only">Loading profile…</span>
      </div>
    );
  }

  const saveProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await updateProfile.mutateAsync({
        display_name: name.trim(),
        avatar_url: avatar.trim(),
        monthly_token_limit: Math.max(0, Number(limit) || 0),
      });
      toast.success("Profile saved.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not save profile.");
    }
  };

  const saveKey = async (e: React.FormEvent) => {
    e.preventDefault();
    const key = keyInput.trim();
    if (key.length < 8) return toast.error("That key looks too short.");
    try {
      await setApiKey.mutateAsync({ provider, api_key: key });
      setKeyInput(""); // never keep the plaintext key in component state
      toast.success("API key saved. Your research now runs on your key.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not save the key.");
    }
  };

  const removeKey = async () => {
    try {
      await deleteApiKey.mutateAsync();
      toast.success("API key removed.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not remove the key.");
    }
  };

  const copyId = async () => {
    try {
      await navigator.clipboard.writeText(user.id);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Couldn't access the clipboard.");
    }
  };

  const limitNum = usage?.monthly_token_limit ?? user.monthly_token_limit;
  const usedThisMonth = usage?.month.tokens_total ?? 0;
  const pct = limitNum > 0 ? Math.min(100, (usedThisMonth / limitNum) * 100) : 0;
  const selected = PROVIDERS.find((p) => p.value === provider)!;

  return (
    <div className="space-y-10">
      {/* ── Identity ─────────────────────────────────────────────────────── */}
      <section aria-labelledby="profile-heading">
        <h1 id="profile-heading" className="mb-4 text-xl font-semibold text-text-primary">
          Profile
        </h1>

        <div className="card">
          <div className="mb-6 flex items-center gap-4">
            <Avatar user={{ ...user, avatar_url: avatar || user.avatar_url }} size={64} />
            <div className="min-w-0">
              <div className="truncate text-lg font-semibold text-text-primary">
                {user.display_name || user.email}
              </div>
              <div className="truncate text-sm text-text-muted">{user.email}</div>
              <div className="mt-1 flex items-center gap-2">
                <code className="truncate font-mono text-xs text-text-muted">{user.id}</code>
                <button
                  type="button"
                  onClick={copyId}
                  className="shrink-0 text-xs text-accent hover:underline"
                >
                  {copied ? "Copied" : "Copy ID"}
                </button>
              </div>
            </div>
          </div>

          <form onSubmit={saveProfile} className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label htmlFor="name" className="mb-1.5 block text-sm font-medium text-text-secondary">
                  Display name
                </label>
                <input
                  id="name"
                  value={name}
                  onChange={(e) => setName(e.target.value.slice(0, 80))}
                  placeholder="Your name"
                  className="input-base"
                />
                <p className="mt-1 text-xs text-text-muted">
                  Used for your initials when you have no picture.
                </p>
              </div>

              <div>
                <label htmlFor="avatar" className="mb-1.5 block text-sm font-medium text-text-secondary">
                  Picture URL
                </label>
                <input
                  id="avatar"
                  type="url"
                  value={avatar}
                  onChange={(e) => setAvatar(e.target.value)}
                  placeholder="https://…  (leave blank for initials)"
                  className="input-base"
                />
                <p className="mt-1 text-xs text-text-muted">
                  Must be an https link to an image.
                </p>
              </div>
            </div>

            <div>
              <label htmlFor="limit" className="mb-1.5 block text-sm font-medium text-text-secondary">
                Monthly token limit
              </label>
              <input
                id="limit"
                type="number"
                min={0}
                step={1000}
                value={limit}
                onChange={(e) => setLimit(e.target.value)}
                className="input-base max-w-xs"
              />
              <p className="mt-1 text-xs text-text-muted">
                Research is blocked once you pass this in a calendar month.{" "}
                <strong className="font-medium">0 means unlimited.</strong>
              </p>
            </div>

            <button type="submit" disabled={updateProfile.isPending} className="btn btn-primary">
              {updateProfile.isPending && <span className="spinner" />}
              Save profile
            </button>
          </form>
        </div>
      </section>

      {/* ── Usage ────────────────────────────────────────────────────────── */}
      <section aria-labelledby="usage-heading">
        <h2 id="usage-heading" className="mb-1 text-lg font-semibold text-text-primary">
          Token usage
        </h2>
        <p className="mb-4 text-sm text-text-muted">
          Measured from your own sessions — the same numbers that bill against your key.
        </p>

        {limitNum > 0 && (
          <div className="card mb-4">
            <div className="mb-2 flex items-baseline justify-between text-sm">
              <span className="font-medium text-text-primary">This month</span>
              <span className="font-mono text-text-secondary tabular-nums">
                {formatNumber(usedThisMonth)} / {formatNumber(limitNum)}
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-bg-elevated">
              <div
                className="h-full rounded-full transition-all"
                style={{
                  width: `${pct}%`,
                  backgroundColor: usage?.limit_reached ? "var(--danger)" : "var(--accent)",
                }}
              />
            </div>
            <p className="mt-2 text-xs text-text-muted">
              {usage?.limit_reached
                ? "Limit reached — new research is blocked until the 1st, or add your own API key below."
                : `${formatNumber(usage?.limit_remaining ?? limitNum - usedThisMonth)} tokens remaining · resets on the 1st`}
            </p>
          </div>
        )}

        <div className="grid gap-3 sm:grid-cols-3">
          <UsageCard title="This month" subtitle="Resets on the 1st" window={usage?.month ?? EMPTY} />
          <UsageCard title="Last 7 days" subtitle="Rolling week" window={usage?.week ?? EMPTY} />
          <UsageCard title="Last session" subtitle="Most recent run" window={usage?.last_session ?? EMPTY} />
        </div>
      </section>

      {/* ── BYOK ─────────────────────────────────────────────────────────── */}
      <section aria-labelledby="key-heading">
        <h2 id="key-heading" className="mb-1 text-lg font-semibold text-text-primary">
          Your API key
        </h2>
        <p className="mb-4 text-sm text-text-muted">
          Bring your own key and your research runs on your provider account instead of this
          server&apos;s. The key is encrypted before it&apos;s stored and is never shown again.
        </p>

        <div className="card space-y-4">
          {user.api_key_provider ? (
            <div
              className="flex flex-wrap items-center justify-between gap-3 rounded-lg p-3"
              style={{ backgroundColor: "color-mix(in srgb, var(--success) 10%, transparent)" }}
            >
              <div className="text-sm">
                <span className="font-medium text-text-primary">
                  {PROVIDERS.find((p) => p.value === user.api_key_provider)?.label ??
                    user.api_key_provider}
                </span>{" "}
                <span className="font-mono text-text-muted">{user.api_key_hint}</span>
                <div className="text-xs text-text-muted">
                  Active — your research uses this key.
                </div>
              </div>
              <button
                type="button"
                onClick={removeKey}
                disabled={deleteApiKey.isPending}
                className="btn btn-danger px-3 py-1.5 text-sm"
              >
                {deleteApiKey.isPending && <span className="spinner" />}
                Remove
              </button>
            </div>
          ) : (
            <p className="rounded-lg bg-bg-elevated p-3 text-sm text-text-secondary">
              No key stored — research runs on this deployment&apos;s shared key, subject to your
              monthly limit.
            </p>
          )}

          <form onSubmit={saveKey} className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-[14rem_1fr]">
              <div>
                <label htmlFor="provider" className="mb-1.5 block text-sm font-medium text-text-secondary">
                  Provider
                </label>
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
              </div>

              <div>
                <label htmlFor="apikey" className="mb-1.5 block text-sm font-medium text-text-secondary">
                  {user.api_key_provider ? "Replace key" : "Paste your key"}
                </label>
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
                <p className="mt-1 text-xs text-text-muted">
                  Get one at{" "}
                  <a
                    href={selected.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-accent hover:underline"
                  >
                    {selected.label}
                  </a>
                  . Stored encrypted; we only ever show the last 4 characters.
                </p>
              </div>
            </div>

            <button
              type="submit"
              disabled={setApiKey.isPending || keyInput.trim().length < 8}
              className="btn btn-primary"
            >
              {setApiKey.isPending && <span className="spinner" />}
              {user.api_key_provider ? "Replace key" : "Save key"}
            </button>
          </form>
        </div>
      </section>
    </div>
  );
}

const EMPTY = {
  tokens_input: 0,
  tokens_output: 0,
  tokens_total: 0,
  cost_usd: 0,
  sessions: 0,
};
