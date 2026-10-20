import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { Providers } from "./Providers";

const fetchMock = vi.fn();

beforeEach(() => {
  // next-themes reads the colour-scheme media query; jsdom has no matchMedia.
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn() })),
  );
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  fetchMock.mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ projects: [] }),
    text: async () => JSON.stringify({ projects: [] }),
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

it("asks the API for nothing on a page outside the app", async () => {
  // The public site (app/(site)/) is published to GitHub Pages with no backend behind it,
  // and renders inside these providers. Anything they fetch is a 404 in every visitor's
  // console: the active-project query did that on every page of the site.
  render(
    <Providers>
      <p>public page</p>
    </Providers>,
  );

  expect(await screen.findByText("public page")).toBeInTheDocument();
  await new Promise((resolve) => setTimeout(resolve, 50));
  expect(fetchMock).not.toHaveBeenCalled();
});
