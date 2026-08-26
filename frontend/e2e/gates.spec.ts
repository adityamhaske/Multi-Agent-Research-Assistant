import { expect, test } from "./fixtures";
import { ensureProject, register, startResearch } from "./run-helpers";

/**
 * The two gates, and the live connection, against a real stack.
 *
 * Companion to `run-journey.spec.ts`, which walks the whole chain to a verified bundle.
 * These interrogate two things that journey passes through rather than examines: what the
 * design gate is allowed to claim (nothing about a report, and no artifact), and what
 * happens when the event stream drops mid-run.
 *
 * Nothing is mocked. The engine runs in the demo configuration that ships in production.
 */

test.describe("plan gate", () => {
  test.setTimeout(240_000);

  test("approving a plan resumes research and creates no artifact", async ({ page }) => {
    await register(page);
    await ensureProject(page);

    // `skipPlanGate: false` matches what the run form sends. Posted through the API rather
    // than clicked, so this spec starts from the gate deterministically instead of
    // re-testing the form the journey spec already drives.
    const runId = await startResearch(page, { skipPlanGate: false });

    // 1. The run stops at the plan, not at a report.
    // Exact: the status line above also contains "research plan".
    await expect(page.getByRole("heading", { name: "Research plan" })).toBeVisible({
      timeout: 180_000,
    });
    await expect(page.getByText(/the research plan is waiting for your approval/)).toBeVisible();

    // 2. The plan is real: the planner's tasks and the outline it chose.
    const planPanel = page.getByRole("tabpanel");
    await expect(planPanel.getByRole("listitem").first()).toBeVisible();
    await expect(page.getByText(/proposed by the planner/)).toBeVisible();

    // 3. Nothing here may read as report approval.
    await expect(page.getByText(/Approving the plan starts the research/)).toBeVisible();
    await expect(page.getByText(/approve a report and creates no artifact/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Approve report" })).toHaveCount(0);
    await expect(page.getByText("Verified artifact")).toHaveCount(0);

    // 4. No artifact exists, checked at the API rather than by reading the screen.
    const beforeApproval = await page.request.get(`/api/v1/runs/${runId}`);
    expect((await beforeApproval.json()).artifact).toBeNull();

    // 5. Approve the plan. Research resumes from the design gate — the same evidence is
    //    not re-gathered, and the run walks on to the report gate.
    await page.getByRole("button", { name: "Approve plan" }).click();
    await expect(page.getByText("What you are approving")).toBeVisible({ timeout: 180_000 });

    // 6. The plan approval is in the chain and still authorizes nothing.
    const afterPlan = await (await page.request.get(`/api/v1/runs/${runId}`)).json();
    expect(afterPlan.artifact).toBeNull();
    const planReview = afterPlan.reviews.find((r: { gate: string }) => r.gate === "PLAN");
    expect(planReview.decision).toBe("APPROVED");
    expect(planReview.revision_id).toBeNull();

    // 7. Only the report approval creates the artifact.
    await page.getByRole("button", { name: "Approve report" }).click();
    await expect(page.getByText("Verified artifact")).toBeVisible({ timeout: 60_000 });

    const final = await (await page.request.get(`/api/v1/runs/${runId}`)).json();
    expect(final.artifact).not.toBeNull();
    expect(final.artifact.review_gate).toBe("REPORT");
    expect(final.artifact.review_decision).toBe("APPROVED");
  });
});

test.describe("live stream", () => {
  test.setTimeout(240_000);

  test("recovers from a dropped connection and still reaches the terminal state", async ({
    page,
  }) => {
    await register(page);
    await ensureProject(page);

    // Cut the FIRST stream connection mid-run, then let the browser's own EventSource
    // reconnect with `Last-Event-ID`. The backend replays `agent_logs` after that id, so
    // this exercises the real replay path rather than a simulated one.
    let cut = 0;
    await page.route("**/api/v1/runs/*/stream", async (route) => {
      if (cut === 0) {
        cut += 1;
        await route.abort("connectionreset");
        return;
      }
      await route.continue();
    });

    const runId = await startResearch(page, { skipPlanGate: true });

    // The UI must not sit on RUNNING forever because a socket died: it reaches the gate.
    await expect(page.getByText("What you are approving")).toBeVisible({ timeout: 180_000 });
    expect(cut).toBeGreaterThan(0);

    // The status the page shows is the authoritative row, not the last event it happened
    // to receive.
    const graph = await (await page.request.get(`/api/v1/runs/${runId}`)).json();
    expect(graph.run.status).toBe("AWAITING_REVIEW");
    expect(graph.revisions.length).toBe(1);

    // Events are keyed by a durable id, so the backlog replay after a reconnect cannot
    // double-count: one revision, one set of evidence, no duplicates.
    expect(graph.evidence.length).toBeGreaterThan(0);
    const sequences = graph.evidence.map((e: { sequence: number }) => e.sequence);
    expect(new Set(sequences).size).toBe(sequences.length);

    // And the degraded banner is not left on screen once the run is parked at the gate.
    await expect(page.getByText(/live connection dropped/)).toHaveCount(0);
  });
});


test.describe("report gate — rework", () => {
  test.setTimeout(240_000);

  test("a rejected draft is resynthesized, counted, and approvable on the second pass", async ({
    page,
  }) => {
    // Rework is the half of the report gate that approval does not exercise: a gate whose
    // rejection did nothing would still pass every approval test. It also has to be visibly
    // *counted*, because the round limit is what stops an unbounded loop, and a user who
    // cannot see how many rounds are left cannot decide whether to spend another.
    await register(page);
    await ensureProject(page);
    const runId = await startResearch(page, { skipPlanGate: true });

    await expect(page.getByText("What you are approving")).toBeVisible({ timeout: 180_000 });

    await page.getByLabel(/feedback for a rework/i).fill(
      "Add explicit trade-offs for each approach and cite a primary source.",
    );
    await page.getByRole("button", { name: "Request rework" }).click();

    // Wait for the *second draft*, not for the rework to be recorded. "You asked for 1
    // rework" renders the moment the decision is written, before the synthesizer has run
    // again — asserting on it and then reading revisions is a race the first version of
    // this test lost, and it would have reported a resynthesis that never happened as a
    // product bug. The revision number is the signal that the new draft exists.
    await expect(page.getByText("Revision 2")).toBeVisible({ timeout: 180_000 });
    await expect(page.getByText(/you asked for 1 rework on this/i)).toBeVisible();

    // A rejection authorizes nothing, checked at the API rather than by reading the screen.
    const afterRework = await (await page.request.get(`/api/v1/runs/${runId}`)).json();
    expect(afterRework.artifact).toBeNull();
    expect(
      afterRework.reviews.filter((r: { decision: string }) => r.decision === "REWORK_REQUESTED"),
    ).toHaveLength(1);
    // The second draft is a new revision, not an edit of the first — a rework that
    // overwrote the rejected text would destroy the record of what was rejected.
    expect(afterRework.revisions.map((r: { version: number }) => r.version)).toEqual([1, 2]);

    await page.getByRole("button", { name: "Approve report" }).click();
    await expect(page.getByText("Verified artifact")).toBeVisible({ timeout: 60_000 });

    const final = await (await page.request.get(`/api/v1/runs/${runId}`)).json();
    expect(final.artifact).not.toBeNull();
    expect(final.artifact.review_gate).toBe("REPORT");
  });
});
