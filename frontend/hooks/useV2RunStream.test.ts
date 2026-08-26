import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useV2RunStream } from "./v2";

/**
 * A client that stops reading at a gate it has already passed sees no run at all.
 *
 * The scar this pins (run `96a16137`, 2026-08-25): the workspace showed the planner
 * spinning and every later stage untouched for the whole of a run that had, in fact,
 * searched the web, fetched seven pages, failed the critic twice and terminated. The
 * backend was blameless — `agent_logs` held all thirty rows and the stream endpoint
 * replays past gates on purpose (`_REPLAY_STOP_EVENTS`, deliberately *not*
 * `_TERMINAL_EVENTS`).
 *
 * The client undid it. `onmessage` closed the EventSource on `PLAN_READY` whenever one
 * arrived — including the one replayed out of the durable backlog on every reconnect,
 * and the subscription re-opens on every status change. So each connection replayed two
 * planner rows, hit the historical gate, and hung up before the executor's first line.
 *
 * The rule is the server's, mirrored: a gate closes the stream only when the run is
 * *parked* at it. History that has moved on is just history.
 */

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

  /** Deliver one server-sent event, durable id and all. */
  send(id: number, payload: Record<string, unknown>) {
    act(() => {
      this.onmessage?.({
        data: JSON.stringify(payload),
        lastEventId: String(id),
      } as MessageEvent<string>);
    });
  }

  close() {
    this.closed = true;
    this.readyState = FakeEventSource.CLOSED;
  }
}

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

/** The backlog a run replays after its design gate has been approved and it has failed. */
function replayPastTheGate(source: FakeEventSource) {
  source.send(1, { type: "agent_log", agent: "planner", message: "Created 5 research tasks" });
  source.send(2, { type: "PLAN_READY", tasks: [] });
  source.send(3, { type: "agent_log", agent: "executor", message: "Used web_search" });
  source.send(4, { type: "agent_log", agent: "executor", message: "Gathered 0 source(s)" });
}

describe("useV2RunStream", () => {
  it("keeps reading past a design gate the run has already left", () => {
    const { result } = renderHook(() => useV2RunStream("run-1", true, "FAILED"), { wrapper });
    replayPastTheGate(opened[0]);

    const agents = result.current.events.map((e) => e.agent);
    expect(agents, "executor events after the replayed gate were dropped").toContain("executor");
    expect(result.current.events).toHaveLength(4);
    expect(opened[0].closed, "a historical gate must not hang up the connection").toBe(false);
  });

  it("still closes at a gate the run is actually parked at", () => {
    // The original intent, and it must survive: a suspended graph publishes nothing more,
    // so holding the socket open waits on no one.
    const { result } = renderHook(() => useV2RunStream("run-1", true, "AWAITING_PLAN"), {
      wrapper,
    });
    opened[0].send(1, { type: "agent_log", agent: "planner", message: "Created 5 tasks" });
    opened[0].send(2, { type: "PLAN_READY", tasks: [] });

    expect(opened[0].closed).toBe(true);
    expect(result.current.events).toHaveLength(2);
  });

  it("closes at the report gate only when parked there", () => {
    const parked = renderHook(() => useV2RunStream("run-a", true, "AWAITING_REVIEW"), { wrapper });
    opened[0].send(1, { type: "HITL_READY" });
    expect(opened[0].closed).toBe(true);
    expect(parked.result.current.events).toHaveLength(1);

    const movedOn = renderHook(() => useV2RunStream("run-b", true, "COMPLETED"), { wrapper });
    opened[1].send(1, { type: "HITL_READY" });
    opened[1].send(2, { type: "agent_log", agent: "synthesizer", message: "Rework drafted" });
    expect(opened[1].closed).toBe(false);
    expect(movedOn.result.current.events).toHaveLength(2);
  });

  it("closes on a true terminal, whatever the status says", () => {
    // A terminal is the end of the backlog by definition — the server stops replaying
    // there too (`_REPLAY_STOP_EVENTS`), so there is nothing after it to miss.
    renderHook(() => useV2RunStream("run-1", true, "RUNNING"), { wrapper });
    opened[0].send(1, { type: "FAILED" });

    expect(opened[0].closed).toBe(true);
  });

  it("de-dupes replayed rows by their durable id", () => {
    const { result } = renderHook(() => useV2RunStream("run-1", true, "FAILED"), { wrapper });
    opened[0].send(7, { type: "agent_log", agent: "executor", message: "Used web_search" });
    opened[0].send(7, { type: "agent_log", agent: "executor", message: "Used web_search" });

    expect(result.current.events).toHaveLength(1);
  });
});
