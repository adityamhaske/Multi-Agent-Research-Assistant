import type { Metadata } from "next";
import Link from "next/link";

import { SiteFooter, SiteHeader } from "@/components/site/SiteChrome";

/**
 * The site-wide 404.
 *
 * Placed at the root of `app/` — not inside `(site)` — specifically so it also becomes the
 * static export's top-level `404.html`. GitHub Pages serves that exact file, with a real
 * 404 status, for any request path it cannot otherwise resolve; without one it falls back
 * to Pages' own unbranded default, which is what every broken or renamed link on this site
 * showed until now. It doubles as the boundary Next renders wherever the app already calls
 * `notFound()` (an unknown doc slug in `docs/[...slug]/page.tsx`).
 *
 * Reuses `SiteHeader`/`SiteFooter` rather than a bare page: being outside `(site)` means it
 * is not wrapped by that group's own `layout.tsx`, so without this it would render inside
 * only the root `<html>`/`<body>` shell, with no way back into the site's own navigation.
 */

export const metadata: Metadata = {
  title: "Page not found",
  // Never indexed — a 404 has no content of its own to rank, and letting a search engine
  // pick this page up would put it in a spot only a broken link points at.
  robots: { index: false, follow: true },
};

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col bg-bg-base">
      <SiteHeader />
      <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col items-start justify-center px-4 py-16 sm:px-6">
        <p className="font-mono text-[0.6875rem] uppercase tracking-widest text-text-muted">
          404
        </p>
        <h1 className="mt-3 font-serif text-3xl font-bold tracking-tight text-text-primary sm:text-4xl">
          Page not found
        </h1>
        <p className="mt-4 max-w-md text-base leading-relaxed text-text-secondary">
          There is nothing at this address — the link may be old, or the page may have
          moved when the docs were reorganized.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <Link href="/" className="btn btn-primary">
            Back to the homepage →
          </Link>
          <Link
            href="/docs"
            className="flex h-9 items-center border border-border bg-bg-surface px-3 font-mono text-xs text-text-secondary transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            Browse the documentation →
          </Link>
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}
