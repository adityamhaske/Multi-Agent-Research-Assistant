import { isValidElement } from "react";
import { expect, it, vi } from "vitest";

vi.mock("next/headers", () => ({ cookies: async () => ({ has: () => true }) }));
vi.mock("next/navigation", () => ({ redirect: vi.fn() }));

import { ActiveProjectProvider } from "@/components/ActiveProject";

import AppLayout from "./layout";

it("gives every app page the active project", async () => {
  // The provider lives here rather than in the root providers, so the public site never
  // fetches projects. Every surface that reads it is under this layout; if it moved
  // inside AppShell or was dropped, useActiveProject would throw at runtime, not at build.
  const tree = await AppLayout({ children: <p>page</p> });
  expect(isValidElement(tree) && tree.type).toBe(ActiveProjectProvider);
});
