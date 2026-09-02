import type { MetadataRoute } from "next";

import { isPagesBuild, siteUrl } from "@/lib/pages-build";

// Every value below is build-time-only (one env var), so this is always safe to freeze at
// build time — but the desktop export (`output: "export"`) does not infer that on its own:
// without this it fails the build outright, naming this route, the same as `sitemap.ts`.
export const dynamic = "force-static";

/**
 * `/robots.txt`, generated at build time — this file convention works under
 * `output: "export"` the same as any other static file, so it needs no server.
 *
 * Only the Pages build gets an allow-all policy. The desktop export has no public HTTP
 * origin to be crawled at, and the standalone server is typically a self-hosted, often
 * private deployment running the authenticated `(app)` routes on the *same* origin as
 * these public `(site)` pages (`prepare-pages-routes.mjs` strips `(app)`/`login` only for
 * the Pages export, not this one) — at a domain this build never sees. Disallowing
 * everything there is the safe default; a self-hosted deployment that wants indexing can
 * front it with its own robots.txt, the same way it already fronts it with its own domain.
 */
export default function robots(): MetadataRoute.Robots {
  if (!isPagesBuild) {
    return { rules: { userAgent: "*", disallow: "/" } };
  }
  return {
    rules: { userAgent: "*", allow: "/" },
    sitemap: `${siteUrl}/sitemap.xml`,
  };
}
