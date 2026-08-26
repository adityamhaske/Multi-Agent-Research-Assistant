/**
 * Interaction audit for the run workspace, driven against fixture data.
 *
 * Companion to `uiqa.mjs`, which looks at pages. This one presses things, and checks the
 * four questions a tab has to answer that a screenshot cannot: does the keyboard move
 * within it, does the URL follow, does Back return, and does a refresh land where the
 * reader was.
 *
 *   node e2e/uiqa-interactions.mjs
 */

import { chromium } from "@playwright/test";
import fs from "node:fs";

import * as F from "./uiqa.fixture.mjs";

const BASE = process.env.UIQA_BASE ?? "http://127.0.0.1:3043";
const EXECUTABLE =
  process.env.UIQA_CHROME ?? "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";

const json = (body) => ({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

const results = [];
function check(name, ok, detail = "") {
  results.push({ name, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? ` — ${detail}` : ""}`);
}

const browser = await chromium.launch(
  fs.existsSync(EXECUTABLE) ? { executablePath: EXECUTABLE } : {},
);
const ctx = await browser.newContext({
  storageState: {
    cookies: [
      {
        name: "access_token",
        value: "uiqa",
        domain: "127.0.0.1",
        path: "/",
        expires: -1,
        httpOnly: true,
        secure: false,
        sameSite: "Lax",
      },
    ],
    origins: [
      {
        origin: BASE,
        localStorage: [{ name: "active_project_id", value: F.IDS.PROJECT_ID }],
      },
    ],
  },
});
const page = await ctx.newPage();
const pageErrors = [];
page.on("pageerror", (e) => pageErrors.push(e.message));

await page.route("**/api/v1/**", (route) => {
  const p = new URL(route.request().url()).pathname.replace("/api/v1", "");
  if (p === "/auth/me") return route.fulfill(json(F.user));
  if (p === "/projects") return route.fulfill(json(F.projects));
  if (p === "/models/readiness") return route.fulfill(json(F.readiness));
  if (p === "/runs") return route.fulfill(json(F.runs));
  if (p.endsWith("/verification")) return route.fulfill(json(F.verification));
  if (p.endsWith("/stream")) return route.abort();
  if (/^\/runs\/[0-9a-f-]+$/.test(p)) return route.fulfill(json(F.graph()));
  return route.fulfill(json({}));
});

const RUN = `${BASE}/research/run?id=${F.IDS.RUN_ID}`;
await page.goto(RUN, { waitUntil: "domcontentloaded" });
await page.waitForSelector('[role="tab"]');
await page.waitForTimeout(600);

// ── 1. The run parked at the review gate opens on the decision, not on the report.
check(
  "opens on the tab the run's state demands",
  (await page.getAttribute('[role="tab"][aria-selected="true"]', "id")) === "run-tab-review",
);

// ── 2. One tab stop for the strip, and the arrows move within it.
await page.focus('[role="tab"][aria-selected="true"]');
await page.keyboard.press("ArrowLeft");
await page.waitForTimeout(250);
check(
  "arrow keys move between tabs",
  (await page.getAttribute('[role="tab"][aria-selected="true"]', "id")) ===
    "run-tab-contradictions",
);
check(
  "keyboard focus follows the selection",
  (await page.evaluate(() => document.activeElement?.id)) === "run-tab-contradictions",
);

// ── 3. The URL follows a tab a person picked.
await page.click('[role="tab"][id="run-tab-evidence"]');
await page.waitForTimeout(400);
check("the chosen tab is in the URL", new URL(page.url()).searchParams.get("tab") === "evidence");

// ── 4. Back returns to the previous tab rather than leaving the run.
await page.goBack();
await page.waitForTimeout(600);
check(
  "browser Back returns to the previous tab, still on the run",
  page.url().includes(`id=${F.IDS.RUN_ID}`) &&
    new URL(page.url()).searchParams.get("tab") !== "evidence",
  new URL(page.url()).search,
);

// ── 5. A refresh lands on the tab the URL names.
await page.goto(`${RUN}&tab=sources`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(700);
await page.reload({ waitUntil: "domcontentloaded" });
await page.waitForTimeout(700);
check(
  "a refresh keeps the reader's tab",
  (await page.getAttribute('[role="tab"][aria-selected="true"]', "id")) === "run-tab-sources",
);

// ── 6. A deep link to a tab that does not exist falls back rather than breaking.
await page.goto(`${RUN}&tab=nonsense`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(700);
check(
  "an unknown ?tab= falls back to the demanded tab",
  (await page.getAttribute('[role="tab"][aria-selected="true"]', "id")) === "run-tab-review",
);

// ── 7. Claim → evidence keeps context and says the ledger is filtered.
await page.goto(`${RUN}&tab=claims`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(700);
await page.getByText(/supporting evidence item/).first().click();
await page.getByText(/Inspect this claim's evidence in full/).first().click();
await page.waitForTimeout(500);
check(
  "following a claim into the evidence ledger says the ledger is filtered",
  await page.getByText(/Filtered/).first().isVisible(),
);
await page.getByRole("button", { name: "Show all evidence" }).click();
await page.waitForTimeout(300);
check(
  "the filter can be cleared",
  (await page.getByText(/showing the/).count()) === 0,
);

// ── 8. Evidence → source scrolls the source into view and rings it.
await page.getByRole("button", { name: /Retrieval-Augmented Agent Memory at Scale/ }).first().click();
await page.waitForTimeout(700);
check(
  "evidence links through to its source",
  (await page.locator(".ring-accent").count()) > 0,
);

// ── 9. Every visible control has an accessible name.
await page.goto(`${RUN}&tab=review`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(700);
const unnamed = await page.$$eval("main button, main a", (els) =>
  els
    .filter((e) => (e.offsetParent ?? null) !== null)
    .filter(
      (e) =>
        !(e.textContent ?? "").trim() &&
        !e.getAttribute("aria-label") &&
        !e.getAttribute("title"),
    )
    .map((e) => e.outerHTML.slice(0, 90)),
);
check("every visible control has an accessible name", unnamed.length === 0, unnamed.join(" | "));

// ── 10. Nothing in the workspace overflows the page horizontally.
const overflow = await page.evaluate(
  () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
);
check("no horizontal page overflow", overflow <= 1, `${overflow}px`);

// ── 11. The start form refuses a second submit while one is in flight.
let starts = 0;
await page.route("**/api/v1/runs", async (route) => {
  if (route.request().method() === "POST") {
    starts += 1;
    await new Promise((r) => setTimeout(r, 1500));
    return route.fulfill(json({ run_id: F.IDS.RUN_ID, status: "PENDING" }));
  }
  return route.fulfill(json(F.runs));
});
await page.goto(`${BASE}/research`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(800);
await page.getByLabel("Research question").fill("A question long enough to be accepted here.");
const startButton = page.getByRole("button", { name: "Start research" });
await startButton.click();
await startButton.click({ force: true }).catch(() => {});
await startButton.click({ force: true }).catch(() => {});
await page.waitForTimeout(2200);
check("a double click cannot start two runs", starts === 1, `${starts} POSTs`);

check("no uncaught page errors during the audit", pageErrors.length === 0, pageErrors.join(" | "));

await browser.close();

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length === 0 ? 0 : 1);
