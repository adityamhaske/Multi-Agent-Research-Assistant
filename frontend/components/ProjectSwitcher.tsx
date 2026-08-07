"use client";

import { useState } from "react";
import toast from "react-hot-toast";

import { useCreateProject } from "@/hooks/queries";
import { ApiError } from "@/lib/api";

import { useActiveProject } from "./ActiveProject";

/**
 * Switch the active project, or make a new one (docs/14 §3).
 *
 * A plain <select> plus an inline "New" form rather than a custom dropdown: it is
 * keyboard- and screen-reader-correct for free, and this control is navigation
 * furniture that should never be the most interesting thing on the page.
 */
export function ProjectSwitcher() {
  const { projects, activeId, setActiveId, isLoading } = useActiveProject();
  const create = useCreateProject();
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    try {
      const project = await create.mutateAsync({ name: trimmed });
      setActiveId(project.id); // land the user in what they just made
      setName("");
      setCreating(false);
      toast.success(`Project "${project.name}" created`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't create that project.");
    }
  };

  if (isLoading) {
    return <div className="h-8 w-40 animate-pulse rounded-md bg-bg-elevated" aria-hidden />;
  }

  if (creating) {
    return (
      <form onSubmit={submit} className="flex items-center gap-1.5">
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value.slice(0, 120))}
          placeholder="Project name"
          aria-label="New project name"
          className="input h-8 w-44 text-sm"
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              setCreating(false);
              setName("");
            }
          }}
        />
        <button
          type="submit"
          disabled={create.isPending}
          className="btn btn-primary h-8 px-2.5 text-xs"
        >
          {create.isPending ? "…" : "Create"}
        </button>
        <button
          type="button"
          onClick={() => {
            setCreating(false);
            setName("");
          }}
          className="px-1.5 text-xs text-text-muted hover:text-text-secondary"
        >
          Cancel
        </button>
      </form>
    );
  }

  return (
    <div className="flex items-center gap-1.5">
      <label htmlFor="project-switcher" className="sr-only">
        Active project
      </label>
      <select
        id="project-switcher"
        value={activeId ?? ""}
        onChange={(e) => setActiveId(e.target.value)}
        className="input h-8 max-w-[12rem] text-sm"
      >
        {projects.length === 0 && <option value="">No projects yet</option>}
        {projects.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
            {p.session_count ? ` (${p.session_count})` : ""}
          </option>
        ))}
      </select>
      <button
        type="button"
        onClick={() => setCreating(true)}
        className="rounded-md px-1.5 py-1 text-sm text-text-muted hover:text-text-secondary"
        title="New project"
        aria-label="New project"
      >
        +
      </button>
    </div>
  );
}
