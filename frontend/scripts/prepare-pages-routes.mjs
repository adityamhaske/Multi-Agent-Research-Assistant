#!/usr/bin/env node
/**
 * Hide the app-only routes for the duration of a Pages build, then put them back.
 *
 * `build:pages` exports the public `(site)` tree. The `(app)` group and `/login` need a
 * backend and a session — `(app)/layout.tsx` reads `cookies()` — so a static export of them
 * fails outright, and would publish a broken shell even if it did not.
 *
 * `.github/workflows/pages.yml` already deletes them, but it does so on a *copy* under
 * `/tmp`, which meant `npm run build:pages` had never worked in a normal checkout. The
 * command in `package.json` and the command CI runs were the same name doing two different
 * things, and the local one was simply broken — the failure this fixes.
 *
 * Rename rather than delete: the developer running this has uncommitted work in those
 * directories, and `finally` restores them even when the build fails. Same shape as
 * `prepare-session-routes.mjs`, which is the established pattern here.
 */
import { existsSync, mkdirSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

//: Route directories a Pages export must not contain, and where they are parked.
//
//: Parked OUTSIDE `app/`. A dot-prefixed name inside it is still a route — the first
//: attempt renamed `app/(app)` to `app/.pages-hidden-app` and the build promptly failed
//: prerendering `/.pages-hidden-app/corpus`.
const HIDDEN = [
  ["app/(app)", ".pages-parked/app-group"],
  ["app/login", ".pages-parked/login"],
];

const moved = [];
try {
  for (const [live, parked] of HIDDEN) {
    const from = path.join(root, live);
    const to = path.join(root, parked);
    if (!existsSync(from)) continue;
    mkdirSync(path.dirname(to), { recursive: true });
    if (existsSync(to)) {
      // A previous run died between the two renames. Restoring is the only safe move —
      // building over a half-parked tree would export whichever half survived.
      throw new Error(`${parked} already exists; restore it before building.`);
    }
    renameSync(from, to);
    moved.push([to, from]);
  }

  const result = spawnSync("npx", ["next", "build"], {
    cwd: root,
    stdio: "inherit",
    env: { ...process.env, NEXT_PUBLIC_PAGES: "1" },
  });
  process.exitCode = result.status ?? 1;

  if (result.status === 0) {
    // Pages runs Jekyll by default and silently drops every path beginning with an
    // underscore — which is all of `_next/`. The workflow touches this file after its own
    // build; doing it here too means the local `out/` is the same artifact CI deploys
    // rather than one that only looks like it.
    writeFileSync(path.join(root, "out", ".nojekyll"), "");
  }
} finally {
  for (const [parked, live] of moved.reverse()) renameSync(parked, live);
  rmSync(path.join(root, ".pages-parked"), { recursive: true, force: true });
}
