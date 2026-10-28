import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CitedPassage } from "./CitedPassage";

/**
 * A corpus citation in place (RFC V3.1 §12, AC-20): the extracted text with the cited span
 * marked, and — for a PDF — the original opened at the cited page. Both come through the
 * run's own cited-documents route (§7.3), never the project's corpus.
 */

const TEXT = "Intro text. The cited sentence is here. Closing text.";

function extracted(filename: string) {
  return {
    filename,
    kind: filename.split(".").pop(),
    text: TEXT,
    segments: [[0, "page 1"], [12, "page 3"]],
    extraction_mode: "verbatim",
  };
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("URL", { ...URL, createObjectURL: () => "blob:cited", revokeObjectURL: vi.fn() });
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => vi.unstubAllGlobals());

function respond(filename: string) {
  fetchMock.mockImplementation(async (url: string) =>
    !url.endsWith("/download")
      ? new Response(JSON.stringify(extracted(filename)), {
          headers: { "content-type": "application/json" },
        })
      : { ok: true, status: 200, blob: async () => new Blob(["%PDF"]) },
  );
}

function renderPassage(page: number | null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CitedPassage
        owner="/runs/r1"
        locator={{ documentId: "doc-1", page, start: 12, end: 39 }}
      />
    </QueryClientProvider>,
  );
}

describe("CitedPassage", () => {
  it("marks the cited span in the text the run's own route returns", async () => {
    respond("paper.pdf");
    renderPassage(3);
    expect(await screen.findByText("The cited sentence is here.")).toHaveProperty("tagName", "MARK");
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/runs\/r1\/cited-documents\/doc-1$/);
  });

  it("opens the original PDF at the cited page", async () => {
    respond("paper.pdf");
    renderPassage(3);

    await userEvent.click(await screen.findByRole("button", { name: "Open the PDF at page 3 →" }));

    const object = await screen.findByLabelText("paper.pdf (PDF preview)");
    expect(object.getAttribute("data")).toBe("blob:cited#page=3");
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/runs/r1/cited-documents/doc-1/download"),
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("offers no PDF for a document that is not one", async () => {
    respond("notes.docx");
    renderPassage(null);
    await screen.findByText("The cited sentence is here.");
    expect(screen.queryByRole("button", { name: /Open the PDF/ })).toBeNull();
  });
});
