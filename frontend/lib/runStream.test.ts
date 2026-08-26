import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { shouldOpenStream } from "./sessionStream";

/**
 * The run workspace must subscribe on the same rule the session stream already proved.
 *
 * The session stream hit this exact defect and fixed it (see `lib/sessionStream.ts`): gating it on
 * "is the run live" discards the run's history, because the stream is the only path by
 * which the UI reads `agent_logs`. It also made the E2E flaky rather than simply broken —
 * a fake-mode run reaches the gate in well under a second, so whether a stream opened at
 * all depended on the page winning a race against the pipeline.
 *
 * The run workspace shipped with the unfixed copy: `useRunStream(runId, isLive(status), ...)`. The
 * reconnect journey failed 5 runs out of 6 locally before this changed.
 *
 * Asserted against the page source because the thing that regressed is which predicate is
 * passed at one call site, and mounting the page here would need the whole query/router
 * stack for a one-line contract.
 */
describe("run workspace stream subscription", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "app", "(app)", "research", "run", "page.tsx"),
    "utf8",
  );

  it("subscribes via shouldOpenStream, not isLive", () => {
    const call = source.match(/useRunStream\(([\s\S]*?)\)\s*;/);
    expect(call, "useRunStream call not found in the run page").toBeTruthy();
    const args = call![1];
    expect(args).toContain("shouldOpenStream");
    expect(args).not.toMatch(/\blive\b/);
  });

  it("still uses isLive for controls that are only valid on a running run", () => {
    // `isLive` is correct for the Stop button — cancelling a finished run is meaningless.
    // Its removal here would mean the two concerns had been collapsed again.
    expect(source).toMatch(/const live = isLive\(/);
    expect(source).toContain("{live && <CancelButton");
  });

  it("opens for finished runs, which is the whole point", () => {
    for (const status of ["PENDING", "RUNNING", "AWAITING_REVIEW", "COMPLETED", "FAILED"]) {
      expect(shouldOpenStream(status), `${status} should open a stream`).toBe(true);
    }
    expect(shouldOpenStream(undefined)).toBe(false);
  });
});
