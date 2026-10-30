import type { MetadataRoute } from "next";

import { allDocs } from "@/lib/docs";
import { absoluteUrl, isPagesBuild } from "@/lib/pages-build";

/**
 * Every non-doc route the Pages export actually publishes. `prepare-pages-routes.mjs`
 * strips `(app)` and `/login` before that build runs, so nothing under either belongs here
 * — a route only this list forgets to strip would otherwise ask a crawler to index a page
 * that 404s.
 */
const STATIC_ROUTES = ["/", "/why", "/docs", "/download", "/releases", "/source", "/license"];

// Every value here is build-time-only (env vars and the docs tree read at import time), so
// this is always safe to freeze at build time — but the desktop export (`output: "export"`)
// does not infer that on its own the way the standalone server build does, and fails the
// build outright without this: "dynamic ... not configured on route /sitemap.xml".
export const dynamic = "force-static";

/**
 * How often each kind of page realistically changes. Google ignores `changefreq`; other
 * crawlers (Bing, Yandex, assorted AI fetchers) still read it as a hint, so it is declared
 * per kind of page rather than as one blanket value.
 */
const CHANGE_FREQUENCY = {
  "/": "weekly",
  "/releases": "weekly",
  "/download": "weekly",
} as const;

/**
 * Commit date of the revision this site was built from (`pages.yml` sets it from `git log`).
 *
 * One site-wide value, not a per-page one, and that is the honest granularity: a fresh
 * `actions/checkout` resets every file's mtime to checkout time, so per-file dates would be
 * fabricated, whereas "the site as of this commit" is a fact. Absent when the build was not
 * given one (a local `build:pages`), and then `<lastmod>` is left out entirely rather than
 * invented from the wall clock — Google only trusts `lastmod` that is verifiably accurate.
 */
const LASTMOD = process.env.NEXT_PUBLIC_SITE_LASTMOD
  ? new Date(process.env.NEXT_PUBLIC_SITE_LASTMOD)
  : undefined;
const lastModified = LASTMOD && !Number.isNaN(LASTMOD.getTime()) ? LASTMOD : undefined;

function entry(route: string) {
  return {
    url: absoluteUrl(route)!,
    ...(lastModified && { lastModified }),
    changeFrequency:
      CHANGE_FREQUENCY[route as keyof typeof CHANGE_FREQUENCY] ?? ("monthly" as const),
  };
}

/**
 * `/sitemap.xml`, generated at build time from the same route set `robots.ts` allows.
 *
 * `<priority>` is deliberately absent: there is no honest basis for ranking one page above
 * another. See `LASTMOD` for why `<lastmod>` is a single build-wide date.
 *
 * Empty outside the Pages build, for the same reason `robots.ts` disallows everything
 * there: neither the desktop export nor a self-hosted server has an origin this build can
 * name, and a sitemap pointing at `https://adityamhaske.github.io/...` from someone else's
 * deployment would be actively wrong rather than merely unused.
 */
export default function sitemap(): MetadataRoute.Sitemap {
  if (!isPagesBuild) return [];

  const staticEntries = STATIC_ROUTES.map(entry);
  const docEntries = allDocs().map((doc) => entry(`/docs/${doc.slug}`));

  return [...staticEntries, ...docEntries];
}
