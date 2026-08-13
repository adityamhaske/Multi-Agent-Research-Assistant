#!/usr/bin/env node
/**
 * Variant-exclusive session routes (docs/13 §7).
 *
 * The web build needs the dynamic `/session/[sessionId]` route; the desktop static
 * export cannot ship dynamic segments at all — Next rejects a `generateStaticParams`
 * that produces zero paths under `output: export`. The two route files therefore
 * live in `app-routes/session/{web,desktop}/`, and this script links the one that
 * matches the build target into `app/(app)/session/`.
 *
 * Usage: node scripts/prepare-session-routes.mjs <web|desktop>
 */
import { existsSync, lstatSync, mkdirSync, rmSync, symlinkSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const mode = process.argv[2];
if (mode !== "web" && mode !== "desktop") {
  console.error("usage: prepare-session-routes.mjs <web|desktop>");
  process.exit(1);
}

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const sessionDir = join(root, "app", "(app)", "session");
mkdirSync(sessionDir, { recursive: true });

const links =
  mode === "web"
    ? [
        // Directory link: the whole [sessionId] route folder.
        { name: "[sessionId]", target: join(root, "app-routes", "session", "web", "[sessionId]") },
        // The static /session route exists only on desktop; keep the slot clean.
        { name: "page.tsx", target: null },
      ]
    : [
        { name: "[sessionId]", target: null },
        { name: "page.tsx", target: join(root, "app-routes", "session", "desktop", "page.tsx") },
      ];

for (const { name, target } of links) {
  const slot = join(sessionDir, name);
  // Remove whatever occupies the slot — a stale symlink, or a real file/directory
  // left over from before routes moved into app-routes/.
  if (existsSync(slot) || lstatIsSymlink(slot)) {
    rmSync(slot, { recursive: true });
  }
  if (target) {
    symlinkSync(target, slot);
  }
}

console.log(`session routes prepared for: ${mode}`);

function lstatIsSymlink(p) {
  try {
    return lstatSync(p).isSymbolicLink();
  } catch {
    return false;
  }
}
