import { defineConfig, devices } from "@playwright/test";

const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:3031";

/**
 * Golden E2E config (docs/08 §2). Runs against the real stack with the backend in
 * `LLM_MODE=fake`, so journeys are deterministic and cost nothing.
 *
 * Serial with a single worker: the journeys drive a shared backend (Postgres, Redis,
 * one Celery worker), and the session lock means parallel pipelines would contend.
 */
export default defineConfig({
  testDir: "./e2e",
  // The screenshot tool lives in ./e2e but is NOT a gate — its own header says so
  // ("Not part of the golden E2E suite — this is a documentation tool"). It was running
  // in CI anyway, purely because testDir globs the folder, and the cost was not small:
  // it overrides the timeout to 900_000, drives a fourth full pipeline, and with
  // `retries: 1` and `workers: 1` it consumed up to 30 minutes serially *before* the
  // three journeys started. A documentation script was failing merges.
  // Run it deliberately instead: `npm run screenshots`.
  testIgnore: "**/capture-screenshots.spec.ts",
  timeout: 180_000, // a full pipeline run, even faked, crosses queue + DB + graph
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  // A retry-masked failure is indistinguishable from a pass, and this gate exists to be
  // trusted: golden-e2e reported green on "1 flaky / 2 passed" while a real intermittent
  // failure went unreported. Retries stay, so a retry still tells us the failure was
  // intermittent rather than hard — but in CI a flake now fails the run.
  failOnFlakyTests: Boolean(process.env.CI),
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  // Set E2E_NO_SERVER=1 when the frontend is already running (CI starts it itself).
  webServer: process.env.E2E_NO_SERVER
    ? undefined
    : {
        command: "npm run build && npm run start",
        url: BASE_URL,
        reuseExistingServer: !process.env.CI,
        timeout: 240_000,
      },
});
