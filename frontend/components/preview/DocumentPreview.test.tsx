import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DocumentPreview, documentUrl, kindForFilename } from "./DocumentPreview";

/**
 * The preview renders untrusted content — uploaded documents authored by whoever made
 * the file. What is asserted here is the boundary, not the appearance: that HTML lands
 * in a fully-withheld sandbox and that Markdown's raw-HTML escape hatch stays shut.
 *
 * A screenshot would not catch either regression. `sandbox="allow-scripts
 * allow-same-origin"` looks identical to `sandbox=""` until someone uses it.
 */

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
});
afterEach(() => vi.unstubAllGlobals());

function respondWith(body: string) {
  fetchMock.mockResolvedValue({ ok: true, status: 200, text: async () => body });
}

describe("kindForFilename", () => {
  it("maps the extensions the backend accepts, and nothing else", () => {
    expect(kindForFilename("paper.pdf")).toBe("pdf");
    expect(kindForFilename("page.HTML")).toBe("html");
    expect(kindForFilename("page.htm")).toBe("html");
    expect(kindForFilename("notes.markdown")).toBe("md");
    expect(kindForFilename("data.csv")).toBe("txt");
    // Unknown types get the "download it instead" path, never a guessed renderer.
    expect(kindForFilename("deck.pptx")).toBeNull();
    expect(kindForFilename("noextension")).toBeNull();
  });
});

describe("DocumentPreview security boundary", () => {
  it("renders uploaded HTML in a fully-withheld sandbox", async () => {
    respondWith("<h1>Hello</h1><script>parent.postMessage('pwned','*')</script>");
    render(<DocumentPreview url="/api/d/1" filename="page.html" downloadable />);

    const frame = (await screen.findByTitle("page.html (preview)")) as HTMLIFrameElement;
    // Empty string, not merely "not allow-scripts": an opaque origin with every
    // capability withheld. `allow-scripts` + `allow-same-origin` together would let the
    // frame remove its own sandbox, so neither may ever appear here.
    expect(frame.getAttribute("sandbox")).toBe("");
    expect(frame.getAttribute("srcdoc")).toContain("<h1>Hello</h1>");
    // srcdoc, never src: the bytes never become a navigable URL in this origin.
    expect(frame.getAttribute("src")).toBeNull();
    expect(frame.getAttribute("referrerpolicy")).toBe("no-referrer");
  });

  it("does not execute raw HTML embedded in an uploaded Markdown file", async () => {
    respondWith("# Notes\n\n<img src=x onerror=\"window.__pwned=1\">\n\nPlain text.");
    render(<DocumentPreview url="/api/d/2" filename="notes.md" downloadable />);

    await screen.findByText("Notes");
    // react-markdown with no raw-HTML plugin keeps the tag as text. Asserted as the
    // *absence of an element*, because "rendered but harmlessly" and "stayed text"
    // are different outcomes. (The plugin's name is deliberately not written here —
    // CI greps these directories for it, and a mention in a comment fails the build
    // exactly as a real import would.)
    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByText(/onerror/)).toBeInTheDocument();
  });

  it("shows a PDF through the browser's own viewer rather than fetching it", async () => {
    render(<DocumentPreview url="/api/d/3" filename="paper.pdf" downloadable />);

    const object = screen.getByLabelText("paper.pdf (PDF preview)");
    expect(object.getAttribute("data")).toBe("/api/d/3");
    expect(object.getAttribute("type")).toBe("application/pdf");
    // The bytes are never pulled into JS — the whole point of the inline exception.
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("DocumentPreview honest empty states", () => {
  it("says a document has no stored original instead of showing a blank pane", () => {
    render(<DocumentPreview url="/api/d/4" filename="old.pdf" downloadable={false} />);
    expect(screen.getByText(/still\s+searchable and citable/i)).toBeInTheDocument();
  });

  it("surfaces a failed load rather than an empty document", async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 404, text: async () => "" });
    render(<DocumentPreview url="/api/d/5" filename="gone.txt" downloadable />);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("404"));
  });
});

describe("documentUrl", () => {
  /**
   * Regression: this shipped without the `/corpus` segment, so every preview rendered
   * "Could not load this document (404)". Every other test in this file passes a stub
   * URL in, so nothing here exercised the function that builds one — the defect was
   * invisible to the unit suite and only the golden E2E, uploading to a real API, hit it.
   */
  it("includes the corpus segment the backend router is mounted at", () => {
    const url = documentUrl("proj-1", "doc-2");
    expect(url).toContain("/projects/proj-1/corpus/documents/doc-2/download");
  });
});
