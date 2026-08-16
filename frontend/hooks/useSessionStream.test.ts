import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useSessionStream } from "./useSessionStream";

/** Every EventSource the hook constructed, in order. */
let opened: FakeEventSource[] = [];

class FakeEventSource {
  static readonly CLOSED = 2;
  readyState = 0;
  closed = false;
  onopen: (() => void) | null = null;
  onmessage: ((e: MessageEvent<string>) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(readonly url: string) {
    opened.push(this);
  }

  close() {
    this.closed = true;
    this.readyState = FakeEventSource.CLOSED;
  }
}

// One client for the whole file. Constructing it inside the wrapper made a fresh client
// on every render, which changed the identity `useQueryClient()` returns and re-ran the
// hook's effect by itself — the reconnect test then passed against code that could not
// reconnect, proving nothing.
const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

function wrapper({ children }: { children: ReactNode }) {
  return createElement(QueryClientProvider, { client: queryClient }, children);
}

beforeEach(() => {
  opened = [];
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useSessionStream", () => {
  it("connects for a session that has already finished", () => {
    // The backend replays durable agent_logs on connect, so this is how a finished run
    // gets its history back. Refusing to connect left the feed empty forever.
    renderHook(() => useSessionStream("abc", true, "AWAITING_APPROVAL"), { wrapper });

    expect(opened).toHaveLength(1);
    expect(opened[0].url).toContain("/api/v1/research/abc/stream");
  });

  it("reconnects when the run generation changes", () => {
    // Approving a draft flips the session back to RUNNING. The client closes the stream
    // on the terminal event, so without a new subscription the rework would stream
    // nothing — the regression that arrives the moment `enabled` stops toggling.
    const { rerender } = renderHook(({ runKey }) => useSessionStream("abc", true, runKey), {
      wrapper,
      initialProps: { runKey: "AWAITING_APPROVAL" },
    });

    expect(opened).toHaveLength(1);

    rerender({ runKey: "RUNNING" });

    expect(opened).toHaveLength(2);
    expect(opened[0].closed).toBe(true);
  });

  it("does not connect before the session row has loaded", () => {
    renderHook(() => useSessionStream("abc", false, undefined), { wrapper });

    expect(opened).toHaveLength(0);
  });
});
