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
