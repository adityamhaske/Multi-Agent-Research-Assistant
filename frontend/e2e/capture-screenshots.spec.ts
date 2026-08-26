/**
 * Screenshot capture for the documentation (docs/screenshots/).
 *
 * Not part of the golden E2E suite — this is a documentation tool. It drives a real run
 * against whatever LLM_MODE the stack is in and saves the resulting screens to disk, so
 * the docs show the actual product rather than mockups.
 *
 *   npm run screenshots
 *
 * It is excluded from the golden config's `testIgnore`, so naming this file directly on
 * the command line will NOT run it — use the script above, which points Playwright at
 * playwright.screenshots.config.ts.
 *
 * Requires the full stack running (docker compose -f docker-compose.full.yml up).
 *
 * **It captures the journey the product ships.** It used to walk a second start form on a
 * second pipeline, so every image in `docs/screenshots/` showed a surface the navigation
 * had stopped pointing at — a documentation tool producing documentation of the wrong
 * product. The run workspace below is what a user actually sees.
 */
import fs from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "./fixtures";

const OUT = path.resolve(__dirname, "../../docs/screenshots");
const PASSWORD = "demo-correct-horse-battery-99";
const QUERY =
  "What are the main approaches to retrieval-augmented generation (RAG), and what are their trade-offs?";

// One long-running test: the pipeline runs once and every screen is captured from that
// same real run.
test.describe.configure({ mode: "serial", timeout: 900_000 });

async function shot(page: Page, name: string) {
  fs.mkdirSync(OUT, { recursive: true });
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: false });
}

async function setTheme(page: Page, theme: "light" | "dark") {
  await page.evaluate((t) => {
    localStorage.setItem("theme", t);
    document.documentElement.classList.toggle("dark", t === "dark");
  }, theme);
  await page.waitForTimeout(250);
}

/** Open a workspace tab and let it settle before the shutter. */
async function openTab(page: Page, name: RegExp) {
  await page.getByRole("tab", { name }).click();
  await page.waitForTimeout(800);
}

test("capture product screenshots", async ({ page }) => {
  test.setTimeout(900_000);
  await page.setViewportSize({ width: 1440, height: 900 });

  const email = `docs-${Date.now()}@mara-demo.dev`;

  // ── 1. Sign-up (light) ────────────────────────────────────────────────────
  await page.goto("/login");
  await setTheme(page, "light");
  await page.getByRole("tab", { name: /create account/i }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await shot(page, "01-login");
  // By submit type, not by label: this button's copy changed once already and hung the
  // capture on a locator that could never match.
  const submit = page.locator('form button[type="submit"]');
  await expect(submit).toHaveAccessibleName(/\S/);
  await submit.click();
  await page.waitForURL(/\/(research|project)/, { timeout: 60_000 });

  // A run is project-scoped, and a fresh account owns no project.
  await page.goto("/research");
  await setTheme(page, "light");
  const created = await page.request.post("/api/v1/projects", {
    data: { name: "Demo", description: "Documentation capture" },
  });
  expect(created.ok(), `project create failed: ${created.status()}`).toBe(true);
  await page.reload();

  // ── 2. The research page, question typed ──────────────────────────────────
  await page.getByLabel(/research question/i).fill(QUERY);
  await page.waitForTimeout(500);
  await shot(page, "02-start-research");

  // ── 3. The design gate ────────────────────────────────────────────────────
  // The run form ships with plan review on, so every run pauses here first.
  await page.getByRole("button", { name: /start research/i }).click();
  await page.waitForURL(/\/research\/run\?id=/, { timeout: 60_000 });
  const runUrl = page.url();

  await expect(page.getByRole("heading", { name: "Research plan" })).toBeVisible({
    timeout: 300_000,
  });
  await page.waitForTimeout(1500);
  await shot(page, "03-plan-gate");

  await page.getByRole("button", { name: "Approve plan" }).click();

  // ── 4. The report gate ────────────────────────────────────────────────────
  await expect(page.getByText("What you are approving")).toBeVisible({ timeout: 600_000 });
  await page.waitForTimeout(1500);
  await shot(page, "04-review-gate");

  // ── 5. The chain behind the report ────────────────────────────────────────
  await openTab(page, /^report$/i);
  await shot(page, "05-report");
  await openTab(page, /^evidence$/i);
  await shot(page, "06-evidence");
  await openTab(page, /^sources$/i);
  await shot(page, "07-sources");

  // ── 6. Approve, then the artifact and its verification ────────────────────
  await openTab(page, /^review$/i);
  await page.getByRole("button", { name: "Approve report" }).click();
  await expect(page.getByText("Verified artifact")).toBeVisible({ timeout: 120_000 });
  await page.waitForTimeout(1200);
  await shot(page, "08-artifact");

  // ── 7. The same workspace in dark mode ────────────────────────────────────
  await page.goto(runUrl);
  await setTheme(page, "dark");
  await page.waitForTimeout(1000);
  await shot(page, "09-workspace-dark");

  // ── 8. Settings (usage + BYOK) ────────────────────────────────────────────
  await page.goto("/settings");
  await setTheme(page, "light");
  await page.waitForTimeout(800);
  await shot(page, "10-settings");

  // ── 9. History ────────────────────────────────────────────────────────────
  await page.goto("/history");
  await page.waitForTimeout(800);
  await shot(page, "11-history");

  console.log(`Screenshots written to ${OUT}`);
});
