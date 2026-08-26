import { expect, test, waitForAuthRedirect, type Page } from "./fixtures";

/**
 * Golden journeys that are not about a research run (docs/08 §2). CI blocks merge on any
 * failure. The backend runs with LLM_MODE=fake — scripted models and fixture retrievers —
 * so these are deterministic and free.
 *
 * **The run journeys live in `run-journey.spec.ts` and `gates.spec.ts`.** This file used to
 * hold five more, all of which drove a second start form on a second pipeline; that form is
 * gone, and the journeys it drove were re-testing the design gate, streaming, approval,
 * export and the bundle — every one of which those two specs already exercise against the
 * flow the product actually ships. What remains here is the corpus journey, which belongs
 * to neither.
 */


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


/** Register a fresh account and land in the app. */
async function registerAndLogin(page: Page): Promise<string> {
  const email = uniqueEmail();
  await page.goto("/login");
  await page.getByRole("tab", { name: /create account/i }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await submitAuthForm(page);
  await waitForAuthRedirect(page, /\/(research|project)/);
  return email;
}




/**
 * Give this browser an active project, creating one if the account has none.
 *
 * Corpus, Overview and Chat are all scoped to an *active* project held in client state,
 * and a freshly-registered account has neither a selection nor a project: the switcher
 * says "No projects created yet" and the page says "No active project". The research
 * journeys never hit either, because `POST /research` resolves — and lazily creates —
 * the user's default project server-side. So the two halves of the app disagree about
 * whether "no project" is a state the user has to resolve, and only the corpus half
 * makes them do it.
 *
 * Driven through the switcher rather than seeded, because that is the path a real
 * first-run user takes. Worth the words because of how the failure presented: both
 * `setInputFiles` and `click` wait for a locator that never appears, so the journey
 * burned its full 180s timeout and reported "timeout" rather than "there was no
 * project" — twice, for two different missing preconditions.
 */
async function ensureActiveProject(page: Page): Promise<void> {
  await page.getByRole("button", { name: /select project/i }).click();

  const existing = page.getByRole("option");
  if ((await existing.count()) === 0) {
    await page.getByRole("button", { name: "+ New" }).click();
    // By label and by role, never by placeholder or by exact copy. This journey sat
    // broken on `getByPlaceholder("Project name...")` and `name: "Create"` after the
    // switcher was restyled, and nothing caught it: golden-e2e only runs once the backend
    // and frontend jobs are green, and they were not.
    await page.getByLabel(/project name/i).fill("E2E Project");
    await page.getByRole("button", { name: /create project/i }).click();
  } else {
    await existing.first().click();
  }

  await expect(page.getByRole("listbox", { name: "Projects" })).toBeHidden();
}

test.describe("Golden journey 6 — corpus documents preview in place", () => {
  test("uploads a document and reads it without leaving the page", async ({ page }) => {
    await registerAndLogin(page);
    await ensureActiveProject(page);
    await page.goto("/corpus");

    await page.setInputFiles('input[type="file"]', {
      name: "grounding.md",
      mimeType: "text/markdown",
      buffer: Buffer.from(
        "# Grounding metrics\n\nRecall improved by 12 points on the held-out split.\n",
      ),
    });

    // The row appears once ingestion finishes, and offers a preview rather than a
    // download — the behaviour change this journey exists to pin.
    const preview = page.getByRole("button", { name: "Preview" }).first();
    await expect(preview).toBeVisible({ timeout: 120_000 });
    await preview.click();

    const drawer = page.getByRole("dialog", { name: /Preview of grounding\.md/ });
    await expect(drawer).toBeVisible();
    await expect(drawer.getByText("Recall improved by 12 points")).toBeVisible();

    // Escape closes it and the corpus list is still there — "in place" is the claim.
    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();
    await expect(page.getByRole("button", { name: "Preview" }).first()).toBeVisible();
  });
});
