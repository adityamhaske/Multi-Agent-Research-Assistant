"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import toast from "react-hot-toast";

import { queryKeys, useChatHistory } from "@/hooks/queries";
import { Report } from "@/lib/citations";
import { apiBase, authHeaders, isDesktop } from "@/lib/desktop";
import { streamSSE } from "@/lib/sse";
import type { Source } from "@/lib/types";

interface Streaming {
  user: string;
  assistant: string;
}

function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] whitespace-pre-wrap border border-accent bg-accent-muted px-3.5 py-2 text-sm text-text-primary">
        {text}
      </div>
    </div>
  );
}

function AssistantBubble({ text, sources }: { text: string; sources: Source[] }) {
  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] border border-border bg-bg-surface px-3.5 py-2 text-sm">
        {text ? (
          <Report markdown={text} sources={sources} />
        ) : (
          <span className="inline-flex gap-1.5 py-1" aria-label="Assistant is typing">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="h-1.5 w-1.5 bg-accent"
                style={{ animation: `pulse 1s ease-in-out ${i * 0.15}s infinite` }}
              />
            ))}
          </span>
        )}
      </div>
    </div>
  );
}

export function ChatPanel({ sessionId, sources }: { sessionId: string; sources: Source[] }) {
  const qc = useQueryClient();
  const { data: history } = useChatHistory(sessionId);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState<Streaming | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [history, streaming]);

  const send = async () => {
    const text = input.trim();
    if (!text || streaming) return;
    setInput("");
    setStreaming({ user: text, assistant: "" });

    const controller = new AbortController();
    abortRef.current = controller;

    let res: Response;
    try {
      res = await fetch(`${apiBase()}/research/${sessionId}/chat`, {
        method: "POST",
        credentials: isDesktop ? "omit" : "include",
        headers: { ...authHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
        signal: controller.signal,
      });
    } catch {
      // Never reached the server — nothing persisted, so restore the input (docs/07 §6).
      setStreaming(null);
      setInput(text);
      toast.error("Network error — your message was not sent.");
      abortRef.current = null;
      return;
    }

    if (!res.ok || !res.body) {
      // Rejected before persisting (rate limit / validation) — restore the input.
      setStreaming(null);
      setInput(text);
      const detail = await res.json().catch(() => null);
      toast.error((detail as { detail?: string } | null)?.detail ?? "Message failed.");
      abortRef.current = null;
      return;
    }

    let streamError: string | null = null;
    try {
      await streamSSE(
        res.body,
        (ev) => {
          let data: { type?: string; text?: string; detail?: string };
          try {
            data = JSON.parse(ev.data);
          } catch {
            return;
          }
          if (data.type === "chunk" && typeof data.text === "string") {
            const chunk = data.text;
            // Immutable replace — never mutate the last array element (docs/07 §6).
            setStreaming((s) => (s ? { ...s, assistant: s.assistant + chunk } : s));
          } else if (data.type === "error") {
            streamError = data.detail ?? "The assistant hit an error.";
          }
        },
        controller.signal,
      );
    } catch {
      // Aborted or transport error mid-stream — the user message is persisted server-side.
      if (!controller.signal.aborted) streamError = "The response was interrupted.";
    }

    // The user message (and, on success, the assistant reply) are persisted — refetch
    // before clearing local streaming state so the transcript never flickers empty.
    await qc.invalidateQueries({ queryKey: queryKeys.chat(sessionId) });
    setStreaming(null);
    abortRef.current = null;
    if (streamError) toast.error(streamError);
  };

  const stop = () => abortRef.current?.abort();

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  };

  const messages = history ?? [];

  return (
    <div className="card flex h-[32rem] flex-col p-0">
      <div className="border-b border-border px-4 py-2.5">
        <h3 className="font-serif text-sm font-bold text-text-primary">Ask a Follow-up</h3>
        <p className="text-xs text-text-muted">Grounded in this report and its sources.</p>
      </div>

      <div
        ref={scrollRef}
        className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3"
        aria-live="polite"
        aria-label="Chat transcript"
      >
        {messages.length === 0 && !streaming && (
          <p className="text-sm text-text-muted">
            No messages yet. Ask something like &ldquo;What are the main limitations?&rdquo;
          </p>
        )}
        {messages.map((m) =>
          m.role === "user" ? (
            <UserBubble key={m.id} text={m.content} />
          ) : (
            <AssistantBubble key={m.id} text={m.content} sources={sources} />
          ),
        )}
        {streaming && (
          <>
            <UserBubble text={streaming.user} />
            <AssistantBubble text={streaming.assistant} sources={sources} />
          </>
        )}
      </div>

      <div className="flex items-end gap-2 border-t border-border p-3">
        <textarea
          rows={1}
          value={input}
          onChange={(e) => setInput(e.target.value.slice(0, 4000))}
          onKeyDown={onKeyDown}
          disabled={Boolean(streaming)}
          placeholder={streaming ? "Waiting for the response…" : "Ask a follow-up…"}
          className="textarea-base max-h-32 min-h-[2.5rem] flex-1 text-sm"
          aria-label="Chat message"
        />
        {streaming ? (
          <button type="button" onClick={stop} className="btn btn-secondary">
            Stop
          </button>
        ) : (
          <button
            type="button"
            onClick={() => void send()}
            disabled={!input.trim()}
            className="btn btn-primary"
          >
            Send
          </button>
        )}
      </div>
    </div>
  );
}
