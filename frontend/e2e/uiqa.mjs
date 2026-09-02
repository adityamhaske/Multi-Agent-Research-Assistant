/**
 * Offline UI QA: drive every surface this change touches against fixture data and take a
 * screenshot of each, in both themes and at three widths.
 *
 * Not a test and not run by CI. It exists because "it compiles" is not "it looks right",
 * and because several of the states that matter most — a failed run, an unresolved citation
 * marker, a conflicting pair, a run with no plan — are awkward to reach against a live
 * stack on demand. Drives fixtures with no backend at all, so its output is disposable:
 * it answers "does this state render correctly" during development, nothing more.
 *
 *   node e2e/uiqa.mjs            # writes .uiqa/*.png
 *
 * Requires a built app served on $UIQA_BASE (default http://127.0.0.1:3040).
 */

import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

import * as F from "./uiqa.fixture.mjs";

const BASE = process.env.UIQA_BASE ?? "http://127.0.0.1:3040";
const OUT = path.resolve(".uiqa");
fs.mkdirSync(OUT, { recursive: true });

const json = (body, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

/** Every backend call the authenticated surfaces make, answered from fixtures. */
async function mockApi(page, { runOverrides = {}, verification = F.verification } = {}) {
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const p = url.pathname.replace("/api/v1", "");

    if (p === "/auth/me") return route.fulfill(json(F.user));
    if (p === "/auth/me/usage")
      return route.fulfill(
        json({
          month: { tokens_input: 0, tokens_output: 0, tokens_total: 0, cost_usd: 0, sessions: 0 },
          week: { tokens_input: 0, tokens_output: 0, tokens_total: 0, cost_usd: 0, sessions: 0 },
          last_session: {
            tokens_input: 0,
            tokens_output: 0,
            tokens_total: 0,
            cost_usd: 0,
            sessions: 0,
          },
          monthly_token_limit: 0,
          limit_remaining: null,
          limit_reached: false,
        }),
      );
    if (p === "/projects") return route.fulfill(json(F.projects));
    if (p === "/models/readiness") return route.fulfill(json(F.readiness));
    if (p === "/models/routing") return route.fulfill(json(F.routing));
    if (p === "/models") return route.fulfill(json({ roles: [], models: [], presets: {}, preset_names: [], available_providers: [], effective_routing: {}, user_routing: null, deployment_routing: {} }));
    if (p === "/models/local/status")
      return route.fulfill(
        json({
          configured_base_url: "http://localhost:11434",
          reachable: false,
          usable: false,
          models: [],
          error: null,
          hint: null,
          install_state: "not_installed",
        }),
      );
    if (p === "/research") return route.fulfill(json(F.sessions));
    if (p.endsWith("/corpus/status")) return route.fulfill(json(F.corpusStatus));
    if (p.endsWith("/corpus/documents")) return route.fulfill(json(F.corpusDocuments));
    if (p.endsWith("/memory/status")) return route.fulfill(json(F.memoryStatus));
    if (p.endsWith("/threads")) return route.fulfill(json({ threads: [], total: 0 }));
    if (p === "/runs") return route.fulfill(json(F.runs));
    if (p.endsWith("/verification")) return route.fulfill(json(verification));
    if (p.endsWith("/stream")) return route.abort();

    const run = p.match(/^\/runs\/([0-9a-f-]+)$/);
    if (run) {
      const id = run[1];
      const summary = F.runs.runs.find((r) => r.id === id);
      const g = F.graph(runOverrides);
      if (summary && id !== F.IDS.RUN_ID) {
        // The list's other runs, projected into a graph consistent with their status.
        const bare = {
          ...g,
          run: {
            ...g.run,
            id,
            question: summary.question,
            status: summary.status,
            depth: summary.depth,
            demo: summary.demo,
            cost_usd: summary.cost_usd,
            citation_resolution_rate: summary.citation_resolution_rate,
            created_at: summary.created_at,
            error_message:
              summary.status === "FAILED"
                ? "The planner's provider returned 429 (quota exhausted) after 3 retries."
                : null,
          },
        };
        if (summary.status === "AWAITING_PLAN") {
          Object.assign(bare, {
            plans: [{ ...g.plans[0], approved_at: null }],
            sources: [],
            evidence: [],
            revisions: [],
            claims: [],
            claim_evidence_links: [],
            contradictions: [],
            reviews: [],
          });
        }
        if (summary.status === "RUNNING") {
          Object.assign(bare, {
            run: { ...bare.run, skip_plan_gate: true },
            plans: [],
            revisions: [],
            claims: [],
            claim_evidence_links: [],
            contradictions: [],
            reviews: [],
          });
        }
        if (summary.status === "FAILED") {
          Object.assign(bare, {
            plans: [],
            sources: [],
            evidence: [],
            revisions: [],
            claims: [],
            claim_evidence_links: [],
            contradictions: [],
            reviews: [],
          });
        }
        return route.fulfill(json(bare));
      }
      return route.fulfill(json(g));
    }

    return route.fulfill(json({ detail: `unmocked ${p}` }, 404));
  });
}

// Tall viewports on purpose. The app shell is `h-screen overflow-hidden` with the page in
// an inner scroller, so Playwright's fullPage capture only ever sees one viewport of it —
// making the whole page visible means making the viewport as tall as the page.
const WIDTHS = { desktop: [1440, 2600], tablet: [820, 2600], mobile: [390, 2600] };

async function shot(page, name, theme, width = "desktop") {
  const [w, h] = WIDTHS[width];
  await page.setViewportSize({ width: w, height: h });
  await page.waitForTimeout(Number(process.env.UIQA_SETTLE ?? 700));
  const file = path.join(OUT, `${name}--${theme}--${width}.png`);
  await page.screenshot({ path: file, fullPage: true });
  // Horizontal overflow is the one layout failure a screenshot hides, because the shot is
  // taken at the document width. Measure it instead of looking for it.
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  if (overflow > 1) console.log(`  ⚠ ${name} ${width}: ${overflow}px of horizontal overflow`);
  return file;
}

const PAGES = [
  ["research", "/research"],
  ["run-review", `/research/run?id=${F.IDS.RUN_ID}`],
  ["run-report", `/research/run?id=${F.IDS.RUN_ID}&tab=report`],
  ["run-claims", `/research/run?id=${F.IDS.RUN_ID}&tab=claims`],
  ["run-evidence", `/research/run?id=${F.IDS.RUN_ID}&tab=evidence`],
  ["run-sources", `/research/run?id=${F.IDS.RUN_ID}&tab=sources`],
  ["run-contradictions", `/research/run?id=${F.IDS.RUN_ID}&tab=contradictions`],
  ["run-plan", `/research/run?id=${F.IDS.RUN_PLAN}`],
  ["run-running", `/research/run?id=${F.IDS.RUN_RUNNING}`],
  ["run-failed", `/research/run?id=${F.IDS.RUN_FAILED}`],
  ["history", "/history"],
  ["project", "/project"],
  ["corpus", "/corpus"],
  ["chat", "/chat"],
  ["settings", "/settings"],
];

// The pinned @playwright/test in this repo expects a browser build the image does not
// carry; the image's own Chromium is used instead (PLAYWRIGHT_BROWSERS_PATH), as the
// environment notes recommend.
const EXECUTABLE = process.env.UIQA_CHROME ?? "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
const browser = await chromium.launch(
  fs.existsSync(EXECUTABLE) ? { executablePath: EXECUTABLE } : {},
);
const errors = [];

for (const theme of ["light", "dark"]) {
  const ctx = await browser.newContext({
    colorScheme: theme,
    // The (app) layout is a server guard on this cookie; the value is never validated
    // client-side, and /auth/me is mocked above.
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
        { origin: BASE, localStorage: [{ name: "theme", value: theme }, { name: "active_project_id", value: F.IDS.PROJECT_ID }] },
      ],
    },
  });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(`[${theme}] pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(`[${theme}] console: ${m.text()}`);
  });
  await mockApi(page);

  for (const [name, url] of PAGES) {
    process.stdout.write(`${theme} ${name}\n`);
    await page.goto(`${BASE}${url}`, { waitUntil: "domcontentloaded" }).catch(() => {});
    await shot(page, name, theme);
    // `project` is in this set because Overview's health strip is the page's one
    // multi-column layout, and a three-column grid is exactly the thing that survives a
    // desktop screenshot and breaks on a laptop.
    if (
      name === "run-review" ||
      name === "research" ||
      name === "history" ||
      name === "project"
    ) {
      await shot(page, name, theme, "mobile");
      if (name === "project") await shot(page, name, theme, "tablet");
    }
  }

  // The approved end state needs its own mock: an artifact plus a frozen verdict. A fresh
  // page rather than re-routing this one — unrouting mid-session leaves the run's
  // EventSource pointed at nothing.
  await page.close();
  const page2 = await ctx.newPage();
  page2.on("pageerror", (e) => errors.push(`[${theme}] pageerror: ${e.message}`));
  page2.on("console", (m) => {
    if (m.type() === "error") errors.push(`[${theme}] console: ${m.text()}`);
  });
  await mockApi(page2, {
    runOverrides: {
      run: { ...F.graph().run, status: "COMPLETED" },
      artifact: F.artifact,
    },
    verification: F.verificationFrozen,
  });
  await page2.goto(`${BASE}/research/run?id=${F.IDS.RUN_ID}`, { waitUntil: "domcontentloaded" });
  await shot(page2, "run-artifact", theme);
  await shot(page2, "run-artifact", theme, "mobile");

  await ctx.close();
}

await browser.close();

if (errors.length) {
  console.log("\nRuntime errors observed:");
  for (const e of [...new Set(errors)]) console.log("  " + e);
} else {
  console.log("\nNo page errors or console errors.");
}
console.log(`\nScreenshots in ${OUT}`);
