"use client";

import { useEffect, useRef, useState } from "react";
import toast from "react-hot-toast";

import { useCreateProject } from "@/hooks/queries";
import { ApiError } from "@/lib/api";

import { useActiveProject } from "./ActiveProject";

/**
 * Modern custom ProjectSwitcher dropdown for the sidebar.
 *
 * Supports expanded and collapsed modes, popping up smoothly without
 * relying on native unstyled <select> elements.
 */
export function ProjectSwitcher({ collapsed = false }: { collapsed?: boolean }) {
  const { projects, activeId, setActiveId, isLoading } = useActiveProject();
  const create = useCreateProject();
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");

  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const activeProject = projects.find((p) => p.id === activeId) ?? projects[0];

  // Close on click outside or Escape
  useEffect(() => {
    if (!open) return;

    const onPointerDown = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) {
        setOpen(false);
        setCreating(false);
      }
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (creating) {
          setCreating(false);
        } else {
          setOpen(false);
          triggerRef.current?.focus();
        }
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open, creating]);

  // Focus input when creating begins
  useEffect(() => {
    if (creating) {
      inputRef.current?.focus();
    }
  }, [creating]);

  const submitCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    try {
      const project = await create.mutateAsync({ name: trimmed });
      setActiveId(project.id);
      setName("");
      setCreating(false);
      setOpen(false);
      toast.success(`Project "${project.name}" created`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't create that project.");
    }
  };

  if (isLoading) {
    return (
      <div
        className={`h-9 animate-pulse border border-border bg-bg-elevated ${
          collapsed ? "w-9 mx-auto" : "w-full"
        }`}
        aria-hidden
      />
    );
  }

  return (
    <div ref={rootRef} className="relative w-full">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        title={collapsed ? `Project: ${activeProject?.name ?? "None"}` : undefined}
        className={`group flex w-full items-center border border-border bg-bg-surface text-text-primary transition-all duration-150 hover:border-border hover:bg-bg-elevated ${
          collapsed
            ? "h-9 w-9 justify-center mx-auto p-0"
            : "h-9 justify-between px-2.5 text-left text-xs"
        } ${open ? "border-accent ring-1 ring-accent" : ""}`}
      >
        {collapsed ? (
          <div className="flex h-6 w-6 items-center justify-center border border-border bg-accent-muted text-accent font-mono font-semibold text-[0.6875rem]">
            {activeProject ? activeProject.name.charAt(0).toUpperCase() : "P"}
          </div>
        ) : (
          <>
            <div className="flex min-w-0 items-center gap-2">
              <svg
                aria-hidden
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.75"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="h-4 w-4 shrink-0 text-accent"
              >
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
              </svg>
              <span className="truncate font-medium">
                {activeProject ? activeProject.name : "Select Project"}
              </span>
            </div>
            <svg
              aria-hidden
              viewBox="0 0 20 20"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
              className={`h-3.5 w-3.5 shrink-0 text-text-muted transition-transform duration-200 group-hover:text-text-primary ${
                open ? "rotate-180 text-text-primary" : ""
              }`}
            >
              <path d="m6 8 4 4 4-4" />
            </svg>
          </>
        )}
      </button>

      {open && (
        <div
          role="listbox"
          aria-label="Projects"
          className={`menu-surface animate-fade-in absolute z-50 w-64 ${
            collapsed
              ? "left-full bottom-0 ml-3 origin-bottom-left"
              : "bottom-full left-0 mb-2 origin-bottom-left"
          }`}
        >
          <div className="flex items-center justify-between px-3 py-2 border-b border-border">
            <span className="font-mono text-[0.6875rem] font-semibold uppercase tracking-wider text-text-muted">
              Projects ({projects.length})
            </span>
            {!creating && (
              <button
                type="button"
                onClick={() => setCreating(true)}
                className="font-mono text-[0.75rem] font-medium text-accent hover:underline flex items-center gap-1"
              >
                <span>+ New</span>
              </button>
            )}
          </div>

          {/* Project List */}
          <div className="max-h-48 overflow-y-auto py-1">
            {projects.length === 0 ? (
              <div className="px-3 py-2 text-xs text-text-muted text-center">
                No projects created yet
              </div>
            ) : (
              projects.map((p) => {
                const isSelected = p.id === activeId;
                return (
                  <button
                    key={p.id}
                    type="button"
                    role="option"
                    aria-selected={isSelected}
                    onClick={() => {
                      setActiveId(p.id);
                      setOpen(false);
                    }}
                    className={`flex w-full items-center justify-between px-2.5 py-1.5 text-xs text-left transition-colors ${
                      isSelected
                        ? "bg-accent-muted font-semibold text-accent"
                        : "text-text-secondary hover:bg-bg-elevated hover:text-text-primary"
                    }`}
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <svg
                        aria-hidden
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.75"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        className={`h-3.5 w-3.5 shrink-0 ${isSelected ? "text-accent" : "text-text-muted"}`}
                      >
                        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
                      </svg>
                      <span className="truncate">{p.name}</span>
                    </div>

                    <div className="flex items-center gap-1.5 shrink-0 ml-2">
                      {Boolean(p.session_count) && (
                        <span className="border border-border bg-bg-elevated px-1.5 py-0.2 font-mono text-[0.625rem] text-text-muted font-normal">
                          {p.session_count}
                        </span>
                      )}
                      {isSelected && (
                        <svg
                          aria-hidden
                          viewBox="0 0 20 20"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          className="h-3.5 w-3.5 text-accent"
                        >
                          <path d="m4 10 4 4 8-8" />
                        </svg>
                      )}
                    </div>
                  </button>
                );
              })
            )}
          </div>

          {/* New Project Form */}
          {creating ? (
            <form onSubmit={submitCreate} className="p-2 border-t border-border/70 bg-bg-elevated/30">
              <input
                ref={inputRef}
                value={name}
                onChange={(e) => setName(e.target.value.slice(0, 120))}
                placeholder="Project name..."
                className="input-base h-7 w-full text-xs mb-2 py-1 px-2"
              />
              <div className="flex items-center justify-end gap-1.5">
                <button
                  type="button"
                  onClick={() => {
                    setCreating(false);
                    setName("");
                  }}
                  className="px-2 py-1 text-[0.6875rem] text-text-muted hover:text-text-secondary"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={create.isPending || !name.trim()}
                  className="btn btn-primary h-7 px-2 text-[0.6875rem]"
                >
                  {create.isPending ? "Creating…" : "Create"}
                </button>
              </div>
            </form>
          ) : (
            <div className="p-1 border-t border-border/70">
              <button
                type="button"
                onClick={() => setCreating(true)}
                className="flex w-full items-center gap-2 px-2.5 py-1.5 font-mono text-xs text-text-muted hover:bg-bg-elevated hover:text-text-primary transition-colors"
              >
                <svg
                  aria-hidden
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.75"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="h-3.5 w-3.5"
                >
                  <line x1="12" y1="5" x2="12" y2="19" />
                  <line x1="5" y1="12" x2="19" y2="12" />
                </svg>
                <span>Create new project</span>
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
