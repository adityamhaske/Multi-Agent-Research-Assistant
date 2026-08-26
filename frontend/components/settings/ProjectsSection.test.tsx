import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Project } from "@/lib/types";

import { ProjectsSection } from "./ProjectsSection";

/**
 * Project management (docs/14 §8). `useUpdateProject`/`useDeleteProject` existed with
 * zero UI callers before this component — the behaviour under test is the wiring itself:
 * archive and delete call the mutation with the shape the hook actually expects
 * (`{id, ...body}`, not `{id, body}`), delete confirms before firing, and archived
 * projects only render once the section is expanded.
 */

const activeProjects = vi.hoisted(() => ({
  value: [] as Project[],
}));
const archivedProjects = vi.hoisted(() => ({
  value: [] as Project[],
}));
const updateProject = vi.hoisted(() => ({ mutateAsync: vi.fn(), isPending: false }));
const deleteProject = vi.hoisted(() => ({ mutateAsync: vi.fn(), isPending: false }));
const createProject = vi.hoisted(() => ({ mutateAsync: vi.fn(), isPending: false }));

vi.mock("@/hooks/queries", () => ({
  useProjects: (archived: boolean) => ({
    data: { projects: archived ? archivedProjects.value : activeProjects.value, total: 0 },
    isLoading: false,
  }),
  useCreateProject: () => createProject,
  useUpdateProject: () => updateProject,
  useDeleteProject: () => deleteProject,
}));

const PROJECT: Project = {
  id: "p1",
  name: "Thesis",
  description: null,
  archived_at: null,
  created_at: "2026-01-01T00:00:00Z",
  session_count: 3,
};

function setUp(active: Project[] = [PROJECT], archived: Project[] = []) {
  activeProjects.value = active;
  archivedProjects.value = archived;
  updateProject.mutateAsync.mockReset().mockResolvedValue(PROJECT);
  deleteProject.mutateAsync.mockReset().mockResolvedValue(undefined);
  createProject.mutateAsync.mockReset().mockResolvedValue(PROJECT);
  return render(<ProjectsSection />);
}

describe("active projects", () => {
  it("lists a project with its session count", () => {
    setUp();
    expect(screen.getByText("Thesis")).toBeInTheDocument();
    expect(screen.getByText(/3 sessions/)).toBeInTheDocument();
  });

  it("shows an empty state with no active projects", () => {
    setUp([]);
    expect(screen.getByText("No active projects yet.")).toBeInTheDocument();
  });

  it("archives a project with the flat mutation shape the hook expects", async () => {
    setUp();
    await userEvent.click(screen.getByRole("button", { name: "Archive" }));
    expect(updateProject.mutateAsync).toHaveBeenCalledWith({ id: "p1", archived: true });
  });

  it("deletes only after the user confirms, naming what will be lost", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    setUp();
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(confirmSpy).toHaveBeenCalledWith(expect.stringContaining("3 sessions"));
    expect(deleteProject.mutateAsync).not.toHaveBeenCalled();

    confirmSpy.mockReturnValue(true);
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(deleteProject.mutateAsync).toHaveBeenCalledWith("p1");
    confirmSpy.mockRestore();
  });
});

describe("archived projects", () => {
  const archivedProject: Project = {
    ...PROJECT,
    id: "p2",
    name: "Old Draft",
    archived_at: "2026-02-01T00:00:00Z",
  };

  it("stays collapsed until the user asks to see them", () => {
    setUp([PROJECT], [archivedProject]);
    expect(screen.queryByText(archivedProject.name)).not.toBeInTheDocument();
    expect(screen.getByText("Show (1)")).toBeInTheDocument();
  });

  it("restores an archived project with the flat mutation shape", async () => {
    setUp([PROJECT], [archivedProject]);
    await userEvent.click(screen.getByText("Show (1)"));
    await userEvent.click(screen.getByRole("button", { name: "Restore" }));
    expect(updateProject.mutateAsync).toHaveBeenCalledWith({ id: "p2", archived: false });
  });
});
