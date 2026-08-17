import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PreviewDrawer } from "./PreviewDrawer";

/**
 * The drawer's keyboard contract (docs/07 §2, Phase 7).
 *
 * `aria-modal="true"` is a promise that everything outside the dialog is inert. Without
 * a focus trap that promise is a lie — a keyboard user tabs straight out into a page
 * their screen reader has been told does not exist. The first version of this component
 * made exactly that mistake, which is why it is pinned rather than assumed.
 */

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, status: 200, text: async () => "hello" }),
  );
});
afterEach(() => vi.unstubAllGlobals());

function renderDrawer(onClose = vi.fn()) {
  render(
    <>
      <button type="button">outside before</button>
      <PreviewDrawer
        open
        onClose={onClose}
        url="/api/d/1"
        filename="notes.txt"
        downloadable
      />
      <button type="button">outside after</button>
    </>,
  );
  return onClose;
}

describe("PreviewDrawer keyboard contract", () => {
  it("labels itself as a modal dialog naming the document", () => {
    renderDrawer();
    expect(
      screen.getByRole("dialog", { name: "Preview of notes.txt" }),
    ).toHaveAttribute("aria-modal", "true");
  });

  it("closes on Escape", async () => {
    const onClose = renderDrawer();
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("keeps Tab inside the dialog rather than leaking to the page behind it", async () => {
    const user = userEvent.setup();
    renderDrawer();

    // Tab from the last control must cycle to the first, not reach "outside after".
    const close = screen.getByRole("button", { name: "Close" });
    close.focus();
    await user.tab();

    expect(document.activeElement).not.toBe(
      screen.getByRole("button", { name: "outside after" }),
    );
    expect(
      screen.getByRole("dialog", { name: "Preview of notes.txt" }).contains(document.activeElement),
    ).toBe(true);
  });
});
