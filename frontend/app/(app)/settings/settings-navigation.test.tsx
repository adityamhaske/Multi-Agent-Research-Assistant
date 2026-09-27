import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SectionContent } from "./[section]/SectionContent";
import { generateStaticParams } from "./[section]/page";
import SettingsLayout from "./layout";

/**
 * Models and Agents are separate Settings pages: one says which model a role uses, the other
 * how the agent behaves. This pins the navigation between them and that each route renders
 * its own page — including in the desktop static export, which builds only the sections
 * `generateStaticParams` lists.
 */

vi.mock("next/navigation", () => ({ usePathname: () => "/settings/agents" }));
vi.mock("@/hooks/queries", async (original) => ({
  ...(await original<typeof import("@/hooks/queries")>()),
  useReadiness: () => ({ data: undefined }),
}));
vi.mock("@/components/settings/SettingsSearch", () => ({ SettingsSearch: () => null }));
vi.mock("@/components/settings/AgentsSection", () => ({
  AgentsSection: () => <div>agents page</div>,
}));
vi.mock("@/components/account/ModelPicker", () => ({ ModelPicker: () => <div>model picker</div> }));
vi.mock("@/components/account/CustomEndpointCard", () => ({
  CustomEndpointCard: () => <div>custom endpoint</div>,
}));
vi.mock("@/components/account/LocalLLMCard", () => ({ LocalLLMCard: () => <div>local models</div> }));

describe("settings navigation", () => {
  it("lists Agents as its own section, right after Models", () => {
    render(
      <SettingsLayout>
        <div />
      </SettingsLayout>,
    );
    const nav = screen.getByRole("navigation", { name: "Settings sections" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((a) => a.textContent)).toEqual([
      "Models",
      "Agents",
      "Connections",
      "Search Providers",
      "Research",
      "Projects",
      "Appearance",
      "Advanced",
      "About",
    ]);
    expect(within(nav).getByRole("link", { name: "Agents" })).toHaveAttribute(
      "href",
      "/settings/agents",
    );
    expect(within(nav).getByRole("link", { name: "Models" })).toHaveAttribute(
      "href",
      "/settings/models",
    );
  });

  it("builds the Agents page in the static export", () => {
    const sections = generateStaticParams().map((p) => p.section);
    expect(sections).toContain("agents");
    expect(sections).toContain("models");
  });
});

describe("each section renders its own page", () => {
  it("Agents renders the agents page and nothing of Models", () => {
    render(<SectionContent section="agents" />);
    expect(screen.getByText("agents page")).toBeInTheDocument();
    expect(screen.queryByText("model picker")).not.toBeInTheDocument();
  });

  it("Models renders model configuration and nothing of Agents", () => {
    render(<SectionContent section="models" />);
    expect(screen.getByText("custom endpoint")).toBeInTheDocument();
    expect(screen.getByText("local models")).toBeInTheDocument();
    expect(screen.getByText("model picker")).toBeInTheDocument();
    expect(screen.queryByText("agents page")).not.toBeInTheDocument();
  });
});
