import net from "node:net";

import { test as base } from "@playwright/test";

/**
 * Test-only isolation for the registration rate limit.
 *
 * `REGISTER_IP` is 5 registrations per hour per IP and it is **not configurable** — it is
 * brute-force protection, and a cap a test suite can switch off is not a cap. The suite,
 * meanwhile, registers one account per journey and has more journeys than that, so every
 * run past the fifth got a `429` and the failure looked like a product bug each time.
 *
 * The fix is on the test side only: before each journey, delete this suite's own
 * rate-limit counters from the E2E Redis. Nothing in `app/services/rate_limit.py` changes,
 * the limiter runs exactly as it does in production, and a journey that somehow registered
 * six times inside one test would still be stopped by it.
 *
 * **Scoped to `rl:*`, never `FLUSHDB`.** The same Redis holds the SSE pub/sub channels and
 * the search cache; flushing the database would silently change what the run under test
 * actually does, which is the class of test that proves nothing.
 *
 * Spoken over a raw socket rather than through a client library: this is the only place in
 * the repo that needs Redis from Node, and a dependency added for one fixture is a
 * dependency the desktop bundle and the Docker image both carry forever.
 */

const REDIS_URL = process.env.E2E_REDIS_URL ?? "redis://localhost:6379/1";

/** Minimal RESP command writer — `*N\r\n$len\r\narg\r\n…`. */
function encode(args: string[]): string {
  return (
    `*${args.length}\r\n` + args.map((a) => `$${Buffer.byteLength(a)}\r\n${a}\r\n`).join("")
  );
}

async function redis(commands: string[][]): Promise<string> {
  const url = new URL(REDIS_URL);
  const db = url.pathname.replace("/", "") || "0";
  const port = Number(url.port || 6379);
  const host = url.hostname || "localhost";

  return new Promise((resolve, reject) => {
    const socket = net.createConnection({ host, port }, () => {
      socket.write(encode(["SELECT", db]));
      for (const cmd of commands) socket.write(encode(cmd));
      socket.write(encode(["QUIT"]));
    });
    let out = "";
    socket.setTimeout(5_000, () => socket.destroy(new Error("redis timeout")));
    socket.on("data", (chunk) => (out += chunk.toString("utf8")));
    socket.on("error", reject);
    socket.on("close", () => resolve(out));
  });
}

/**
 * Drop this suite's rate-limit counters.
 *
 * Two passes because `SCAN` needs its cursor answered before `DEL` can be sent, and a
 * single connection cannot see its own reply mid-write. Failure is swallowed: a developer
 * running one spec against a stack with no Redis should get that spec's real result, not a
 * fixture's connection error.
 */
export async function clearRateLimitCounters(): Promise<void> {
  try {
    const scanned = await redis([["SCAN", "0", "MATCH", "rl:*", "COUNT", "1000"]]);
    const keys = scanned
      .split("\r\n")
      .filter((line) => line.startsWith("rl:"))
      .map((k) => k.trim());
    if (keys.length) await redis([["DEL", ...keys]]);
  } catch {
    /* no Redis reachable — leave the suite to report its own result */
  }
}

/**
 * The suite's `test`. Identical to Playwright's, plus the counter reset.
 *
 * Import this instead of `@playwright/test` in every E2E spec, so a new journey is isolated
 * by default rather than by whoever remembers.
 */
export const test = base.extend({
  // The second parameter is named `provide`, not the Playwright-conventional `use`: the
  // repo's `react-hooks/rules-of-hooks` lint reads a call to `use(...)` as React's `use`
  // hook in a non-component function. Playwright passes it positionally, so the name is
  // free, and renaming beats disabling a rule that is right about everywhere else.
  page: async ({ page }, provide) => {
    await clearRateLimitCounters();
    await provide(page);
  },
});

export { expect, type Page } from "@playwright/test";
