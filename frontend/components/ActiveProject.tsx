"use client";

import { createContext, useCallback, useContext, useMemo, useSyncExternalStore } from "react";

import { useProjects } from "@/hooks/queries";
import type { Project } from "@/lib/types";

/**
 * Which project the app is currently looking at (docs/14 §3).
 *
 * Held in context rather than the URL because every scoped surface (dashboard,
 * history, and later chat) needs it and they navigate between each other freely —
 * threading a query param through all of them would be noise. The choice is
 * remembered in localStorage so a reload keeps you where you were; it is a UI
 * preference, not an authorization input (the server re-checks ownership on every
 * request), so storing it client-side is safe.
 */

const STORAGE_KEY = "active_project_id";

/**
 * localStorage as an external store, read through useSyncExternalStore rather than
 * copied into state by an effect. That keeps the render pure (no setState-in-effect),
 * gives a correct SSR snapshot, and syncs across tabs for free via the storage event.
 */
const listeners = new Set<() => void>();

function subscribeToStoredId(onChange: () => void) {
  listeners.add(onChange);
  window.addEventListener("storage", onChange);
  return () => {
    listeners.delete(onChange);
    window.removeEventListener("storage", onChange);
  };
}

function getStoredId(): string | null {
  // Not an auth input: the server re-checks project ownership on every request, so a
  // tampered value yields 404s, never access. The inline marker is what the CI web-storage
  // guard reads — it bans auth in web storage, not every client-side preference.
  return window.localStorage.getItem(STORAGE_KEY); // ci-allow-web-storage: UI preference
}

// The server has no localStorage; null means "no remembered choice yet".
function getStoredIdOnServer(): string | null {
  return null;
}

function writeStoredId(id: string) {
  window.localStorage.setItem(STORAGE_KEY, id); // ci-allow-web-storage: UI preference
  // `storage` only fires in *other* tabs, so notify this one explicitly.
  listeners.forEach((l) => l());
}

interface ActiveProjectValue {
  projects: Project[];
  /** undefined while loading — callers use that to hold off on scoped fetches. */
  activeId: string | undefined;
  active: Project | undefined;
  setActiveId: (id: string) => void;
  isLoading: boolean;
}

const Ctx = createContext<ActiveProjectValue | null>(null);

export function ActiveProjectProvider({ children }: { children: React.ReactNode }) {
  const { data, isLoading } = useProjects();
  const projects = useMemo(() => data?.projects ?? [], [data]);
  const storedId = useSyncExternalStore(
    subscribeToStoredId,
    getStoredId,
    getStoredIdOnServer
  );

  const setActiveId = useCallback((id: string) => writeStoredId(id), []);

  // A remembered id that no longer exists (deleted project, different account) must
  // fall back rather than leave the app scoped to nothing.
  const activeId = useMemo(() => {
    if (isLoading) return undefined;
    if (storedId && projects.some((p) => p.id === storedId)) return storedId;
    return projects[0]?.id;
  }, [isLoading, storedId, projects]);

  const value = useMemo<ActiveProjectValue>(
    () => ({
      projects,
      activeId,
      active: projects.find((p) => p.id === activeId),
      setActiveId,
      isLoading,
    }),
    [projects, activeId, setActiveId, isLoading]
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useActiveProject(): ActiveProjectValue {
  const ctx = useContext(Ctx);
  if (!ctx) {
    throw new Error("useActiveProject must be used inside <ActiveProjectProvider>");
  }
  return ctx;
}
