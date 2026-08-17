/**
 * Screenshot capture for the README (docs/screenshots/).
 *
 * Not part of the golden E2E suite — this is a documentation tool. It drives a
 * real run against whatever LLM_MODE the stack is in and saves the resulting
 * screens to disk, so the README shows the actual product rather than mockups.
 *
 *   npm run screenshots
 *
 * It is excluded from the golden config's `testIgnore`, so naming this file directly on
 * the command line will NOT run it — use the script above, which points Playwright at
 * playwright.screenshots.config.ts.
 *
 * Requires the full stack running (docker compose -f docker-compose.full.yml up).
 */
import fs from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

const OUT = path.resolve(__dirname, "../../docs/screenshots");
const PASSWORD = "demo-correct-horse-battery-99";
const QUERY =
  "What are the main approaches to retrieval-augmented generation (RAG), and what are their trade-offs?";

// One long-running test: the pipeline runs once and every screen is captured
// from that same real session.
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
  // By submit type, not by label — see golden.spec.ts::submitAuthForm. The copy here was
  // "Create Account" until the landing-page redesign renamed it "Initialize Account",
  // which hung this file on a locator that could never match.
  const submit = page.locator('form button[type="submit"]');
  await expect(submit).toHaveAccessibleName(/\S/);
  await submit.click();
  await page.waitForURL("**/dashboard");

  // ── 2. Dashboard (light) ──────────────────────────────────────────────────
  await setTheme(page, "light");
  await page.getByLabel(/research question/i).fill(QUERY);
  await shot(page, "02-dashboard");

  // ── 3. Research design gate ───────────────────────────────────────────────
  // The run form ships with plan review on (docs/07 §2, Phase 4), so every run now
  // pauses here first. This step is not optional bookkeeping: without it the capture
  // sat at the design gate waiting for a review gate that could not arrive, and burned
  // the full 600s timeout to report "element(s) not found".
  await page.getByRole("button", { name: /start research/i }).click();
  await page.waitForURL(/\/session\/[0-9a-f-]{36}/);
  const sessionUrl = page.url();

  await expect(page.getByRole("heading", { name: /design gate/i })).toBeVisible({
    timeout: 120_000,
  });
  await page.waitForTimeout(1500);
  await shot(page, "03-plan-gate");

  await page.getByRole("button", { name: /approve & start research/i }).click();

  // ── 3b. Live monitor while the pipeline runs ──────────────────────────────
  await expect(page.getByRole("heading", { name: "Activity" })).toBeVisible({
    timeout: 60_000,
  });
  // Let a few agent events land so the feed and rail are populated.
  await expect(page.getByLabel("Agent activity log")).toContainText(/planner|executor/i, {
    timeout: 120_000,
  });
  await page.waitForTimeout(6000);
  await shot(page, "03-live-monitor");

  // ── 4. Human approval gate ────────────────────────────────────────────────
  await expect(page.getByRole("heading", { name: /review gate/i })).toBeVisible({
    timeout: 600_000,
  });
  await page.waitForTimeout(1500);
  await shot(page, "04-approval-gate");

  // ── 5. Completed report + citations ───────────────────────────────────────
  await page.getByRole("button", { name: /approve & finalize/i }).click();
  // Same drift as golden.spec.ts: the heading now reads "Research Report", so an
  // exact-name locator waits instead of matching. Anchor on the labelled region.
  await expect(page.locator('section[aria-labelledby="report-heading"]')).toBeVisible({
    timeout: 600_000,
  });
  await page.waitForTimeout(1500);
  await shot(page, "05-report");

  // Sources panel (scroll to it).
  await page.evaluate(() => {
    const el = [...document.querySelectorAll("h2")].find((h) => /^Sources \(/.test(h.textContent ?? ""));
    if (el) window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 70);
  });
  await page.waitForTimeout(600);
  await shot(page, "06-sources");

  // ── 6. Same report in dark mode (Claude Code palette) ─────────────────────
  await page.goto(sessionUrl);
  await setTheme(page, "dark");
  await page.waitForTimeout(800);
  await shot(page, "07-report-dark");

  // ── 7. Profile (identity + password) ──────────────────────────────────────
  await page.goto("/profile");
  await setTheme(page, "light");
  await page.waitForTimeout(800);
  await shot(page, "08-profile");

  // ── 8. Settings (usage + BYOK) ────────────────────────────────────────────
  await page.goto("/settings");
  await page.waitForTimeout(800);
  await shot(page, "09-byok");

  // ── 8b. Account menu open (nav IA) ────────────────────────────────────────
  await page.getByRole("button", { name: /account|ada|docs-/i }).first().click().catch(() => {});
  await page.evaluate(() => {
    const b = [...document.querySelectorAll("button")].find(
      (x) => x.getAttribute("aria-haspopup") === "menu",
    );
    if (b && b.getAttribute("aria-expanded") !== "true") (b as HTMLButtonElement).click();
  });
  await page.waitForTimeout(400);
  await shot(page, "11-account-menu");

  // ── 8. History ────────────────────────────────────────────────────────────
  await page.goto("/history");
  await page.waitForTimeout(800);
  await shot(page, "10-history");

  console.log(`Screenshots written to ${OUT}`);
});
