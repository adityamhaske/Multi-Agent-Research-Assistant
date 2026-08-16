import { expect, test, type Page } from "@playwright/test";

/**
 * The three golden journeys (docs/08 §2). CI blocks merge to `main` if any fails.
 * The backend runs with LLM_MODE=fake: scripted models + fixture retrievers, so these
 * are deterministic and free.
 */

const QUERY =
  "What are the leading approaches to long-term memory in LLM agents, and their trade-offs?";

// Meets the backend password policy (>= 12 chars, not breached).
const PASSWORD = "e2e-correct-horse-battery-42";

function uniqueEmail(): string {
  // `.test` / `.example` etc. are rejected by the email validator as special-use;
  // use a normal TLD so registration validates (no deliverability check is performed).
  return `e2e-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@mara-demo.dev`;
}

/**
 * Submit the auth form, located by submit type rather than by its label.
 *
 * The label is deliberately NOT used. This button's copy changed once already — the
 * landing-page redesign renamed it "Create Account" → "Initialize Account" — and that
 * silently broke all three golden journeys plus the screenshot tool, leaving `main` red
 * for days. The failure was maximally unhelpful: a role+name query that never matches
 * makes `click()` wait for the element rather than fail, so CI burned 51 minutes to
 * report "Test timeout of 180000ms exceeded" instead of one second to report "no button
 * named /create account/i".
 *
 * The mode tab above already chose login vs register, so the form's submit control is
 * unambiguous. The accessible name is still asserted — that keeps the a11y coverage the
 * role-based query was there for, without coupling the suite to marketing copy.
 */
async function submitAuthForm(page: Page): Promise<void> {
  const submit = page.locator('form button[type="submit"]');
  await expect(submit).toHaveAccessibleName(/\S/);
  await submit.click();
}

/** Register a fresh account; the app logs straight in and lands on the dashboard. */
async function registerAndLogin(page: Page): Promise<string> {
  const email = uniqueEmail();
  await page.goto("/login");
  await page.getByRole("tab", { name: /create account/i }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await submitAuthForm(page);
  await page.waitForURL("**/dashboard");
  return email;
}

/** Submit a research query and wait for the human-review gate. */
async function startResearchToGate(page: Page): Promise<void> {
  await page.getByLabel(/research question/i).fill(QUERY);
  await page.getByRole("button", { name: /start research/i }).click();
  await page.waitForURL(/\/session\/[0-9a-f-]{36}/);

  // The session opens in the live-monitor state before any result exists.
  await expect(page.getByRole("heading", { name: "Activity" })).toBeVisible();

  // SSE delivers pipeline events into the feed (replayed from agent_logs on connect).
  await expect(page.getByLabel("Agent activity log")).toContainText(
    /planner|executor|critic|synthesizer/i,
    { timeout: 60_000 },
  );

  await expect(page.getByRole("heading", { name: /review gate/i })).toBeVisible({
    timeout: 150_000,
  });
}

test.describe("Golden journey 1 — research reaches the gate", () => {
  test("submits a query, streams pipeline events, and renders a cited draft", async ({ page }) => {
    await registerAndLogin(page);
    await startResearchToGate(page);

    // Draft body renders (a blank panel here is the bug this journey guards).
    await expect(page.getByRole("heading", { name: /draft report/i })).toBeVisible();

    // Citations UX: inline [n] chips resolved against the source table.
    const chips = page.getByRole("button", { name: /^Source \d+/ });
    await expect(chips.first()).toBeVisible();

    // The decision panel reports a non-zero source count.
    const sourceCount = page.locator("dt", { hasText: "Sources" }).locator("+ dd");
    await expect(sourceCount).not.toHaveText("0");
  });
});

test.describe("Golden journey 2 — approval completes the session", () => {
  test("approves the draft, finalizes the report, and exports markdown", async ({ page }) => {
    await registerAndLogin(page);
    await startResearchToGate(page);

    await page.getByRole("button", { name: /approve & finalize/i }).click();

    // Finalizer resumes from the checkpoint and completes.
    await expect(page.getByRole("heading", { name: "Report", exact: true })).toBeVisible({
      timeout: 150_000,
    });
    await expect(page.getByText("Completed")).toBeVisible();

    // Metrics row + sources panel.
    await expect(page.getByText("Duration")).toBeVisible();
    await expect(page.getByText("Tokens")).toBeVisible();
    await expect(page.getByRole("heading", { name: /^sources \(\d+\)$/i })).toBeVisible();

    // Export: .md downloads.
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: ".md", exact: true }).click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/\.md$/);
  });
});

test.describe("Golden journey 3 — rework loops and chat works", () => {
  test("requests rework, re-reaches the gate, approves, then chats over the report", async ({
    page,
  }) => {
    await registerAndLogin(page);
    await startResearchToGate(page);

    // Reject with feedback → pipeline resumes from the gate.
    await page
      .getByLabel(/request changes/i)
      .fill("Add explicit trade-offs for each approach and cite a primary source.");
    await page.getByRole("button", { name: /request rework/i }).click();

    // Back to the running monitor, then to the gate a second time.
    await expect(page.getByRole("heading", { name: "Activity" })).toBeVisible({ timeout: 60_000 });
    await expect(page.getByRole("heading", { name: /review gate/i })).toBeVisible({
      timeout: 150_000,
    });

    // The rework round is accounted for.
    await expect(page.getByText(/1 of 3 used/i)).toBeVisible();

    // Approve the revised draft.
    await page.getByRole("button", { name: /approve & finalize/i }).click();
    await expect(page.getByRole("heading", { name: "Report", exact: true })).toBeVisible({
      timeout: 150_000,
    });

    // Grounded follow-up chat streams an answer.
    const question = "What are the main limitations?";
    await page.getByLabel("Chat message").fill(question);
    await page.getByRole("button", { name: "Send", exact: true }).click();

    const transcript = page.getByLabel("Chat transcript");
    await expect(transcript).toContainText(question);
    // Assistant reply lands and the composer re-enables (stream finished).
    await expect(page.getByRole("button", { name: "Send", exact: true })).toBeVisible({
      timeout: 90_000,
    });
    await expect(transcript.locator("div").filter({ hasText: /\w/ }).nth(1)).toBeVisible();

    // History persists across a reload.
    await page.reload();
    await expect(page.getByLabel("Chat transcript")).toContainText(question, { timeout: 30_000 });
  });
});
