import { act } from "react";
import { hydrateRoot } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { afterEach, expect, it, vi } from "vitest";

// next-themes keeps the theme in the browser, so its server render has no resolvedTheme.
// The tests switch this between the server pass and the browser's hydrating pass, which is
// exactly how the two disagree in production.
let theme: string | undefined;
vi.mock("next-themes", () => ({
  useTheme: () => ({ resolvedTheme: theme, setTheme: vi.fn() }),
}));

import { AppearanceSection } from "./SectionContent";

afterEach(() => {
  document.body.innerHTML = "";
});

async function hydrateAfterServerRender(browserTheme: string) {
  theme = undefined;
  const container = document.createElement("div");
  container.innerHTML = renderToString(<AppearanceSection />);
  document.body.appendChild(container);
  theme = browserTheme;
  const mismatches: unknown[] = [];
  await act(async () => {
    hydrateRoot(container, <AppearanceSection />, {
      onRecoverableError: (error) => mismatches.push(error),
    });
  });
  return { container, mismatches };
}

it("hydrates the theme picker without a mismatch, whichever theme the browser holds", async () => {
  // React error 418 on every full load of /settings/appearance: the picker rendered its
  // selection from resolvedTheme, undefined on the server and set in the browser.
  for (const browserTheme of ["light", "dark"]) {
    const { mismatches } = await hydrateAfterServerRender(browserTheme);
    expect(mismatches, `hydrating with ${browserTheme}`).toEqual([]);
  }
});

it("shows the browser's theme as selected once mounted", async () => {
  const { container } = await hydrateAfterServerRender("dark");
  const checked = container.querySelectorAll('[role="radio"][aria-checked="true"]');
  expect(checked).toHaveLength(1);
  expect(checked[0].textContent).toContain("Dark");
});
