import { expect, test } from "./fixtures";
import { ensureProject, register, startResearch } from "./v2-helpers";

/**
 * The two gates, and the live connection, against a real stack.
 *
 * Companion to `v2-journey.spec.ts`, which covers question → artifact with the plan gate
 * skipped. These cover what that one deliberately does not: the design gate as a user meets
 * it, and what happens when the event stream drops mid-run.
 *
 * Nothing is mocked. The engine runs in the demo configuration that ships in production.
 */

test.describe("V2 plan gate", () => {
  test.setTimeout(240_000);

  test("approving a plan resumes research and creates no artifact", async ({ page }) => {
    await register(page);
    await ensureProject(page);

    // `skipPlanGate: false` is the product default for a run started from the form; the
    // journey spec uses the other branch, so this is the one that reaches the design gate.
    const runId = await startResearch(page, { skipPlanGate: false });

    // 1. The run stops at the plan, not at a report.
    // Exact: the status line above also contains "research plan".
    await expect(page.getByRole("heading", { name: "Research plan" })).toBeVisible({
      timeout: 180_000,
    });
    await expect(page.getByText(/Paused: the research plan is waiting/)).toBeVisible();

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
    const beforeApproval = await page.request.get(`/api/v1/v2/runs/${runId}`);
    expect((await beforeApproval.json()).artifact).toBeNull();

    // 5. Approve the plan. Research resumes from the design gate — the same evidence is
    //    not re-gathered, and the run walks on to the report gate.
    await page.getByRole("button", { name: "Approve plan" }).click();
    await expect(page.getByText("What you are approving")).toBeVisible({ timeout: 180_000 });

    // 6. The plan approval is in the chain and still authorizes nothing.
    const afterPlan = await (await page.request.get(`/api/v1/v2/runs/${runId}`)).json();
    expect(afterPlan.artifact).toBeNull();
    const planReview = afterPlan.reviews.find((r: { gate: string }) => r.gate === "PLAN");
    expect(planReview.decision).toBe("APPROVED");
    expect(planReview.revision_id).toBeNull();

    // 7. Only the report approval creates the artifact.
    await page.getByRole("button", { name: "Approve report" }).click();
    await expect(page.getByText("Verified artifact")).toBeVisible({ timeout: 60_000 });

    const final = await (await page.request.get(`/api/v1/v2/runs/${runId}`)).json();
    expect(final.artifact).not.toBeNull();
    expect(final.artifact.review_gate).toBe("REPORT");
    expect(final.artifact.review_decision).toBe("APPROVED");
  });
});

test.describe("V2 live stream", () => {
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
    await page.route("**/api/v1/v2/runs/*/stream", async (route) => {
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
    const graph = await (await page.request.get(`/api/v1/v2/runs/${runId}`)).json();
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
