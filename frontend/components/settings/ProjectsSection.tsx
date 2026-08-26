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
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setEditing(true)}
          className="truncate text-left text-sm font-semibold text-text-primary hover:text-accent transition-colors hover:underline"
          title="Click to rename"
        >
          {project.name}
        </button>
        <button
          type="button"
          onClick={() => setEditing(true)}
          className="text-text-muted hover:text-text-secondary opacity-60 hover:opacity-100 p-0.5"
          title="Rename project"
          aria-label="Rename project"
        >
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
          </svg>
        </button>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
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
        className="input-base w-full max-w-xs text-sm py-1 px-2.5 font-medium"
      />
      <span className="text-[0.6875rem] font-mono text-text-muted">Enter to save · Esc to cancel</span>
    </div>
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
      toast.error(err instanceof ApiError ? err.message : "Could not delete the project.");
    }
  };

  return (
    <div className="flex items-center justify-between gap-4 border border-border/70 bg-bg-surface/80 p-3.5 transition-all hover:border-border hover:bg-bg-elevated/30">
      <div className="flex items-center gap-3.5 min-w-0 flex-1">
        <div className="p-2.5 border border-border/60 bg-bg-base/60 text-text-muted shrink-0">
          <svg className="w-4 h-4 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
          </svg>
        </div>
        <div className="min-w-0 flex-1">
          <RenameRow project={project} />
          <div className="mt-1 flex items-center gap-2 font-mono text-[0.6875rem] text-text-muted">
            <span className="bg-bg-elevated px-1.5 py-0.5 border border-border/50 font-medium text-text-secondary">
              {project.session_count} session{project.session_count === 1 ? "" : "s"}
            </span>
            <span>·</span>
            <span>created {new Date(project.created_at).toLocaleDateString()}</span>
          </div>
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-1.5">
        <button
          type="button"
          onClick={toggleArchive}
          disabled={updateProject.isPending}
          className="btn btn-ghost text-xs px-2.5 py-1.5 hover:bg-bg-elevated"
        >
          {archived ? "Restore" : "Archive"}
        </button>
        <button
          type="button"
          onClick={remove}
          disabled={deleteProject.isPending}
          className="btn btn-ghost text-xs px-2.5 py-1.5 hover:bg-danger/10"
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
      toast.error(err instanceof ApiError ? err.message : "Could not create the project.");
    }
  };

  return (
    <form onSubmit={submit} className="flex flex-col sm:flex-row sm:items-end gap-3 border border-border/80 bg-bg-surface/90 p-4 shadow-xs">
      <Field label="New project" htmlFor="new-project-name" className="flex-1" hint="Isolated workspace with private memory and documents.">
        <input
          id="new-project-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Market Research Q3, Neuroscience Study"
          className="input-base w-full text-sm"
        />
      </Field>
      <button type="submit" disabled={!name.trim() || createProject.isPending} className="btn btn-primary h-10 px-4">
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
    <div className="space-y-6">
      <Section
        title="Projects"
        description="Every project has its own sessions, reports, chat memory, and corpus. Create as many as you need — research in one never mixes with another."
      >
        <div className="mb-6">
          <CreateProjectForm />
        </div>
        {activeLoading ? (
          <div className="h-24 animate-pulse bg-bg-elevated/40" aria-hidden />
        ) : !active?.projects.length ? (
          <div className="border border-border/70 bg-bg-surface/50 p-6 text-center text-sm text-text-muted">
            No active projects yet.
          </div>
        ) : (
          <div className="space-y-2.5">
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
          className="mb-4 inline-flex items-center gap-1.5 font-mono text-xs font-semibold text-accent hover:underline"
        >
          <span>{showArchived ? "Hide" : `Show (${archivedCount})`}</span>
          <svg className={`w-3.5 h-3.5 transition-transform ${showArchived ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>
        {showArchived &&
          (archivedLoading ? (
            <div className="h-16 animate-pulse bg-bg-elevated/40" aria-hidden />
          ) : !archivedCount ? (
            <p className="text-sm text-text-muted">No archived projects.</p>
          ) : (
            <div className="space-y-2.5">
              {archived!.projects.map((p) => (
                <ProjectRow key={p.id} project={p} archived={true} />
              ))}
            </div>
          ))}
      </Section>
    </div>
  );
}
