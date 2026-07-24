import { describe, expect, it } from "vitest";

import { SSEParser, streamSSE, type SSEEvent } from "./sse";

function streamOf(chunks: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(c);
      controller.close();
    },
  });
}

describe("SSEParser", () => {
  it("parses a single complete event", () => {
    const events = new SSEParser().feed('data: {"type":"chunk"}\n\n');
    expect(events).toHaveLength(1);
    expect(events[0].data).toBe('{"type":"chunk"}');
  });

  it("parses several events from one chunk", () => {
    const events = new SSEParser().feed("data: a\n\ndata: b\n\ndata: c\n\n");
    expect(events.map((e) => e.data)).toEqual(["a", "b", "c"]);
  });

  it("carries a partial event across feeds and emits it once complete", () => {
    const p = new SSEParser();
    expect(p.feed('data: {"ty')).toHaveLength(0); // incomplete — nothing yet
    expect(p.feed('pe":"chunk"}')).toHaveLength(0); // still no terminator
    const events = p.feed("\n\n");
    expect(events).toHaveLength(1);
    expect(events[0].data).toBe('{"type":"chunk"}');
  });

  it("splits events correctly when a boundary lands mid-terminator", () => {
    const p = new SSEParser();
    expect(p.feed("data: one\n")).toHaveLength(0);
    const events = p.feed("\ndata: two\n\n");
    expect(events.map((e) => e.data)).toEqual(["one", "two"]);
  });

  it("joins multi-line data and reads id/event fields", () => {
    const events = new SSEParser().feed("id: 42\nevent: agent_log\ndata: line1\ndata: line2\n\n");
    expect(events[0]).toEqual({ id: "42", event: "agent_log", data: "line1\nline2" });
  });

  it("ignores comments and keep-alive pings", () => {
    const events = new SSEParser().feed(": ping\n\ndata: real\n\n");
    expect(events.map((e) => e.data)).toEqual(["real"]);
  });

  it("handles CRLF line endings", () => {
    const events = new SSEParser().feed("data: crlf\r\n\r\n");
    expect(events.map((e) => e.data)).toEqual(["crlf"]);
  });

  it("flush() emits a trailing event that never got its blank line", () => {
    const p = new SSEParser();
    expect(p.feed("data: trailing\n")).toHaveLength(0);
    expect(p.flush().map((e) => e.data)).toEqual(["trailing"]);
  });
});

describe("streamSSE", () => {
  // The named regression from docs/08 §3:
  // test_sse_parser_handles_split_utf8_and_partial_events
  it("decodes multi-byte UTF-8 split across chunk boundaries without corruption", async () => {
    const payload = 'data: {"text":"😀 café"}\n\n';
    const bytes = new TextEncoder().encode(payload);

    // 'data: {"text":"' is 15 ASCII bytes, so the emoji occupies bytes 15..18.
    // Cut at 17 — squarely inside the emoji's 4-byte sequence.
    const chunks = [bytes.slice(0, 17), bytes.slice(17)];

    const seen: SSEEvent[] = [];
    await streamSSE(streamOf(chunks), (e) => seen.push(e));

    expect(seen).toHaveLength(1);
    expect(JSON.parse(seen[0].data).text).toBe("😀 café");
  });

  it("emits events in order across many small chunks", async () => {
    const payload = "data: one\n\ndata: two\n\ndata: three\n\n";
    const bytes = new TextEncoder().encode(payload);
    const chunks: Uint8Array[] = [];
    for (let i = 0; i < bytes.length; i += 3) chunks.push(bytes.slice(i, i + 3));

    const seen: SSEEvent[] = [];
    await streamSSE(streamOf(chunks), (e) => seen.push(e));

    expect(seen.map((e) => e.data)).toEqual(["one", "two", "three"]);
  });

  it("stops feeding events once the signal is aborted", async () => {
    const controller = new AbortController();
    controller.abort();
    const bytes = new TextEncoder().encode("data: never\n\n");

    const seen: SSEEvent[] = [];
    await streamSSE(streamOf([bytes]), (e) => seen.push(e), controller.signal);

    expect(seen).toHaveLength(0);
  });
});
