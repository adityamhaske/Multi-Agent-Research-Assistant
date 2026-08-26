"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import toast from "react-hot-toast";

import {
  pullLocalModel,
  useLocalLLMStatus,
  useStartLocalServer,
  useStopLocalServer,
} from "@/hooks/queries";
import { isDesktop } from "@/lib/desktop";
import type { LocalModelInfo, PullProgress } from "@/lib/types";

import { Section } from "./Section";

/**
 * Local model server status and one-click setup (docs/07 §2, Phase 2b; docs/12 M15).
 *
 * Honest boundary: the web build guides, the desktop build acts. A user is told which
 * they are on rather than handed a button that cannot work — the web build cannot
 * spawn a process on someone else's machine, so it shows the install command instead
 * of a "Start" button, and polls every 2s so the card updates itself the moment a
 * manually-started server appears.
 */

// Comfortably above `_MIN_RESEARCH_PARAMS_B` in `local_llm.py` — big enough to pass
// the structured-evidence step, small enough to be a reasonable first download.
const RECOMMENDED_MODEL = "qwen2.5:14b";

function statusTone(reachable: boolean, usable: boolean) {
  if (usable) return { label: "Connected", color: "var(--success)" };
  if (reachable) return { label: "No models", color: "var(--warning)" };
  return { label: "Not detected", color: "var(--text-muted)" };
}

function formatSize(bytes: number | null) {
  if (!bytes) return null;
  const gb = bytes / 1_000_000_000;
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${Math.round(bytes / 1_000_000)} MB`;
}

/** Three distinct kinds, because "not research ready" has two different causes. */
function modelBadge(model: LocalModelInfo) {
  if (model.is_embedding) {
    return {
      label: "embedding",
      tone: "var(--text-muted)",
      title: "Powers retrieval. Cannot be used as a planner/executor/critic/chat model.",
    };
  }
  if (model.likely_underpowered) {
    return {
      label: "chat only",
      tone: "var(--warning)",
      title:
        "Small models usually fail the research pipeline's structured-evidence step. Fine for chat.",
    };
  }
  return { label: "research ready", tone: "var(--success)", title: undefined };
}

function ModelRow({ model }: { model: LocalModelInfo }) {
  const size = formatSize(model.size_bytes);
  const badge = modelBadge(model);
  return (
    <li className="flex flex-wrap items-center gap-x-2.5 gap-y-1 py-2 font-mono text-xs">
      <code className="text-[0.8125rem] font-semibold text-text-primary">{model.name}</code>
      {size && <span className="text-[0.6875rem] text-text-muted tabular-nums">{size}</span>}
      <span
        className="px-2 py-0.5 text-[0.6875rem] uppercase tracking-wider font-semibold border"
        style={{
          backgroundColor: `color-mix(in srgb, ${badge.tone} 10%, var(--bg-surface))`,
          borderColor: `color-mix(in srgb, ${badge.tone} 30%, var(--border))`,
          color: badge.tone,
        }}
        title={badge.title}
      >
        {badge.label}
      </span>
      {model.route && !model.is_embedding && (
        <code className="ml-auto text-[0.6875rem] text-text-muted">{model.route}</code>
      )}
    </li>
  );
}

/** OS-detected install command for the web build — client-only, so it renders after
 * mount rather than guessing on the server. */
function detectOS(): "mac" | "windows" | "linux" | "unknown" {
  if (typeof navigator === "undefined") return "unknown";
  const ua = navigator.userAgent;
  if (/Mac/i.test(ua)) return "mac";
  if (/Win/i.test(ua)) return "windows";
  if (/Linux/i.test(ua)) return "linux";
  return "unknown";
}

const INSTALL: Record<string, { command?: string; url: string; label: string }> = {
  mac: {
    command: "curl -fsSL https://ollama.com/install.sh | sh",
    url: "https://ollama.com/download/mac",
    label: "Download for macOS",
  },
  linux: {
    command: "curl -fsSL https://ollama.com/install.sh | sh",
    url: "https://ollama.com/download/linux",
    label: "Download for Linux",
  },
  windows: { url: "https://ollama.com/download/windows", label: "Download for Windows" },
  unknown: { url: "https://ollama.com/download", label: "Download Ollama" },
};

function WebInstallGuide() {
  const info = INSTALL[detectOS()];
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    if (!info.command) return;
    try {
      await navigator.clipboard.writeText(info.command);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Couldn't access the clipboard.");
    }
  };

  return (
    <div className="space-y-2 border border-border bg-bg-surface px-3 py-2.5">
      <p className="text-xs leading-relaxed text-text-secondary">
        The web build can&apos;t start a process on your machine — install Ollama and run it
        yourself. This card checks every couple of seconds and updates the moment it finds it.
      </p>
      {info.command && (
        <div className="flex items-center gap-2">
          <code className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap border border-border bg-bg-elevated px-2 py-1.5 font-mono text-[0.6875rem]">
            {info.command}
          </code>
          <button
            type="button"
            onClick={copy}
            className="btn btn-secondary shrink-0 px-2 py-1 text-xs"
          >
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      )}
      <a
        href={info.url}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-block text-xs text-accent hover:underline"
      >
        {info.label} →
      </a>
    </div>
  );
}

function PullButton({ model, disabled }: { model: string; disabled?: boolean }) {
  const [progress, setProgress] = useState<PullProgress | null>(null);
  const [pulling, setPulling] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const start = async () => {
    setPulling(true);
    setProgress(null);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await pullLocalModel(
        model,
        (p) => {
          setProgress(p);
          if (p.error) toast.error(p.error);
        },
        controller.signal,
      );
      toast.success(`${model} pulled.`);
    } catch (err) {
      if (!(err instanceof DOMException && err.name === "AbortError")) {
        toast.error(`Could not pull ${model}.`);
      }
    } finally {
      setPulling(false);
      abortRef.current = null;
    }
  };

  const pct =
    progress?.total && progress.completed != null
      ? Math.round((progress.completed / progress.total) * 100)
      : null;

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={start}
        disabled={disabled || pulling}
        className="btn btn-secondary px-3 py-1 text-xs font-mono"
      >
        {pulling && <span className="spinner" />}
        Pull {model}
      </button>
      {pulling && (
        <span className="font-mono text-[0.6875rem] text-text-muted">
          {progress?.status ?? "starting…"}
          {pct != null && ` · ${pct}%`}
        </span>
      )}
    </div>
  );
}

export function LocalLLMCard() {
  const { data, isLoading, isFetching } = useLocalLLMStatus(!isDesktop);
  const [expanded, setExpanded] = useState(false);
  const startServer = useStartLocalServer();
  const stopServer = useStopLocalServer();

  const tone = data ? statusTone(data.reachable, data.usable) : null;
  const models = data?.models ?? [];
  const shown = expanded ? models : models.slice(0, 5);

  const handleStart = async () => {
    try {
      await startServer.mutateAsync();
      toast.success("Starting local models…");
    } catch {
      toast.error("Could not start the local model server.");
    }
  };

  return (
    <Section
      title="Local models (Ollama)"
      description={
        <>
          Run the assistant against a model on your own machine — no API key, no cost, and
          nothing leaves your computer.{" "}
          <Link
            className="underline underline-offset-2 hover:text-text-secondary"
            href="/docs/getting-started/local-llm"
          >
            Setup guide
          </Link>
        </>
      }
      footer={
        isDesktop ? (
          data?.install_state === "installed_not_running" ? (
            <button
              type="button"
              className="btn btn-primary"
              disabled={startServer.isPending}
              onClick={handleStart}
            >
              {startServer.isPending && <span className="spinner" />}
              Start local models
            </button>
          ) : data?.install_state === "running" ? (
            <button
              type="button"
              className="btn btn-secondary"
              disabled={stopServer.isPending}
              onClick={() => stopServer.mutate()}
            >
              {stopServer.isPending && <span className="spinner" />}
              Stop
            </button>
          ) : null
        ) : undefined
      }
    >
      {isLoading ? (
        <div className="h-16 animate-pulse border border-border bg-bg-surface" aria-hidden />
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <span className="flex items-center gap-2 font-mono text-xs font-semibold">
              <span aria-hidden className="status-marker" style={{ background: tone?.color }} />
              <span style={{ color: tone?.color }}>{tone?.label}</span>
            </span>
            <code className="font-mono text-xs text-text-muted">{data?.configured_base_url}</code>
            {isFetching && !isDesktop && data?.install_state !== "running" && (
              <span className="font-mono text-[0.6875rem] text-text-muted">checking…</span>
            )}
          </div>

          {!isDesktop && data?.install_state !== "running" && <WebInstallGuide />}

          {data?.hint && (
            <p
              className="border border-border px-3 py-2.5 font-mono text-xs leading-relaxed"
              style={{
                background: "color-mix(in srgb, var(--warning) 8%, transparent)",
                color: "var(--text-secondary)",
              }}
            >
              {data.hint}
            </p>
          )}

          {data?.install_state === "running" && models.length === 0 && (
            <PullButton model={RECOMMENDED_MODEL} />
          )}

          {models.length > 0 && (
            <div>
              <ul className="divide-y divide-border">
                {shown.map((m) => (
                  <ModelRow key={m.name} model={m} />
                ))}
              </ul>
              {models.length > 5 && (
                <button
                  type="button"
                  className="mt-1 text-[0.75rem] text-text-muted underline underline-offset-2 hover:text-text-secondary"
                  onClick={() => setExpanded((v) => !v)}
                >
                  {expanded ? "Show fewer" : `Show all ${models.length}`}
                </button>
              )}
              <p className="mt-3 text-[0.75rem] leading-relaxed text-text-muted">
                Pick a local model per role in <strong>Model routing</strong> below. Models
                marked <em>chat only</em> are usually too small for research runs — they
                search fine but fail to return citable evidence in the required format.
              </p>
            </div>
          )}
        </div>
      )}
    </Section>
  );
}
