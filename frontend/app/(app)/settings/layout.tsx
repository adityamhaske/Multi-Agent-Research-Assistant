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
const SECTIONS: { slug: string; label: string; icon: string }[] = [
  { slug: "models", label: "Models", icon: "M9 3v2m6-2v2M9 19v2m6-2v2M3 9h2m-2 6h2m16-6h2m-2 6h2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z" },
  { slug: "connections", label: "Connections", icon: "M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" },
  { slug: "search", label: "Search Providers", icon: "M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9" },
  { slug: "research", label: "Research", icon: "M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" },
  { slug: "projects", label: "Projects", icon: "M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" },
  { slug: "appearance", label: "Appearance", icon: "M7 21a4 4 0 01-4-4 4 4 0 014-4c.73 0 1.41.2 2 .54V7a4 4 0 014-4 4 4 0 014 4v1.54A3.99 3.99 0 0119 13a4 4 0 01-4 4 4 4 0 01-4-4v-1.54A3.99 3.99 0 019 17.54V21z" },
  { slug: "advanced", label: "Advanced", icon: "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z" },
  { slug: "about", label: "About", icon: "M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" },
];

export default function SettingsLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { data: readiness } = useReadiness();
  const setupFirst = !isDesktop && readiness ? !readiness.ready : false;

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      {/* Header Banner */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between border-b border-border/70 pb-5">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="font-serif text-2xl font-bold tracking-tight text-text-primary">
              Settings
            </h1>
            <span className="border border-accent/20 bg-accent/5 px-2 py-0.5 font-mono text-[0.6875rem] font-medium text-accent">
              Configuration
            </span>
          </div>
          <p className="mt-1 text-sm text-text-muted">
            Manage provider keys, local model routing, search indexes, and account preferences.
          </p>
        </div>

        <div className="w-full sm:w-72">
          <SettingsSearch />
        </div>
      </div>

      {/* Setup First Alert */}
      {setupFirst && (
        <div
          role="note"
          className="border border-accent/30 bg-accent/5 p-4 text-sm text-text-secondary flex items-start gap-3 shadow-sm"
        >
          <svg className="w-5 h-5 text-accent shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <div className="space-y-1">
            <p className="font-semibold text-text-primary">Finish setting up</p>
            <p className="leading-relaxed text-text-secondary">
              Research needs one model source —{" "}
              <Link href="/settings/connections" className="text-accent underline font-medium hover:text-accent-hover">
                a provider key
              </Link>
              , or{" "}
              <Link href="/settings/models" className="text-accent underline font-medium hover:text-accent-hover">
                a local server
              </Link>
              . Everything else can wait.
            </p>
          </div>
        </div>
      )}

      {/* Main Grid */}
      <div className="flex flex-col gap-8 md:flex-row md:items-start">
        {/* Left Navigation Rail */}
        <nav
          aria-label="Settings sections"
          className="flex shrink-0 flex-row gap-1 overflow-x-auto pb-2 md:w-52 md:flex-col md:overflow-visible md:pb-0"
        >
          {SECTIONS.map((s) => {
            const active = pathname === `/settings/${s.slug}`;
            return (
              <Link
                key={s.slug}
                href={`/settings/${s.slug}`}
                aria-current={active ? "page" : undefined}
                className={`group flex items-center gap-2.5 px-3.5 py-2.5 text-sm font-medium transition-all ${
                  active
                    ? "bg-accent/10 text-accent font-semibold border-l-2 border-accent"
                    : "text-text-secondary hover:bg-bg-surface hover:text-text-primary border-l-2 border-transparent"
                }`}
              >
                <svg
                  className={`h-4 w-4 shrink-0 transition-colors ${
                    active ? "text-accent" : "text-text-muted group-hover:text-text-secondary"
                  }`}
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={1.75}
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d={s.icon} />
                </svg>
                <span className="truncate">{s.label}</span>
              </Link>
            );
          })}
        </nav>

        {/* Content Panel */}
        <div className="min-w-0 flex-1 space-y-6">{children}</div>
      </div>
    </div>
  );
}
