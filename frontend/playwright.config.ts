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
  timeout: 180_000, // a full pipeline run, even faked, crosses queue + DB + graph
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
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
