# SSE protocol

Two different streams share the transport and almost nothing else:

| | Session events | Chat |
|---|---|---|
| Endpoint | `GET /research/{id}/stream` | `POST .../chat`, `POST /threads/{id}/messages` |
| Client | Native `EventSource` | `fetch` + a buffered reader (`EventSource` cannot POST) |
| Durable | **Yes** — replayable, with `Last-Event-ID` | No |
| Carries `id:` lines | Yes | No |

---

## Session event stream

### Connecting

```
GET /api/v1/research/{session_id}/stream
```

Authentication is the session cookie, sent automatically — which is the whole reason for the
same-origin proxy, since `EventSource` cannot set an `Authorization` header. On the desktop
build the sidecar is cross-origin, so the per-launch token rides as `?access_token=` instead
and credentials stay off.

`404` if the session is not yours.

Response headers:

```
Content-Type: text/event-stream
Cache-Control: no-cache, no-transform
X-Accel-Buffering: no
Connection: keep-alive
```

**`no-transform` is load-bearing, not decoration.** Any compressing intermediary will buffer
an event stream while it fills a compression window. The headers arrive immediately, so the
client sees a healthy open connection and simply never receives events — the monitor sits on
"waiting for the pipeline to start" forever while the pipeline runs normally. `no-transform`
is the HTTP-standard instruction not to alter the payload, and both nginx and Next's
compression middleware honour it. `X-Accel-Buffering: no` covers nginx's proxy buffering
specifically.

### The connection sequence

1. **`{"type": "connected"}`** — sent immediately, with no `id:`. It means the connection is
   live, not that anything has happened.
2. **Replay.** Every stored event for this session after `Last-Event-ID` (or from the start),
   in order, each with its `id:`.
3. **Live tail.** New events as they are published.

The server subscribes to the live channel **before** snapshotting the backlog. An event
published in the gap between those two steps would otherwise be lost from both — it is now
queued on the subscription and de-duplicated against the replay by its durable id.

### Frames

Every durable event is:

```
id: 128
data: {"type":"agent_log","id":128,"ts":"…","agent":"executor","message":"…","detail":{…}}

```

The `id` is the `agent_logs` row id — a monotonic bigserial, which is what makes it usable as
a resume cursor.

### Event types

```jsonc
// A pipeline step.
{"type": "agent_log", "id": 123, "ts": "…", "agent": "executor",
 "message": "Researching: 'EU AI Act Article 14 obligations'",
 "detail": {"task_id": 2, "query": "…", "model": "google:gemini-2.5-flash"}}

// The design gate. cost_usd is 0.0 on an ordinary run because the gate sits before the
// executor — reported rather than assumed, so a resumed run shows a real number.
{"type": "PLAN_READY", "id": 128, "ts": "…",
 "data": {"task_count": 5, "outline_section_count": 4, "cost_usd": 0.0}}

// The review gate.
{"type": "HITL_READY", "id": 130, "ts": "…",
 "data": {"word_count": 1240, "source_count": 9, "cost_usd": 0.18}}

// Terminal.
{"type": "COMPLETED", "id": 140, "ts": "…", "data": {"elapsed_s": 171.4, "cost_usd": 0.21}}
{"type": "FAILED",    "id": 141, "ts": "…", "data": {"reason": "cost ceiling reached: $0.5100 of $0.50"}}
```

The envelope always carries `type`, `ts`, `agent`, `message`, `detail`, and `data`; unused
fields are `null`.

### Terminal events

The stream **closes** after `COMPLETED`, `FAILED`, `PLAN_READY`, or `HITL_READY`.

The two gates are on that list for the same reason as the two terminal states: the graph is
suspended at an `interrupt()` and will publish nothing more until a human acts. Holding the
connection open would wait on nobody.

The desktop sidecar keeps the identical list. A new pause event must be added to **both**, or
a stream stays open on a suspended graph.

### Reconnection

Native `EventSource` reconnects automatically and sends `Last-Event-ID`, and the server
replays the durable log after that id — so a dropped connection loses nothing.

The client keeps a set of seen ids and de-duplicates replayed rows, and resets that set when
the subscription target changes.

**A stream is opened for every loaded session, including finished ones.** That is deliberate:
this stream is the only path by which the UI ever sees the run history, because the replay is
the only reader of those rows. Gating on `RUNNING` did not merely skip live updates — it
discarded the run's history, so a session that finished before its page loaded showed an
empty feed permanently. The connection is cheap for a finished run: the server ends the
response after the replay, and the client closes on the terminal event.

The subscription is keyed by session **and run generation** (the status), because approving a
draft restarts the pipeline without the session id changing. Without that, a client that had
closed itself on a terminal event would never reconnect and the rework would stream nothing.

**A polling fallback runs at 5 seconds** when the stream is degraded, so a run converges even
behind an intermediary that swallows the stream entirely. Two independent nets, because this
failure was real.

---

## Chat streams

`POST` endpoints, so `fetch` with a buffered reader rather than `EventSource`. No `id:`
lines, and no replay — chat history is fetched normally.

### Report chat

```jsonc
{"type": "connected", "scope": "report", "sources": [...], "notes": [...]}
{"type": "chunk", "text": "…"}
{"type": "done", "message_id": "uuid"}
{"type": "error", "detail": "…"}
```

Sources arrive **first** so citation chips can render as text streams in, and so a web-scoped
answer's `[n]` markers resolve. `scope` is echoed back because the answer has to be able to
say which grounding produced it. A retriever failure arrives as a `notes` entry and is stated
to the model as a gap — never swallowed into an empty grounding block the model would paper
over.

### Project chat

```jsonc
{"type": "connected", "citations": [...]}
{"type": "chunk", "text": "…"}
{"type": "done", "message_id": "uuid", "citations": [...]}
```

Citations are sent on `connected`, before the first token: they describe what was
*retrieved*, which is settled the moment the query runs. The `done` frame carries the
narrowed set — only the markers the answer actually used, because listing an unused excerpt
as a citation would be sources theatre.

---

## Client parsing

Two things are load-bearing in any SSE client here, and both had real regressions:

1. **Decode with streaming enabled.** Decoding each network chunk in isolation corrupts a
   multi-byte character split across a chunk boundary.
2. **Carry an incomplete event across reads.** Emit only once a full `\n\n`-terminated block
   has arrived, or events are dropped at chunk boundaries.

The parser in this repository is a pure string state machine for exactly this reason: an
event can be split mid-line across two feeds in a unit test and must still resolve.

Per the specification, one leading space after the field colon is stripped, comment lines
(`:`) are ignored, multiple `data:` lines are joined with newlines, and unknown fields are
ignored.
