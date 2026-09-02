/**
 * GitHub Pages variant (`NEXT_PUBLIC_PAGES=1`).
 *
 * A third build target alongside the Docker server and the Tauri desktop export, and it
 * exists for one reason: **the in-app docs were unreachable to anyone who had not already
 * deployed the app.** `/docs` renders the repository's markdown tree beautifully and lives
 * behind a running Next server, so the material someone reads to decide whether to install
 * this required installing it first.
 *
 * (Do not write a glob with a star-slash in these comments — it closes the block early.
 * That cost a confusing round of TS1434 errors pointing at prose.)
 *
 * This target exports the `(site)` route group — landing, comparison, docs, download — as
 * flat HTML that Pages can serve. The `(app)` routes and `/login` are removed from a
 * *copy* of this directory by the workflow before building (`.github/workflows/pages.yml`);
 * they need a backend and would publish a broken shell.
 *
 * Publishing the real pages rather than a hand-written duplicate is the whole point. The
 * previous `site/index.html` was one static file written by hand, and by the time anyone
 * looked it described a pipeline with one human gate — the design gate had shipped weeks
 * earlier. Generated pages cannot drift from the app they document, and they inherit
 * `globals.css`, so the site's light and dark palettes are the app's by construction
 * rather than by somebody remembering to copy hex values across.
 *
 * The flag is inlined at build time, so every branch collapses to dead code in the server
 * and desktop builds — same contract as `isDesktop`.
 */

import type { Metadata } from "next";

export const isPagesBuild = process.env.NEXT_PUBLIC_PAGES === "1";

/**
 * Path prefix the site is served under.
 *
 * GitHub Pages serves a project site from `/<repo>/`, not the domain root, so every
 * internal link and asset needs the prefix or it 404s one level up. Next applies this to
 * `<Link>` and to its own assets automatically once `basePath` is set; this export exists
 * for the handful of places that build a URL by hand.
 */
export const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

/**
 * The origin this Pages build is published at, including its base path.
 *
 * Set by `.github/workflows/pages.yml` (`NEXT_PUBLIC_SITE_URL`, resolved in the same step
 * and from the same `CUSTOM_DOMAIN` check as `base_path`/`domain`), so a fork's own Pages
 * deploy gets its own owner and repo name for free instead of this project's. The fallback
 * covers a local `npm run build:pages` with no workflow env set: this repository's own
 * published URL, the same literal string `README.md`'s badges already point at, combined
 * with whatever `basePath` was passed — so a manual build still emits correct absolute
 * URLs instead of a bare, path-less origin.
 *
 * `||`, not `??`: unlike `basePath` above (where an *empty string* is the deliberate,
 * meaningful value for a custom domain), an empty `NEXT_PUBLIC_SITE_URL` is never
 * intentional — it would make every canonical URL a bare path instead of an absolute one,
 * and `new URL(siteUrl)` in the root layout's `metadataBase` would throw outright.
 */
export const siteUrl =
  process.env.NEXT_PUBLIC_SITE_URL || `https://adityamhaske.github.io${basePath}`;

/**
 * Absolute, canonical URL for a route on this deployment — or `undefined` when this build
 * has no knowable public origin.
 *
 * Only the Pages build's origin is knowable at build time. A self-hosted server deploys to
 * a domain this build never sees, and the desktop export has no HTTP origin at all —
 * guessing either would stamp `https://adityamhaske.github.io/...` as the canonical URL and
 * `og:url` on every self-hosted instance and every desktop install. `robots.ts` disallows
 * crawling on both builds for the same reason; this is the per-page half of that decision.
 *
 * Trailing-slashed like the Pages export itself (`next.config.ts`'s `trailingSlash: true`
 * for `isPages`), so the sitemap and every `<link rel="canonical">` name the exact URL the
 * export serves rather than one Pages would 404 or redirect from.
 */
export function absoluteUrl(routePath: string): string | undefined {
  if (!isPagesBuild) return undefined;
  const path = routePath.startsWith("/") ? routePath : `/${routePath}`;
  const withTrailingSlash = path === "/" ? path : `${path.replace(/\/+$/, "")}/`;
  return `${siteUrl}${withTrailingSlash}`;
}

/**
 * `alternates.canonical` and `openGraph.url` for a route, spread into a page's `metadata`.
 *
 * One function so a page cannot set one and forget the other — a crawler and a social
 * scraper would otherwise be free to disagree about which copy of a page is authoritative.
 * Deliberately does not set `openGraph.title`/`openGraph.description`: leaving those keys
 * absent (rather than restating a page's own `title`/`description` here) is what lets
 * Next's own per-page fallback fill them in from the page's `title`/`description` export —
 * setting them here would freeze whatever page called this first into every other page's
 * Open Graph tags, since metadata objects merge shallowly per field.
 *
 * Empty object when `absoluteUrl` has no origin to build from, which leaves both fields
 * unset rather than wrong — see `absoluteUrl`.
 */
export function pageUrls(routePath: string): Pick<Metadata, "alternates" | "openGraph"> {
  const url = absoluteUrl(routePath);
  return url ? { alternates: { canonical: url }, openGraph: { url } } : {};
}
