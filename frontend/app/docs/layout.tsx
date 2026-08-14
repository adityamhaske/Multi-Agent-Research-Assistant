import Link from "next/link";

import { DocsSidebar } from "@/components/docs/DocsSidebar";
import { ThemeToggle } from "@/components/ThemeToggle";
import { docCategories } from "@/lib/docs";

/**
 * Documentation shell.
 *
 * Deliberately outside the `(app)` route group: docs are public. They are what someone
 * reads to decide whether to run this at all, so putting them behind the login wall would
 * gate the material that answers "should I install this".
 */
export default function DocsLayout({ children }: { children: React.ReactNode }) {
  const categories = docCategories();

  return (
    <div className="flex min-h-screen flex-col bg-bg-base">
      <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center justify-between border-b border-border bg-bg-base/90 px-4 backdrop-blur-md sm:px-6">
        <div className="flex items-center gap-3">
          <Link href="/" className="group flex items-center gap-2.5">
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
            <span className="font-serif text-[0.9375rem] font-bold tracking-tight text-text-primary">
              Research Assistant
            </span>
          </Link>
          <span className="hidden font-mono text-[0.6875rem] uppercase tracking-widest text-text-muted sm:inline">
            Documentation
          </span>
        </div>

        <div className="flex items-center gap-2">
          <Link
            href="/dashboard"
            className="flex h-8 items-center border border-border bg-bg-surface px-2.5 font-mono text-xs text-text-secondary transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            Open app →
          </Link>
          <ThemeToggle />
        </div>
      </header>

      <div className="mx-auto flex w-full max-w-7xl flex-1 gap-8 px-4 py-8 sm:px-6">
        <aside className="hidden w-56 shrink-0 lg:block">
          {/* Sticky under the 3.5rem header so navigation stays reachable in a long doc. */}
          <div className="sticky top-[4.5rem] max-h-[calc(100vh-6rem)]">
            <DocsSidebar categories={categories} />
          </div>
        </aside>

        <main className="min-w-0 flex-1">{children}</main>
      </div>
    </div>
  );
}
