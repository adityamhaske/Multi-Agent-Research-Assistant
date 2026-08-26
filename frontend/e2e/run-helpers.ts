import { expect, waitForAuthRedirect, type Page } from "./fixtures";

/**
 * Shared steps for the run journeys.
 *
 * Extracted when the gate and stream specs needed the same first three actions. Everything
 * here is a *precondition* — an account, a project, a started run — and none of it touches
 * the research execution, which every spec drives through the real UI and the real worker.
 */

export const QUESTION =
  "What are the leading approaches to long-term memory in LLM agents, and their trade-offs?";

const PASSWORD = "e2e-correct-horse-battery-42";

function uniqueEmail(): string {
  return `e2e-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@mara-demo.dev`;
}

export async function register(page: Page): Promise<void> {
  await page.goto("/login");
  await page
    .getByRole("tab", { name: /register|create/i })
    .click()
    .catch(() => {});
  await page.getByLabel(/email/i).fill(uniqueEmail());
  await page.getByLabel(/^password/i).fill(PASSWORD);
  // Located by submit type, not by label: this button's copy has changed once already and
  // silently broke every journey (see golden.spec.ts).
  const submit = page.locator('form button[type="submit"]');
  await expect(submit).toHaveAccessibleName(/\S/);
  await submit.click();
  await waitForAuthRedirect(page, /\/(project|research)/, 60_000);
}

/** A project, through the app's own API. Research is always project-scoped. */
export async function ensureProject(page: Page): Promise<void> {
  const existing = await page.request.get("/api/v1/projects?archived=false");
  expect(existing.ok(), `projects list failed: ${existing.status()}`).toBe(true);
  const { projects } = (await existing.json()) as { projects: unknown[] };
  if (projects.length > 0) return;

  const created = await page.request.post("/api/v1/projects", {
    data: { name: `E2E ${Date.now()}`, description: "E2E journey" },
  });
  expect(created.ok(), `project create failed: ${created.status()}`).toBe(true);
}

/**
 * Start a run and land on its workspace.
 *
 * `skipPlanGate` is a real product option, not a test hook: the run form sends `false` so a
 * user meets the design gate, while a script POSTing an un-updated body keeps the ungated
 * journey (AGENTS.md, "three defaults, and they disagree on purpose"). Both populations are
 * real, so both are reachable here — threaded through the API for determinism rather than
 * clicked, since the form itself is exercised by `run-journey.spec.ts`.
 */
export async function startResearch(
  page: Page,
  { skipPlanGate }: { skipPlanGate: boolean },
): Promise<string> {
  const projects = (await (await page.request.get("/api/v1/projects?archived=false")).json())
    .projects as { id: string }[];

  const created = await page.request.post("/api/v1/runs", {
    data: {
      project_id: projects[0]!.id,
      question: QUESTION,
      depth: "fast",
      skip_plan_gate: skipPlanGate,
    },
  });
  expect(created.ok(), `run create failed: ${created.status()}`).toBe(true);
  const runId = (await created.json()).run_id as string;

  await page.goto(`/research/run?id=${runId}`);
  await expect(page.getByRole("heading", { name: QUESTION })).toBeVisible();
  return runId;
}
