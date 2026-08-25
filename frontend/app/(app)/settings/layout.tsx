"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { SettingsSearch } from "@/components/settings/SettingsSearch";
import { useReadiness } from "@/hooks/queries";
import { isDesktop } from "@/lib/desktop";

/**
 * The settings IA (docs/07 §2, Phase 3): a left rail replacing the single 452-line
 * scroll of six unrelated concerns — depth available, never in the way.
 */
const SECTIONS: { slug: string; label: string }[] = [
  { slug: "models", label: "Models" },
  { slug: "connections", label: "Connections" },
  { slug: "search", label: "Search Providers" },
  { slug: "research", label: "Research" },
  { slug: "corpus", label: "Corpus" },
  { slug: "exports", label: "Exports" },
  { slug: "appearance", label: "Appearance" },
  { slug: "advanced", label: "Advanced" },
];

export default function SettingsLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  // Web-only: readiness is an account concept (a cloud key or a reachable local
  // server); the desktop build has no server-side BYOK to be "not ready" about in
  // the same sense (docs/17 §8a).
  const { data: readiness } = useReadiness();
  const setupFirst = !isDesktop && readiness ? !readiness.ready : false;

  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="mb-1 font-serif text-xl font-bold tracking-tight text-text-primary">
        Settings
      </h1>
      <p className="mb-5 text-sm text-text-muted">
        Deep customization, organized — search below, or browse by section.
      </p>

      {/* Persists across every section now, not just one scroll's top (docs/07 §2) —
          says why Models/Connections are the sections that matter first. */}
      {setupFirst && (
        <div
          role="note"
          className="mb-5 border px-4 py-3"
          style={{
            borderColor: "color-mix(in srgb, var(--accent) 35%, var(--border))",
            backgroundColor: "color-mix(in srgb, var(--accent) 6%, var(--bg-surface))",
          }}
        >
          <p className="text-sm font-semibold text-text-primary">Finish setting up</p>
          <p className="mt-1 text-sm leading-relaxed text-text-secondary">
            Research needs one model source —{" "}
            <Link href="/settings/connections" className="underline">
              a provider key
            </Link>
            , or{" "}
            <Link href="/settings/models" className="underline">
              a local server
            </Link>
            . Everything else can wait.
          </p>
        </div>
      )}

      <div className="mb-5 max-w-sm">
        <SettingsSearch />
      </div>

      <div className="flex flex-col gap-6 md:flex-row">
        <nav
          aria-label="Settings sections"
          className="flex shrink-0 flex-row gap-1 overflow-x-auto md:w-44 md:flex-col md:overflow-visible"
        >
          {SECTIONS.map((s) => {
            const active = pathname === `/settings/${s.slug}`;
            return (
              <Link
                key={s.slug}
                href={`/settings/${s.slug}`}
                aria-current={active ? "page" : undefined}
                className={`whitespace-nowrap px-3 py-2 text-sm font-medium transition-colors ${
                  active
                    ? "bg-bg-elevated text-accent border-l-2 border-accent"
                    : "text-text-secondary hover:bg-bg-elevated hover:text-text-primary border-l-2 border-transparent"
                }`}
              >
                {s.label}
              </Link>
            );
          })}
        </nav>

        <div className="min-w-0 flex-1 space-y-5">{children}</div>
      </div>
    </div>
  );
}
