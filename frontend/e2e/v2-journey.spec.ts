import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

/**
 * The V2 journey, end to end, through the browser.
 *
 *   start research → real execution → evidence → claims → sources → contradictions
 *   → review → approve → verified artifact → download bundle → standalone verifier PASS
 *
 * The backend runs with `LLM_MODE=fake` — scripted models and fixture retrievers, the same
 * demo path that ships in production — so the run is deterministic and free. **Nothing about
 * the journey is mocked**: the request goes to the real API, Celery drives the real
 * LangGraph engine, the V2 domain rows are written by the real adapter, and the downloaded
 * bundle is checked by `research_engine/verify_bundle.py` as a subprocess.
 *
 * The last step is the one that matters. A UI that renders six green ticks it computed
 * itself would pass a test that only looked at the screen; this shells out to the shipped
 * verifier and requires *it* to agree.
 */

const QUESTION =
  "What are the leading approaches to long-term memory in LLM agents, and their trade-offs?";
const PASSWORD = "e2e-correct-horse-battery-42";

function uniqueEmail(): string {
  return `v2-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@mara-demo.dev`;
}

async function register(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByRole("tab", { name: /register|create/i }).click().catch(() => {});
  await page.getByLabel(/email/i).fill(uniqueEmail());
  await page.getByLabel(/^password/i).fill(PASSWORD);
  const submit = page.locator('form button[type="submit"]');
  await expect(submit).toHaveAccessibleName(/\S/);
  await submit.click();
  await page.waitForURL(/\/(dashboard|project|research)/, { timeout: 60_000 });
}

test.describe("V2 research journey", () => {
  // The engine runs a full plan → execute → critic → synthesize cycle even in fake mode.
  test.setTimeout(240_000);

  test("question to verified artifact, checked by the standalone verifier", async ({ page }) => {
    await register(page);

    // 1–2. Open Research and start a run.
    await page.goto("/research");
    await expect(page.getByRole("heading", { name: "Research" })).toBeVisible();
    await page.getByLabel("Research question").fill(QUESTION);
    await page.getByRole("button", { name: "Start research" }).click();

    // 3. The run page opens on a real run id, and reports real state — not a spinner the
    // frontend invented.
    await page.waitForURL(/\/research\/run\?id=[0-9a-f-]{36}/, { timeout: 60_000 });
    const runId = new URL(page.url()).searchParams.get("id")!;
    await expect(page.getByRole("heading", { name: QUESTION })).toBeVisible();

    // 4. Wait for the engine to finish and the draft to reach the review gate. The Review
    // tab's heading only renders once a revision exists.
    await expect(page.getByText("What you are approving")).toBeVisible({ timeout: 180_000 });

    // 5–8. The chain, tab by tab. Each assertion is about a distinction the product makes,
    // not merely about a row being present.
    await page.getByRole("tab", { name: /Evidence/ }).click();
    await expect(page.getByText("Unchecked").first()).toBeVisible();
    await expect(page.getByText(/Retrieved is not\s+verified/)).toBeVisible();

    await page.getByRole("tab", { name: /Claims/ }).click();
    await expect(page.getByText(/supporting evidence item/).first()).toBeVisible();

    await page.getByRole("tab", { name: /Sources/ }).click();
    await expect(page.getByText(/Retrieved is not cited/)).toBeVisible();

    await page.getByRole("tab", { name: /Contradictions/ }).click();
    // Either conflicts were found or they were not — both are legitimate outcomes of a real
    // run, and both must be *stated*. What must never happen is silence.
    await expect(
      page
        .getByText(/No conflicting claims recorded/)
        .or(page.getByText(/Surfaced, not resolved/).first()),
    ).toBeVisible();

    // 9–10. Review and approve.
    await page.getByRole("tab", { name: "Review" }).click();
    await expect(page.getByText(/verifiable research artifact/)).toBeVisible();
    await page.getByRole("button", { name: "Approve report" }).click();

    // 11. The artifact appears, with the verifier's own six checks.
    await expect(page.getByText("Verified artifact")).toBeVisible({ timeout: 60_000 });
    for (const label of [
      "Bundle integrity",
      "Report integrity",
      "Evidence integrity",
      "Citation resolution",
      "Claim / evidence linkage",
      "Approval chain",
    ]) {
      await expect(page.getByText(label)).toBeVisible();
    }

    // 12. Download the bundle through the UI control a user would actually click.
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("link", { name: "Verification bundle" }).click(),
    ]);
    const bundlePath = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "v2-bundle-")), "b.json");
    await download.saveAs(bundlePath);

    const bundle = JSON.parse(fs.readFileSync(bundlePath, "utf8"));
    expect(bundle.session_id).toBe(runId);
    expect(bundle.claims.length).toBeGreaterThan(0);
    expect(bundle.evidence.length).toBeGreaterThan(0);
    expect(bundle.approval_chain.some((a: { action: string }) => a.action === "approved")).toBe(
      true,
    );

    // 13–14. The shipped standalone verifier, as a subprocess. No network, no AI, and no
    // frontend assertion standing in for it.
    const verifier = spawnSync(
      "python",
      ["-m", "research_engine.verify_bundle", bundlePath, "--json"],
      { cwd: path.resolve(process.cwd(), "../backend"), encoding: "utf8" },
    );
    expect(verifier.error, `verifier failed to launch: ${verifier.error?.message}`).toBeFalsy();
    const verdict = JSON.parse(verifier.stdout);
    expect(verdict.passed, `verifier rejected the bundle: ${verifier.stdout}`).toBe(true);
    expect(verifier.status).toBe(0);
  });
});
