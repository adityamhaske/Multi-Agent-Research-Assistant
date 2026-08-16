import { defineConfig } from "@playwright/test";

import base from "./playwright.config";

/**
 * Config for the README screenshot tool (`e2e/capture-screenshots.spec.ts`).
 *
 * It needs its own config because the golden config `testIgnore`s that file, and a
 * `testIgnore` cannot be overridden by naming the file on the command line — so without
 * this the tool would be unrunnable rather than merely un-gated.
 *
 * The split is the point: the golden journeys gate merges, this drives a real run to
 * produce documentation images. It was previously swept into the merge gate by
 * `testDir` alone, where its 15-minute timeout and full pipeline run made an already
 * long job longer and let a docs script fail a build.
 *
 *   npm run screenshots        # requires the full stack up (docs/09)
 */
export default defineConfig({
  ...base,
  testIgnore: undefined,
  testMatch: "**/capture-screenshots.spec.ts",
  // A documentation run has no business retrying: a half-captured second attempt would
  // overwrite good images from the first.
  retries: 0,
});
