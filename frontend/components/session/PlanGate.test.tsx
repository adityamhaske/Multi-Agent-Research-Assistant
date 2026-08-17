import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PlanGate } from "./PlanGate";
import type { SessionDetail, SessionPlan } from "@/lib/types";

/**
 * The gate's job is to submit the reviewer's decision faithfully (docs/07 §2, Phase 4).
 * Everything asserted here is about the request body, because that is the only part the
 * backend acts on — an excluded task that still reaches the API is researched anyway,
 * and the reviewer would never know their edit was dropped.
 */

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, apiFetch };
});
vi.mock("react-hot-toast", () => ({
  default: { success: vi.fn(), error: vi.fn() },
}));

const PLAN: SessionPlan = {
  session_id: "s1",
  status: "AWAITING_PLAN",
  tasks: [
    {
      id: 1,
      query: "background and definitions",
      rationale: "context",
      subtopics: [],
      include: true,
      source_hint: null,
    },
    {
      id: 2,
      query: "current state and data",
      rationale: "evidence",
      subtopics: [],
      include: true,
      source_hint: null,
    },
  ],
  outline: [],
  approved_at: null,
};

const SESSION = {
  session_id: "s1",
  status: "AWAITING_PLAN",
  total_cost_usd: 0,
} as unknown as SessionDetail;

function renderGate() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <PlanGate session={SESSION} />
    </QueryClientProvider>,
  );
}

/** The body of the POST to /research/s1/plan, once one has been made. */
async function submittedBody() {
  await waitFor(() =>
    expect(apiFetch).toHaveBeenCalledWith("/research/s1/plan", expect.objectContaining({ method: "POST" })),
  );
  const call = apiFetch.mock.calls.find(([path, opts]) => path === "/research/s1/plan" && opts?.method === "POST");
  return call![1].body as {
    tasks: { id: number; query: string }[];
    outline: { title: string }[];
  };
}

beforeEach(() => {
  apiFetch.mockReset();
  apiFetch.mockImplementation((path: string, opts?: { method?: string }) => {
    if (path === "/research/s1/plan" && (!opts || opts.method !== "POST")) return Promise.resolve(PLAN);
    if (path === "/research/outline-templates") return Promise.resolve([]);
    return Promise.resolve({ ...PLAN, approved_at: "2026-08-16T00:00:00Z" });
  });
});

afterEach(() => vi.clearAllMocks());

describe("PlanGate", () => {
  it("shows the planner's proposal as editable queries", async () => {
    renderGate();
    expect(await screen.findByDisplayValue("background and definitions")).toBeInTheDocument();
    expect(screen.getByDisplayValue("current state and data")).toBeInTheDocument();
  });

  it("submits an edited query, not the one the planner proposed", async () => {
    const user = userEvent.setup();
    renderGate();
    const field = await screen.findByDisplayValue("background and definitions");

    await user.clear(field);
    await user.type(field, "grounding metrics");
    await user.click(screen.getByRole("button", { name: /approve & start research/i }));

    const body = await submittedBody();
    expect(body.tasks.map((t) => t.query)).toEqual(["grounding metrics", "current state and data"]);
  });

  it("drops an excluded task from the request entirely", async () => {
    // Not merely `include: false` in the payload — the reviewer removed it, so it must
    // not be in the list the executor is handed.
    const user = userEvent.setup();
    renderGate();
    await screen.findByDisplayValue("background and definitions");

    await user.click(screen.getByRole("checkbox", { name: /include “current state and data”/i }));
    await user.click(screen.getByRole("button", { name: /approve & start research/i }));

    const body = await submittedBody();
    expect(body.tasks.map((t) => t.query)).toEqual(["background and definitions"]);
  });

  it("renumbers ids 1..n so they match what evidence is tagged with", async () => {
    const user = userEvent.setup();
    renderGate();
    await screen.findByDisplayValue("background and definitions");

    await user.click(screen.getByRole("checkbox", { name: /include “background and definitions”/i }));
    await user.click(screen.getByRole("button", { name: /approve & start research/i }));

    const body = await submittedBody();
    expect(body.tasks).toHaveLength(1);
    expect(body.tasks[0].id).toBe(1);
  });

  it("refuses to submit an empty plan, and says why", async () => {
    const user = userEvent.setup();
    renderGate();
    await screen.findByDisplayValue("background and definitions");

    for (const label of [/include “background and definitions”/i, /include “current state and data”/i]) {
      await user.click(screen.getByRole("checkbox", { name: label }));
    }

    expect(screen.getByRole("button", { name: /approve & start research/i })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent(/at least one subtopic/i);
    expect(apiFetch).not.toHaveBeenCalledWith("/research/s1/plan", expect.objectContaining({ method: "POST" }));
  });

  it("reorders tasks, and submits them in the order shown", async () => {
    const user = userEvent.setup();
    renderGate();
    await screen.findByDisplayValue("background and definitions");

    await user.click(screen.getByRole("button", { name: /move task 2 earlier/i }));
    await user.click(screen.getByRole("button", { name: /approve & start research/i }));

    const body = await submittedBody();
    expect(body.tasks.map((t) => t.query)).toEqual([
      "current state and data",
      "background and definitions",
    ]);
  });
});
