"use client";

import Link from "next/link";

import { useReadiness } from "@/hooks/queries";
import { isDesktop } from "@/lib/desktop";

/**
 * Shown when the user has no way to run research yet (docs/17 §8a).
 *
 * The trigger is computed, never stored. A "has seen onboarding" flag outlives the
 * condition it describes — still true after a key is revoked, still false after Ollama
 * starts — whereas this disappears the moment a model actually exists, and returns if one
 * stops existing.
 *
 * It routes to Settings rather than opening a wizard. A second key-entry surface would
 * diverge from the model picker the first time a provider is added; this codebase already
 * paid for that pattern once, when `map_local_host` existed in three copies and two were
 * wrong.
 */
export function FirstRunNotice() {
  const { data } = useReadiness();

  // Absent data is not "not ready" — a failed or in-flight request must not accuse the
  // user of missing configuration they may well have.
  if (!data || data.ready) return null;

  return (
    <div
      role="note"
      className="border px-4 py-3.5"
      style={{
        borderColor: "color-mix(in srgb, var(--accent) 35%, var(--border))",
        backgroundColor: "color-mix(in srgb, var(--accent) 6%, var(--bg-surface))",
      }}
    >
      <p className="text-sm font-semibold text-text-primary">
        Connect a model to start researching
      </p>
      <p className="mt-1 max-w-2xl text-sm leading-relaxed text-text-secondary">
        {data.local_reachable ? (
          <>
            A local model server is running — great for document embeddings. For
            research-quality output, add a provider key (Anthropic, Google, or
            OpenAI) in Settings.
          </>
        ) : (
          <>
            You need one of: a provider API key, or a local model server. Nothing else is
            required — web search falls back to a keyless provider, and the database is
            bundled.
          </>
        )}
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Link href="/settings" className="btn btn-primary">
          Connect a model
        </Link>
        {/* The keyless path this build actually has, never a control that does not exist.
            A self-hosted stack has one: `./start.sh --fake` runs the real graph on scripted
            models and fixture sources and stamps every run as a demo — and it is what
            `start.sh` falls back to on its own when `.env` has no provider key. The desktop
            app has no such switch, so on the desktop this offers nothing rather than a path
            that is not there. */}
        {!isDesktop && (
          <span className="font-mono text-xs text-text-muted">
            or, with no key at all, start the stack with{" "}
            <code className="font-semibold">./start.sh --fake</code> — scripted models on
            fixture sources, and every run is stamped as a demo
          </span>
        )}
      </div>
    </div>
  );
}
