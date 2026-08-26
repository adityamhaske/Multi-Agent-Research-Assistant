"use client";

import { useState } from "react";
import toast from "react-hot-toast";

import { Field, Section } from "@/components/account/Section";
import {
  useCreateProject,
  useDeleteProject,
  useProjects,
  useUpdateProject,
} from "@/hooks/queries";
import { ApiError } from "@/lib/api";
import type { Project } from "@/lib/types";

/**
 * Project management (docs/14 §8). Rename, archive, and delete already existed as API
 * routes and mutation hooks (`hooks/queries.ts`) with zero UI callers — this is the
 * settings surface for them.
 *
 * Archive is reversible and just hides a project from the active list; delete is
 * destructive and removes the project's sessions, reports, memory, chat threads, and
 * corpus. The server refuses delete while any session is still running rather than
 * pulling the row out from under an in-flight worker — the confirm copy below states
 * that up front rather than letting the user discover it as a 409.
 */

function RenameRow({ project }: { project: Project }) {
  const updateProject = useUpdateProject();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(project.name);

  const save = async () => {
    const trimmed = name.trim();
    if (!trimmed || trimmed === project.name) {
      setEditing(false);
      setName(project.name);
      return;
    }
    try {
      await updateProject.mutateAsync({ id: project.id, name: trimmed });
      toast.success("Project renamed.");
      setEditing(false);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not rename the project.");
      setName(project.name);
    }
  };

  if (!editing) {
    return (
      <button
        type="button"
        onClick={() => setEditing(true)}
        className="truncate text-left text-sm font-medium text-text-primary hover:underline"
        title="Rename"
      >
        {project.name}
      </button>
    );
  }

  return (
    <input
      autoFocus
      value={name}
      onChange={(e) => setName(e.target.value)}
      onBlur={save}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
        if (e.key === "Escape") {
          setName(project.name);
          setEditing(false);
        }
      }}
      disabled={updateProject.isPending}
      className="input-base w-full max-w-xs text-sm"
    />
  );
}

function ProjectRow({ project, archived }: { project: Project; archived: boolean }) {
  const updateProject = useUpdateProject();
  const deleteProject = useDeleteProject();

  const toggleArchive = async () => {
    try {
      await updateProject.mutateAsync({ id: project.id, archived: !archived });
      toast.success(archived ? "Project restored." : "Project archived.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not update the project.");
    }
  };

  const remove = async () => {
    const warning =
      `Delete "${project.name}"? This permanently removes ${project.session_count} ` +
      `session${project.session_count === 1 ? "" : "s"} and every report, memory chunk, ` +
      `chat thread, and uploaded corpus document in it. This cannot be undone.`;
    if (!window.confirm(warning)) return;
    try {
      await deleteProject.mutateAsync(project.id);
      toast.success("Project deleted.");
    } catch (err) {
      // The server refuses delete with 409 while a session is still RUNNING — surfacing
      // its message rather than a generic one is what tells the user why to wait.
      toast.error(err instanceof ApiError ? err.message : "Could not delete the project.");
    }
  };

  return (
    <div className="flex items-center justify-between gap-4 border-b border-border py-3 last:border-b-0">
      <div className="min-w-0 flex-1">
        <RenameRow project={project} />
        <div className="mt-0.5 font-mono text-[0.6875rem] text-text-muted">
          {project.session_count} session{project.session_count === 1 ? "" : "s"} ·
          created {new Date(project.created_at).toLocaleDateString()}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <button
          type="button"
          onClick={toggleArchive}
          disabled={updateProject.isPending}
          className="btn btn-ghost text-xs"
        >
          {archived ? "Restore" : "Archive"}
        </button>
        <button
          type="button"
          onClick={remove}
          disabled={deleteProject.isPending}
          className="btn btn-ghost text-xs"
          style={{ color: "var(--danger)" }}
        >
          Delete
        </button>
      </div>
    </div>
  );
}

function CreateProjectForm() {
  const createProject = useCreateProject();
  const [name, setName] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    try {
      await createProject.mutateAsync({ name: trimmed });
      setName("");
      toast.success("Project created.");
    } catch (err) {
      // A case-insensitive duplicate name surfaces as 409 (projects.py) — worth its own
      // message rather than a generic failure, since the fix is just "pick another name".
      toast.error(err instanceof ApiError ? err.message : "Could not create the project.");
    }
  };

  return (
    <form onSubmit={submit} className="flex items-end gap-3">
      <Field label="New project" htmlFor="new-project-name" className="flex-1">
        <input
          id="new-project-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Project name"
          className="input-base w-full max-w-sm text-sm"
        />
      </Field>
      <button type="submit" disabled={!name.trim() || createProject.isPending} className="btn btn-primary">
        {createProject.isPending && <span className="spinner" />}
        Create
      </button>
    </form>
  );
}

export function ProjectsSection() {
  const [showArchived, setShowArchived] = useState(false);
  const { data: active, isLoading: activeLoading } = useProjects(false);
  const { data: archived, isLoading: archivedLoading } = useProjects(true);

  const archivedCount = archived?.projects.length ?? 0;

  return (
    <>
      <Section
        title="Projects"
        description="Every project has its own sessions, reports, chat memory, and corpus. Create as many as you need — research in one never mixes with another."
      >
        <div className="mb-5">
          <CreateProjectForm />
        </div>
        {activeLoading ? (
          <div className="h-24 animate-pulse" aria-hidden />
        ) : !active?.projects.length ? (
          <p className="text-sm text-text-muted">No active projects yet.</p>
        ) : (
          <div>
            {active.projects.map((p) => (
              <ProjectRow key={p.id} project={p} archived={false} />
            ))}
          </div>
        )}
      </Section>

      <Section
        title="Archived projects"
        description="Archiving hides a project from the switcher without deleting anything. Restore it any time."
      >
        <button
          type="button"
          onClick={() => setShowArchived((v) => !v)}
          className="mb-3 font-mono text-xs text-accent hover:underline"
        >
          {showArchived ? "Hide" : `Show (${archivedCount})`}
        </button>
        {showArchived &&
          (archivedLoading ? (
            <div className="h-16 animate-pulse" aria-hidden />
          ) : !archivedCount ? (
            <p className="text-sm text-text-muted">No archived projects.</p>
          ) : (
            <div>
              {archived!.projects.map((p) => (
                <ProjectRow key={p.id} project={p} archived={true} />
              ))}
            </div>
          ))}
      </Section>
    </>
  );
}
