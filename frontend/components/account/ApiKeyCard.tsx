"use client";

import { useState } from "react";
import toast from "react-hot-toast";

import {
  useDeleteApiKey,
  useMe,
  useProviderHealth,
  useSetApiKey,
  useSetApiKeyLabel,
} from "@/hooks/queries";
import { ApiError } from "@/lib/api";
import type { ApiKeyProvider } from "@/lib/types";

import { ConnectionStatus } from "./ConnectionStatus";
import { Field, Section } from "./Section";

/**
 * Web BYOK: the account's single active provider connection (docs/06 §1, docs/07 §2).
 *
 * Extracted from the Settings page module so it can be unit-tested — `app/**` is
 * outside vitest's `include` glob (`{lib,components,hooks}/**`, docs/07 §2), the same
 * reason the Overview page's logic lives in `lib/` rather than in `app/(app)/project/`.
 */

const PROVIDERS: { value: ApiKeyProvider; label: string; help: string; url: string }[] = [
  { value: "anthropic", label: "Anthropic (Claude)", help: "sk-ant-…", url: "https://console.anthropic.com/settings/keys" },
  { value: "google", label: "Google (Gemini)", help: "From Google AI Studio", url: "https://aistudio.google.com/apikey" },
  { value: "openai", label: "OpenAI", help: "sk-…", url: "https://platform.openai.com/api-keys" },
  { value: "openrouter", label: "OpenRouter", help: "sk-or-…", url: "https://openrouter.ai/keys" },
  { value: "custom", label: "Custom Endpoint", help: "API Key / Bearer Token", url: "#" },
];

export function ApiKeyCard() {
  const { data: user, isLoading } = useMe();
  const setApiKey = useSetApiKey();
  const deleteApiKey = useDeleteApiKey();
  const setApiKeyLabel = useSetApiKeyLabel();
  const [provider, setProvider] = useState<ApiKeyProvider>("anthropic");
  const [keyInput, setKeyInput] = useState("");
  const [baseUrlInput, setBaseUrlInput] = useState("");
  // null = not editing. Seeded from the saved nickname when opened, so the field
  // shows what's actually stored rather than starting blank beside a named connection.
  const [labelDraft, setLabelDraft] = useState<string | null>(null);
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

  const renameKey = async () => {
    if (labelDraft === null) return;
    try {
      await setApiKeyLabel.mutateAsync(labelDraft.trim());
      setLabelDraft(null);
      toast.success("Renamed.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not rename.");
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
              <span className="font-medium text-text-primary">
                {user.api_key_label || activeProvider.label}
              </span>{" "}
              <span className="font-mono text-text-muted">{user.api_key_hint}</span>
              {/* The catalog label ("Custom Endpoint") is shared by every user routed
                  through this provider — shown alongside a nickname, not replaced by
                  it, so "which kind of connection is this" stays answerable too. */}
              {user.api_key_label && (
                <span className="ml-1 font-mono text-[0.6875rem] text-text-muted">
                  ({activeProvider.label})
                </span>
              )}

              {labelDraft !== null ? (
                <div className="mt-2 flex items-center gap-2">
                  <input
                    autoFocus
                    type="text"
                    value={labelDraft}
                    onChange={(e) => setLabelDraft(e.target.value)}
                    onKeyDown={(e) => {
                      // type="button" siblings already keep Enter from reaching the
                      // page's outer save-key <form>, but a text input submits its
                      // enclosing form on Enter regardless of a sibling's type — this
                      // is the guard that actually stops that submit.
                      if (e.key === "Enter") {
                        e.preventDefault();
                        renameKey();
                      }
                      if (e.key === "Escape") setLabelDraft(null);
                    }}
                    placeholder={activeProvider.label}
                    maxLength={60}
                    aria-label="Connection nickname"
                    className="input-base w-48 font-mono text-xs"
                  />
                  <button
                    type="button"
                    onClick={renameKey}
                    disabled={setApiKeyLabel.isPending}
                    className="font-mono text-xs text-accent hover:underline disabled:opacity-50"
                  >
                    {setApiKeyLabel.isPending && <span className="spinner" />}
                    Save
                  </button>
                  <button
                    type="button"
                    onClick={() => setLabelDraft(null)}
                    className="font-mono text-xs text-text-muted hover:underline"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setLabelDraft(user.api_key_label ?? "")}
                  className="mt-2 block font-mono text-xs text-accent hover:underline"
                >
                  Rename
                </button>
              )}

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
