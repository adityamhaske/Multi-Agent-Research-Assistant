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
 * `/sitemap.xml`, generated at build time from the same route set `robots.ts` allows.
 *
 * `<lastmod>`, `<priority>` and `<changefreq>` are deliberately absent. Google's own sitemap
 * documentation says it ignores `priority`/`changefreq` outright and only trusts `lastmod`
 * when it is "consistently and verifiably accurate" — this build has no real per-page edit
 * history to report (a fresh `actions/checkout` resets every file's mtime to checkout time,
 * not the commit that last touched it), so the honest sitemap is a list of URLs, not a
 * fabricated freshness signal three fields wide.
 *
 * Empty outside the Pages build, for the same reason `robots.ts` disallows everything
 * there: neither the desktop export nor a self-hosted server has an origin this build can
 * name, and a sitemap pointing at `https://adityamhaske.github.io/...` from someone else's
 * deployment would be actively wrong rather than merely unused.
 */
export default function sitemap(): MetadataRoute.Sitemap {
  if (!isPagesBuild) return [];

  const staticEntries = STATIC_ROUTES.map((route) => ({ url: absoluteUrl(route)! }));
  const docEntries = allDocs().map((doc) => ({ url: absoluteUrl(`/docs/${doc.slug}`)! }));

  return [...staticEntries, ...docEntries];
}
