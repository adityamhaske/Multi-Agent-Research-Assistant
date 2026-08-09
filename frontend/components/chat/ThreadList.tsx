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
    <div className="card flex h-full flex-col p-0">
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <h3 className="text-sm font-semibold text-text-primary">Chats</h3>
        <button
          type="button"
          onClick={() => void create()}
          disabled={!projectId || createThread.isPending}
          className="btn btn-secondary px-2 py-1 text-xs"
        >
          New
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {isLoading && <p className="px-2 py-3 text-sm text-text-muted">Loading…</p>}
        {!isLoading && threads.length === 0 && (
          <p className="px-2 py-3 text-sm text-text-muted">
            No chats yet. Start one to ask questions across everything approved in this
            project.
          </p>
        )}
        <ul className="space-y-1">
          {threads.map((thread) => (
            <li key={thread.id}>
              <div
                className={`group flex items-center gap-1 rounded-lg px-2 py-1.5 transition-colors ${
                  thread.id === activeThreadId ? "bg-accent-muted" : "hover:bg-bg-elevated"
                }`}
              >
                <button
                  type="button"
                  onClick={() => onSelect(thread)}
                  aria-current={thread.id === activeThreadId ? "true" : undefined}
                  className="min-w-0 flex-1 text-left"
                >
                  <span className="block truncate text-sm text-text-primary">
                    {thread.title}
                  </span>
                  <span className="block text-xs text-text-muted">
                    <RelativeTime iso={thread.last_message_at} />
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => void remove(thread)}
                  aria-label={`Delete ${thread.title}`}
                  className="shrink-0 rounded p-1 text-text-muted opacity-0 transition-opacity hover:text-danger focus:opacity-100 group-hover:opacity-100"
                >
                  ×
                </button>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
