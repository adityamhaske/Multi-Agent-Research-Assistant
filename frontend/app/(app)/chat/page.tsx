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
    <div className="grid gap-5 lg:grid-cols-[18rem_1fr]">
      <div className="h-[34rem] lg:h-auto">
        <ThreadList
          projectId={projectId}
          activeThreadId={thread?.id ?? null}
          onSelect={setThread}
        />
      </div>
      {thread ? (
        <ProjectChatPanel key={thread.id} threadId={thread.id} />
      ) : (
        <div className="card flex min-h-[34rem] flex-col items-center justify-center border border-border bg-bg-surface p-8 text-center shadow-sm">
          <div className="mx-auto max-w-sm space-y-2">
            <div className="mx-auto flex h-10 w-10 items-center justify-center border border-border bg-bg-elevated font-serif font-bold text-accent">
              💬
            </div>
            <h3 className="font-serif text-base font-bold text-text-primary">
              Select or Start a Chat
            </h3>
            <p className="text-xs leading-relaxed text-text-muted">
              Pick a conversation from the sidebar or start a new one. Answers cite the approved research reports in this project so every statement remains verifiable.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Project chat (docs/14 §5) — the surface project memory exists for.
 *
 * Scoped by the active project from context rather than a route param, matching the
 * research page and history: every surface under the switcher is project-scoped, and
 * threading the id through the URL as well would be two sources of truth for one choice.
 */
export default function ChatPage() {
  const { activeId, active, isLoading } = useActiveProject();

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="card h-28 animate-pulse border border-border" aria-hidden />
        <div className="card h-96 animate-pulse border border-border" aria-hidden />
        <span className="sr-only">Loading chat…</span>
      </div>
    );
  }

  if (!activeId) {
    return (
      <div className="card border border-border bg-bg-surface p-8 text-center shadow-sm">
        <p className="text-sm font-medium text-text-secondary">
          Create a project first — chat answers from the research approved inside one.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <section aria-labelledby="chat-heading">
        <h1 id="chat-heading" className="mb-1 font-serif text-2xl font-bold tracking-tight text-text-primary">
          {active?.name ?? "Project"} Chat
        </h1>
        <p className="max-w-2xl text-sm leading-relaxed text-text-muted">
          Ask questions grounded in the research reports approved in this project.
        </p>
      </section>

      <MemoryStatusCard projectId={activeId} />

      <ProjectThreads key={activeId} projectId={activeId} />
    </div>
  );
}
