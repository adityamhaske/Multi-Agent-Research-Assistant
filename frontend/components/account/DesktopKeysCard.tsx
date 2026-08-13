"use client";

import { useState } from "react";
import toast from "react-hot-toast";

import { useDeleteDesktopKey, useDesktopKeys, useSetDesktopKey, useDesktopCustomEndpoint, useSetDesktopCustomEndpoint } from "@/hooks/queries";
import { ApiError } from "@/lib/api";
import type { ApiKeyProvider } from "@/lib/types";

import { Section } from "./Section";

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

/**
 * Desktop BYOK (docs/12 M9). Unlike the server — one key on the user row — the
 * desktop keeps a key per provider in the OS keychain, so several providers can be
 * available at once and the model picker enables each one independently. Keys are
 * sent to the local sidecar over loopback and never shown again; the UI only ever
 * sees the keychain/environment hints.
 */
export function DesktopKeysCard() {
  const { data: keys, isLoading } = useDesktopKeys();
  const setKey = useSetDesktopKey();
  const deleteKey = useDeleteDesktopKey();
  const [inputs, setInputs] = useState<Record<string, string>>({});

  const { data: customEndpoint } = useDesktopCustomEndpoint();
  const setCustomEndpoint = useSetDesktopCustomEndpoint();
  const [baseUrlInput, setBaseUrlInput] = useState<string | null>(null);

  const activeBaseUrl = baseUrlInput ?? customEndpoint?.base_url ?? "";

  const save = async (provider: ApiKeyProvider) => {
    const key = (inputs[provider] ?? "").trim();
    if (key.length < 8) {
      toast.error("That key looks too short.");
      return;
    }
    try {
      await setKey.mutateAsync({ provider, key });
      setInputs((s) => ({ ...s, [provider]: "" })); // never keep plaintext in state
      toast.success("Key saved to the OS keychain.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not save the key.");
    }
  };

  const remove = async (provider: ApiKeyProvider) => {
    try {
      await deleteKey.mutateAsync(provider);
      toast.success("Key removed from the keychain.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not remove the key.");
    }
  };

  const saveBaseUrl = async () => {
    try {
      await setCustomEndpoint.mutateAsync(activeBaseUrl);
      toast.success("Custom endpoint saved.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not save the custom endpoint.");
    }
  };

  return (
    <Section
      title="Provider keys"
      description="Paste a key for each provider you want to use. Keys are stored in this computer's OS keychain, sent only to the local research service, and never shown again."
    >
      {isLoading || !keys ? (
        <div className="card h-24 animate-pulse" aria-hidden />
      ) : (
        <div className="space-y-4">
          {PROVIDERS.map((p) => {
            const status = keys[p.value];
            const busy =
              setKey.isPending || (deleteKey.isPending && deleteKey.variables === p.value);
            return (
              <div
                key={p.value}
                className="flex flex-wrap items-center gap-3 border border-border bg-bg-surface px-4 py-3"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs font-semibold uppercase tracking-wider text-text-primary">
                      {p.label}
                    </span>
                    {status.keychain && (
                      <span
                        className="px-2 py-0.5 font-mono text-[0.6875rem] font-semibold border"
                        style={{
                          color: "var(--success)",
                          backgroundColor: "color-mix(in srgb, var(--success) 10%, var(--bg-surface))",
                          borderColor: "color-mix(in srgb, var(--success) 30%, var(--border))",
                        }}
                      >
                        Keychain
                      </span>
                    )}
                    {status.environment && (
                      <span
                        className="px-2 py-0.5 font-mono text-[0.6875rem] font-semibold border"
                        style={{
                          color: "var(--text-muted)",
                          backgroundColor: "var(--bg-elevated)",
                          borderColor: "var(--border)",
                        }}
                      >
                        Environment
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 text-xs text-text-muted">
                    Get one from{" "}
                    <a
                      href={p.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-mono text-xs font-medium text-accent hover:underline"
                    >
                      {p.label}
                    </a>
                    .
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <input
                    type="password"
                    autoComplete="off"
                    spellCheck={false}
                    aria-label={`${p.label} API key`}
                    value={inputs[p.value] ?? ""}
                    onChange={(e) => setInputs((s) => ({ ...s, [p.value]: e.target.value }))}
                    placeholder={status.keychain ? "Replace key…" : p.help}
                    className="input-base w-56 font-mono"
                  />
                  <button
                    type="button"
                    onClick={() => save(p.value)}
                    disabled={busy || (inputs[p.value] ?? "").trim().length < 8}
                    className="btn btn-primary"
                  >
                    {busy && <span className="spinner" />}
                    {status.keychain ? "Replace" : "Save"}
                  </button>
                  {status.keychain && (
                    <button
                      type="button"
                      onClick={() => remove(p.value)}
                      disabled={busy}
                      className="btn btn-danger"
                    >
                      Remove
                    </button>
                  )}
                </div>
              </div>
            );
          })}

          <div className="flex flex-col gap-2 border border-border bg-bg-surface px-4 py-3">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs font-semibold uppercase tracking-wider text-text-primary">
                Custom Endpoint Base URL
              </span>
            </div>
            <div className="mt-0.5 font-mono text-xs text-text-muted mb-2">
              Used when selecting a "custom:..." model route.
            </div>
            <div className="flex items-center gap-2">
              <input
                type="url"
                autoComplete="off"
                spellCheck={false}
                aria-label="Custom Base URL"
                value={activeBaseUrl}
                onChange={(e) => setBaseUrlInput(e.target.value)}
                placeholder="https://api.together.xyz/v1"
                className="input-base min-w-[20rem] flex-1 font-mono"
              />
              <button
                type="button"
                onClick={saveBaseUrl}
                disabled={setCustomEndpoint.isPending || activeBaseUrl === (customEndpoint?.base_url ?? "")}
                className="btn btn-primary"
              >
                {setCustomEndpoint.isPending && <span className="spinner" />}
                Save URL
              </button>
            </div>
          </div>
        </div>
      )}
    </Section>
  );
}
