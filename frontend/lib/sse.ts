/**
 * UTF-8-safe, boundary-safe SSE parsing (docs/07 §6).
 *
 * The previous iteration corrupted emoji and dropped events at chunk boundaries by
 * decoding each network chunk in isolation. Two fixes, both load-bearing:
 *   1. `TextDecoder.decode(value, { stream: true })` keeps partial multi-byte UTF-8
 *      sequences buffered across reads (see `streamSSE`).
 *   2. `SSEParser` carries an incomplete event across `feed()` calls, only emitting
 *      once a full `\n\n`-terminated event has arrived.
 *
 * `SSEParser` is a pure string state machine so it can be unit-tested without a
 * network — split an event mid-line across two `feed()` calls and it still resolves.
 */

export interface SSEEvent {
  id?: string;
  event?: string;
  data: string;
}

export class SSEParser {
  private buffer = "";

  /** Feed a decoded text chunk; return every complete event it now contains. */
  feed(chunk: string): SSEEvent[] {
    // Normalize line endings so `\r\n` and `\r` split identically to `\n`. Safe to
    // run on the whole buffer each call because we never split a `\r\n` pair.
    this.buffer = (this.buffer + chunk).replace(/\r\n/g, "\n").replace(/\r/g, "\n");

    const events: SSEEvent[] = [];
    let sep: number;
    while ((sep = this.buffer.indexOf("\n\n")) !== -1) {
      const raw = this.buffer.slice(0, sep);
      this.buffer = this.buffer.slice(sep + 2);
      const ev = this.parseBlock(raw);
      if (ev) events.push(ev);
    }
    return events;
  }

  /** Emit a trailing event that arrived without a final blank line, if any. */
  flush(): SSEEvent[] {
    const raw = this.buffer;
    this.buffer = "";
    const ev = raw.trim() ? this.parseBlock(raw) : null;
    return ev ? [ev] : [];
  }

  private parseBlock(raw: string): SSEEvent | null {
    let id: string | undefined;
    let event: string | undefined;
    const dataLines: string[] = [];

    for (const line of raw.split("\n")) {
      if (line === "" || line.startsWith(":")) continue; // blank or comment
      const colon = line.indexOf(":");
      const field = colon === -1 ? line : line.slice(0, colon);
      let value = colon === -1 ? "" : line.slice(colon + 1);
      if (value.startsWith(" ")) value = value.slice(1); // strip one leading space (spec)

      switch (field) {
        case "data":
          dataLines.push(value);
          break;
        case "id":
          id = value;
          break;
        case "event":
          event = value;
          break;
        // `retry` and unknown fields are ignored.
      }
    }

    if (dataLines.length === 0 && event === undefined) return null;
    return { id, event, data: dataLines.join("\n") };
  }
}

/**
 * Drive an SSE parser over a byte stream (a `fetch` response body). Used by the chat
 * panel, whose request is a POST and therefore cannot use native `EventSource`.
 */
export async function streamSSE(
  stream: ReadableStream<Uint8Array>,
  onEvent: (ev: SSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const reader = stream.getReader();
  const decoder = new TextDecoder("utf-8");
  const parser = new SSEParser();

  try {
    while (true) {
      if (signal?.aborted) return;
      const { done, value } = await reader.read();
      if (done) break;
      const text = decoder.decode(value, { stream: true });
      if (text) for (const ev of parser.feed(text)) onEvent(ev);
    }
    const tail = decoder.decode(); // flush any buffered bytes
    if (tail) for (const ev of parser.feed(tail)) onEvent(ev);
    for (const ev of parser.flush()) onEvent(ev);
  } finally {
    reader.releaseLock();
  }
}
