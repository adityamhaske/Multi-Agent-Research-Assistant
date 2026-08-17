import Link from "next/link";

import { ThemeToggle } from "@/components/ThemeToggle";
import { isPagesBuild } from "@/lib/pages-build";

/**
 * Header and footer for the public site (`app/(site)/`).
 *
 * Extracted rather than copied because the mark and the header bar already existed twice —
 * once in the docs shell and once inline on the download page — and a third copy was about
 * to be written for the landing page. Every drift bug this repo has catalogued started as
 * a second copy of something (AGENTS.md, "two hosts, one contract"); this is the frontend
 * shape of the same mistake.
 *
 * `eyebrow` is the one thing that varies per section, and it is a *label*, not a title:
 * the docs shell used it to say "Documentation" beside the logo, which orients a reader
 * who arrived on a deep link with no idea which part of the site they are in.
 */

const REPO = "https://github.com/adityamhaske/Multi-Agent-Research-Assistant";

/** The hex-mark. Duplicated in `app/icon.svg` by necessity — that one is a static asset a
 *  browser fetches for the tab, this one is inline so it inherits `currentColor`. */
function Mark() {
  return (
    <span
      aria-hidden
      className="flex h-7 w-7 items-center justify-center border border-accent bg-accent text-accent-contrast"
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="square"
        strokeLinejoin="miter"
        className="h-4 w-4"
      >
        <polygon points="12 2 22 8.5 22 15.5 12 22 2 15.5 2 8.5 12 2" />
        <line x1="12" y1="22" x2="12" y2="15.5" />
        <polyline points="22 8.5 12 15.5 2 8.5" />
      </svg>
    </span>
  );
}

const NAV = [
  { href: "/why", label: "Why this" },
  { href: "/docs", label: "Docs" },
  { href: "/download", label: "Download" },
] as const;

export function SiteHeader({ eyebrow }: { eyebrow?: string }) {
  return (
    <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center justify-between border-b border-border bg-bg-base/90 px-4 backdrop-blur-md sm:px-6">
      <div className="flex items-center gap-3">
        <Link href="/" className="group flex items-center gap-2.5">
          <Mark />
          <span className="font-serif text-[0.9375rem] font-bold tracking-tight text-text-primary">
            Research Assistant
          </span>
        </Link>
        {eyebrow && (
          <span className="hidden font-mono text-[0.6875rem] uppercase tracking-widest text-text-muted sm:inline">
            {eyebrow}
          </span>
        )}
      </div>

      <div className="flex items-center gap-1">
        <nav aria-label="Site" className="hidden items-center gap-1 sm:flex">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="flex h-8 items-center px-2.5 font-mono text-xs text-text-secondary transition-colors hover:text-text-primary"
            >
              {item.label}
            </Link>
          ))}
        </nav>
        {isPagesBuild ? (
          // The static site has no app to open. Sending someone to /dashboard here would
          // 404 on a page that promises the opposite.
          <a
            href={REPO}
            className="ml-1 flex h-8 items-center border border-border bg-bg-surface px-2.5 font-mono text-xs text-text-secondary transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            GitHub ↗
          </a>
        ) : (
          <Link
            href="/dashboard"
            className="ml-1 flex h-8 items-center border border-border bg-bg-surface px-2.5 font-mono text-xs text-text-secondary transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            Open app →
          </Link>
        )}
        <ThemeToggle />
      </div>
    </header>
  );
}

export function SiteFooter() {
  return (
    <footer className="mt-16 border-t border-border px-4 py-8 sm:px-6">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <p className="font-mono text-[0.6875rem] text-text-muted">
          Self-hostable · bring your own key · MIT licensed
        </p>
        <nav aria-label="Footer" className="flex flex-wrap items-center gap-4">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="font-mono text-[0.6875rem] text-text-muted transition-colors hover:text-text-primary"
            >
              {item.label}
            </Link>
          ))}
          <a
            href={REPO}
            className="font-mono text-[0.6875rem] text-text-muted transition-colors hover:text-text-primary"
          >
            GitHub ↗
          </a>
        </nav>
      </div>
    </footer>
  );
}
