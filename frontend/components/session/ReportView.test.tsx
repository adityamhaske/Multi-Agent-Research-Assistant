import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SessionDetail } from "@/lib/types";

import { ReportView } from "./ReportView";

/**
 * The export controls (M0C).
 *
 * `.bundle.json` is the hash-verifiable artifact the landing page, the login page, the
 * settings copy and the comparison table all advertise. It shipped as a server endpoint
 * with **no control anywhere in the app**: `ReportView` offered `.md` and PDF only, and
 * the only way to obtain a bundle was to construct the URL by hand.
 *
 * These assert the request the button makes and the filename it saves under, because those
 * are the two things that decide whether the file a user ends up with is the one the
 * verifier can read.
 */

vi.mock("react-hot-toast", () => ({
  default: { success: vi.fn(), error: vi.fn() },
}));

// ChatPanel opens an EventSource and does its own fetching; it is not under test here.
vi.mock("./ChatPanel", () => ({
  ChatPanel: () => <div data-testid="chat-panel" />,
}));

const SESSION: SessionDetail = {
  session_id: "11111111-2222-3333-4444-555555555555",
  project_id: "p1",
  status: "COMPLETED",
  prompt: "What is retrieval-augmented generation?",
  research_depth: "fast",
  total_cost_usd: 0.12,
  total_tokens_input: 100,
  total_tokens_output: 200,
  elapsed_seconds: 42,
  rework_count: 0,
  created_at: "2026-08-17T10:00:00Z",
  updated_at: "2026-08-17T10:05:00Z",
  archived_at: null,
  corpus_mode: false,
  demo: false,
  citation_resolution_rate: 1,
  model_routing: { planner: "google:gemini-2.5-pro" },
  draft_report: null,
  final_report: "# Findings\n\nA claim that is long enough to count [1].\n",
  sources: [
    {
      index: 1,
      url: "https://example.org/a",
      title: "A source",
      snippet: "supporting text",
      snippets: ["supporting text"],
    },
  ],
  error_message: null,
};

let clicked: HTMLAnchorElement | null = null;

beforeEach(() => {
  clicked = null;
  // jsdom has no download behaviour; capture the anchor the component builds instead.
  // The component appends the anchor to the body before clicking it, so reading it back
  // from the DOM avoids aliasing `this` out of the mock (which eslint rejects).
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {
    clicked = document.querySelector<HTMLAnchorElement>("body > a[download]");
  });
  vi.stubGlobal("URL", {
    ...URL,
    createObjectURL: vi.fn(() => "blob:mock"),
    revokeObjectURL: vi.fn(),
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}", { status: 200, headers: { "content-type": "application/json" } })),
  );
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("export controls", () => {
  it("offers all three export formats", () => {
    render(<ReportView session={SESSION} />);
    expect(screen.getByRole("button", { name: ".md" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "PDF" })).toBeInTheDocument();
    // The one that did not exist.
    expect(screen.getByRole("button", { name: ".bundle.json" })).toBeInTheDocument();
  });

  it("requests the bundle from the endpoint that serves it", async () => {
    render(<ReportView session={SESSION} />);
    await userEvent.click(screen.getByRole("button", { name: ".bundle.json" }));

    await waitFor(() => expect(fetch).toHaveBeenCalled());
    const [url, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe(`/api/v1/research/${SESSION.session_id}/export.bundle.json`);
    // Same-origin with the httpOnly cookie — the app never holds a token to send.
    expect(init).toMatchObject({ credentials: "include" });
  });

  it("saves the bundle under a name the verifier is documented against", async () => {
    render(<ReportView session={SESSION} />);
    await userEvent.click(screen.getByRole("button", { name: ".bundle.json" }));

    await waitFor(() => expect(clicked).not.toBeNull());
    // `research-<8 hex>.bundle.json` — matches the Content-Disposition both hosts send
    // and the filename in the verify instructions.
    expect(clicked!.download).toBe("research-11111111.bundle.json");
  });

  it("still saves .md under its own extension", async () => {
    render(<ReportView session={SESSION} />);
    await userEvent.click(screen.getByRole("button", { name: ".md" }));

    await waitFor(() => expect(clicked).not.toBeNull());
    expect(clicked!.download).toBe("research-11111111.md");
  });

  it("surfaces the server's reason when a bundle is refused", async () => {
    const toast = (await import("react-hot-toast")).default;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({ detail: "Bundle export is only available for COMPLETED sessions." }),
            { status: 400, headers: { "content-type": "application/json" } },
          ),
      ),
    );

    render(<ReportView session={SESSION} />);
    await userEvent.click(screen.getByRole("button", { name: ".bundle.json" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Bundle export is only available for COMPLETED sessions.",
      ),
    );
    // A refused export must not produce a file — a 400 saved as `.bundle.json` would be
    // a download that fails verification for reasons the user cannot diagnose.
    expect(clicked).toBeNull();
  });
});

describe("verifier instructions", () => {
  it("explains how to check the artifact, with the exact command", async () => {
    render(<ReportView session={SESSION} />);

    const trigger = screen.getByRole("button", { name: /verify this report independently/i });
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    await userEvent.click(trigger);

    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByText(/python -m research_engine\.verify_bundle/),
    ).toBeInTheDocument();
  });

  it("keeps the instructions collapsed until asked", () => {
    render(<ReportView session={SESSION} />);
    expect(screen.queryByText(/python -m research_engine\.verify_bundle/)).toBeNull();
  });
});
