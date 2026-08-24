# Running research

What happens between asking a question and getting a report.

## Submitting a question

A research question is 10–2000 characters. A real question — "What obligations does the EU
AI Act place on providers of general-purpose AI models?" — decomposes better than a keyword.

Alongside it you choose:

**Depth** — `fast`, `balanced`, or `comprehensive`. This is the main cost dial: it tells the
planner how far to decompose the question, and every task is a paid round of search.

**Project** — which project the run belongs to. Omit it and the run lands in your default
project, so a brand-new account is never blocked from starting.
([Projects and memory](28-projects-and-memory.md))

**Models** — optionally, a per-run routing override. Otherwise it resolves from your saved
preference, then the deployment default. Whatever is resolved is snapshotted on the
session, so a resumed run keeps the models it started with and the finished report stays
attributable to what wrote it.

**Subtopics** — up to 20 seed topics the plan must cover. The planner treats them as a
floor, not a ceiling, and you can still edit the result at the design gate.

**Outline** — a report structure from the template catalogue, previewed before you choose.
The templates are served from the same module the synthesizer is handed, so what you preview
is what it gets.

**Corpus only** — restrict evidence to documents you uploaded to this project. No web
retriever runs and page fetching refuses every non-corpus URL, so the run makes no network
calls at all. A run in this mode with no corpus installed fails rather than quietly falling
back to the web.

## What happens during execution

The request returns immediately with a session id and status `PENDING`; the work runs in a
background worker. The browser opens an event stream and starts showing progress.

```
Planner  →  ⏸ design gate  →  Executor ⇄ Critic  →  Contradiction detector
                                                              ↓
                                  Report  ←  Finalizer  ←  ⏸ review gate  ←  Synthesizer
```

**Planner** decomposes the question into independently searchable tasks, each with a
concrete query and a rationale, and proposes a report outline.

**Design gate** pauses the run before anything is searched.
([Review and approval](26-review-and-approval.md))

**Executor** runs real tool calls — `web_search`, `read_webpage`, `calculate` — and returns
structured evidence: for each fact, the source URL, the source title, and a **verbatim
snippet** capped at 500 characters. Tasks run concurrently, four at a time by default.

**Critic** grades each task's evidence and **fails closed**: unparseable or missing critic
output counts as a failure, never as a pass. A failing task goes back to the executor with
actionable feedback, within a bounded retry limit. A task that exhausts its retries still
contributes what it found — the report says so in its limitations rather than pretending.

**Contradiction detector** looks for pairs of sources that cannot both be true. Both sides
must be quoted from snippets it was actually shown, and any pair whose source URL was not
in the evidence is dropped — so a fabricated conflict cannot reach the report. Conflicts are
surfaced, never auto-resolved.

**Synthesizer** writes the cited Markdown draft using only the gathered evidence. Every
factual claim carries `[n]` markers that map to the evidence list. If you approved an
outline at the design gate, that structure replaces the default sections — a human chose it,
so it outranks the default. It never relaxes a citation rule: an outline decides what the
sections are, never what may be said in them without a source.

**Review gate** pauses for your approval. **Finalizer** produces the report.

## Live progress

Every node emits events. Each is written to a durable log **first** and published for live
fan-out **second**, which is what makes the feed lossless: on connect the server replays the
stored events (honouring `Last-Event-ID`) and only then tails the live stream. Refresh the
page, join late, or lose your connection — nothing is missed.

The feed shows the pipeline rail with each stage's state, and a message log with the actual
searches being run. If the stream is blocked by an intermediary, the client falls back to
polling every five seconds, so a run still converges.

The stream closes on a terminal event: `COMPLETED`, `FAILED`, or either of the two gates.
Holding it open at a gate would wait on nobody — the graph is suspended until a human acts.

Protocol detail: [SSE protocol](../reference/35-sse.md).

## Cost and limits

Token usage is read from each model response and accumulated on the session. Every run limit
is **`0 = unlimited`, and `0` is the default** — nothing stops a long run out of the box.

When a guard does fire, it says which one and by how much, and the partial results are
preserved rather than discarded.

Two caveats worth knowing before you rely on a number:

- **`$0.00` does not mean free on OpenRouter or custom endpoints.** Their prices are not in
  the catalog, so estimated cost is always zero and the cost cap cannot fire. Cap spend at
  the provider.
- **Router aliases are not pinned models.** An `auto/*` route resolves differently per call,
  so what served the request may not be what the alias names. The session records what
  actually answered.

## Stopping, archiving, deleting

**Stop** a `PENDING` or `RUNNING` session and it moves to `FAILED` with "Research stopped by
user", and that decision is durable — it is recorded on the session, not in a cache entry
that expires.

What it does **not** do is interrupt work already in flight. The pipeline runs on to its
next checkpoint, spending tokens after you have been told the run stopped; that spend is
still recorded on the session, because it was really incurred. What is guaranteed is that
the run cannot come back: when the pipeline finally delivers its outcome, the writer sees
the stop and keeps the session terminal instead of moving it to the review gate. Before
this was fixed, a stopped run could reappear minutes later awaiting your approval.

**Archive** moves a session out of the active list. It is reversible and loses nothing —
the archive is a destination, not a filter, so the default view never includes archived
sessions.

**Delete** is permanent and removes everything derived from the session: agent logs, chat
messages, and audit rows cascade, and the graph checkpoints are dropped explicitly. Without
that last step "delete" would leave the full agent state — including fetched page content —
behind, which is exactly what someone deleting a session is asking you not to do. A running
session cannot be deleted; stop it first.

## Failure states

A run that fails records **why**. `FAILED` is terminal and carries a reason: a breached
budget names the limit and the overshoot; a provider error surfaces the provider's own
message rather than a generic parse failure. Partial evidence is preserved and the sources
gathered so far still render.

The design principle behind that: a degraded pipeline produces an explicit failure with a
reason, never a silently thinner report.
