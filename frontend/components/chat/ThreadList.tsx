"use client";

import toast from "react-hot-toast";

import { RelativeTime } from "@/components/RelativeTime";
import { useCreateThread, useDeleteThread, useThreads } from "@/hooks/queries";
import type { ChatThread } from "@/lib/types";

/**
 * The project's conversations (docs/14 §3).
 *
 * Threads are parallel and independent so one project can hold several lines of enquiry
 * without them contaminating each other's history. Titles come from the first message
 * rather than a naming prompt — asking someone to name a conversation before having it
 * is a chore, and a model call to summarise it would be spend for cosmetics.
 */
export function ThreadList({
  projectId,
  activeThreadId,
  onSelect,
}: {
  projectId: string | undefined;
  activeThreadId: string | null;
  onSelect: (thread: ChatThread | null) => void;
}) {
  const { data, isLoading } = useThreads(projectId);
  const createThread = useCreateThread(projectId);
  const deleteThread = useDeleteThread(projectId);

  const threads = data?.threads ?? [];

  const create = async () => {
    try {
      const thread = await createThread.mutateAsync({});
      onSelect(thread);
    } catch {
      toast.error("Couldn't start a new chat.");
    }
  };

  const remove = async (thread: ChatThread) => {
    if (!window.confirm(`Delete "${thread.title}"? The conversation cannot be recovered.`)) {
      return;
    }
    try {
      await deleteThread.mutateAsync(thread.id);
      if (activeThreadId === thread.id) onSelect(null);
    } catch {
      toast.error("Couldn't delete that chat.");
    }
  };

  return (
    <div className="card flex h-full flex-col border border-border bg-bg-surface p-0 shadow-sm">
      <div className="flex items-center justify-between border-b border-border bg-bg-elevated/40 px-3.5 py-2.5">
        <div className="flex items-center gap-1.5">
          <h3 className="font-serif text-sm font-bold text-text-primary">Project Threads</h3>
          {threads.length > 0 && (
            <span className="border border-border bg-bg-surface px-1.5 py-0.2 font-mono text-[length:var(--text-micro)] font-semibold text-text-muted">
              {threads.length}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={() => void create()}
          disabled={!projectId || createThread.isPending}
          className="btn btn-secondary px-2.5 py-1 font-mono text-xs font-semibold"
        >
          {createThread.isPending ? "Creating…" : "+ New"}
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {isLoading && <p className="px-2 py-3 font-mono text-xs text-text-muted">Loading…</p>}
        {!isLoading && threads.length === 0 && (
          <div className="px-3 py-6 text-center">
            <p className="text-xs font-medium text-text-secondary">No chats started yet</p>
            <p className="mt-1 text-[length:var(--text-micro)] text-text-muted">
              Click &ldquo;+ New&rdquo; to start asking questions across approved reports.
            </p>
          </div>
        )}
        <ul className="space-y-1">
          {threads.map((thread) => {
            const isActive = thread.id === activeThreadId;
            return (
              <li key={thread.id}>
                <div
                  className={`group flex items-center gap-1.5 border px-2.5 py-2 transition-all ${
                    isActive
                      ? "border-accent bg-accent-muted font-medium shadow-xs"
                      : "border-transparent hover:border-border hover:bg-bg-elevated/80"
                  }`}
                  style={{
                    borderLeftWidth: isActive ? "3px" : "1px",
                    borderLeftColor: isActive ? "var(--accent)" : "transparent",
                  }}
                >
                  <button
                    type="button"
                    onClick={() => onSelect(thread)}
                    aria-current={isActive ? "true" : undefined}
                    className="min-w-0 flex-1 text-left"
                  >
                    <span className="block truncate text-xs font-medium text-text-primary group-hover:text-accent">
                      {thread.title}
                    </span>
                    <span className="mt-0.5 block font-mono text-[length:var(--text-micro)] text-text-muted">
                      <RelativeTime iso={thread.last_message_at} />
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => void remove(thread)}
                    aria-label={`Delete ${thread.title}`}
                    className="shrink-0 p-1 font-mono text-xs text-text-muted opacity-0 transition-opacity hover:text-danger focus:opacity-100 group-hover:opacity-100"
                  >
                    ×
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
