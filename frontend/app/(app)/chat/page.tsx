"use client";

import { useState } from "react";

import { useActiveProject } from "@/components/ActiveProject";
import { MemoryStatusCard } from "@/components/chat/MemoryStatusCard";
import { ProjectChatPanel } from "@/components/chat/ProjectChatPanel";
import { ThreadList } from "@/components/chat/ThreadList";
import type { ChatThread } from "@/lib/types";

/**
 * Thread selection for one project.
 *
 * Split out and mounted with `key={projectId}` so switching projects remounts it and the
 * selected thread resets by construction. The alternative — clearing it from an effect —
 * is the setState-in-effect pattern this codebase avoids everywhere (see ActiveProject,
 * which reaches for useSyncExternalStore for the same reason).
 */
function ProjectThreads({ projectId }: { projectId: string }) {
  const [thread, setThread] = useState<ChatThread | null>(null);

  return (
    <div className="grid gap-4 lg:grid-cols-[16rem_1fr]">
      <div className="h-[32rem] lg:h-auto">
        <ThreadList
          projectId={projectId}
          activeThreadId={thread?.id ?? null}
          onSelect={setThread}
        />
      </div>
      {thread ? (
        <ProjectChatPanel key={thread.id} threadId={thread.id} />
      ) : (
        <div className="card flex min-h-[32rem] items-center justify-center text-center">
          <p className="max-w-sm text-sm text-text-muted">
            Pick a chat, or start a new one. Answers cite the approved reports they came
            from, so you can check every claim against the research behind it.
          </p>
        </div>
      )}
    </div>
  );
}

/**
 * Project chat (docs/14 §5) — the surface project memory exists for.
 *
 * Scoped by the active project from context rather than a route param, matching the
 * dashboard and history: every surface under the switcher is project-scoped, and
 * threading the id through the URL as well would be two sources of truth for one choice.
 */
export default function ChatPage() {
  const { activeId, active, isLoading } = useActiveProject();

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="card h-24 animate-pulse" aria-hidden />
        <div className="card h-96 animate-pulse" aria-hidden />
        <span className="sr-only">Loading chat…</span>
      </div>
    );
  }

  if (!activeId) {
    return (
      <div className="card text-center">
        <p className="text-sm text-text-secondary">
          Create a project first — chat answers from the research approved inside one.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">
          {active?.name ?? "Project"} chat
        </h1>
        <p className="mt-0.5 text-sm text-text-muted">
          Grounded in every report you approved in this project.
        </p>
      </div>

      <MemoryStatusCard projectId={activeId} />

      <ProjectThreads key={activeId} projectId={activeId} />
    </div>
  );
}
