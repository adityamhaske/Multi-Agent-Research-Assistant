import { describe, expect, it } from "vitest";

import { shouldOpenStream } from "./sessionStream";

/**
 * Regression: the session monitor showed an empty activity feed for any run that had
 * already finished.
 *
 * The SSE stream is not only the live channel — it is how *history* arrives. The backend
 * replays the durable `agent_logs` on connect before tailing Redis, and nothing else in
 * the UI reads those logs (the only other query for them builds the export bundle). So
 * gating the connection on RUNNING meant a finished session never asked for its own
 * history, and sat on "Waiting for the pipeline to start…" forever.
 *
 * It surfaced as a flaky golden E2E because a fake-mode run reaches the gate in ~0.67s:
 * the page won the race often enough to look fine.
 */
describe("shouldOpenStream", () => {
  it("opens for a run still in flight", () => {
    expect(shouldOpenStream("PENDING")).toBe(true);
    expect(shouldOpenStream("RUNNING")).toBe(true);
  });

  it("opens for a run that already finished, because history arrives on the stream", () => {
    expect(shouldOpenStream("AWAITING_APPROVAL")).toBe(true);
    expect(shouldOpenStream("COMPLETED")).toBe(true);
    expect(shouldOpenStream("FAILED")).toBe(true);
  });

  it("stays shut until the session row has loaded", () => {
    // No status yet means there is no session to replay — connecting would race the fetch.
    expect(shouldOpenStream(undefined)).toBe(false);
    expect(shouldOpenStream("")).toBe(false);
  });
});
