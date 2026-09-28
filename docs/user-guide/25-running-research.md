# Running research

What happens between asking a question and getting a report.

## Submitting a question

A research question is 10–2000 characters. A real question — "What obligations does the EU
AI Act place on providers of general-purpose AI models?" — decomposes better than a keyword.

Alongside it you choose:

**Depth** — `fast`, `balanced`, or `comprehensive`. This is the main cost dial: it sets how far
the planner decomposes the question and how much each task may do — up to 3 model turns and 3
pages per task on `fast`, 5 on `balanced`, 8 on `comprehensive`. Turns are most of a run's
wall-clock, so the form states the numbers rather than a promise of thoroughness.

**Models** — optionally, a per-run routing override. Otherwise it resolves from your saved
preference, then the deployment default. Whatever is resolved is snapshotted on the run, so a
resumed run keeps the models it started with and the finished report stays attributable to
what wrote it.

**Restrict to uploaded corpus** — evidence only from documents you uploaded to this project.
No web retriever runs and page fetching refuses every non-corpus URL, so the run makes no
network calls at all. A run in this mode with no corpus installed fails rather than quietly
falling back to the web.

**Review the research plan before searching** — on by default: the run pauses at the design
gate after the planner, before anything is spent. Turn it off and the run starts searching
immediately. ([Review and approval](26-review-and-approval.md))

The run belongs to the project selected in the switcher.
([Projects and memory](28-projects-and-memory.md))

**Instructions** are not chosen per run. Each agent follows the instructions saved under
Settings → Agents, or its shipped ones, and the run takes a copy when it starts and keeps it
to the end — editing an agent while this run waits at a gate changes your next run, not this
one. ([Agent instructions](38-agent-instructions.md))

**Seed subtopics and a report outline** can be set through the API — `topic_seeds` and
`outline_template` on `POST /runs` — but the app's run form does not offer them yet. The
planner treats seed topics as a floor, not a ceiling.
([API reference](../reference/34-api.md))

## What happens during execution

Submitting creates a run and returns immediately with its id and status `PENDING`. The work
runs in the background — a Celery worker on the server, an in-process task on the desktop
app — and the browser opens the run's event stream and starts showing progress.

```
Planner  →  ⏸ design gate  →  Executor ⇄ Critic  →  Contradiction detector
                                                              ↓
                                          Artifact  ←  ⏸ review gate  ←  Synthesizer
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

**Review gate** pauses for your approval. Approving freezes the report, its evidence and your
decision into the artifact — nothing is re-run, and no model is called.
([Review and approval](26-review-and-approval.md))

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

Token usage is read from each model response and accumulated on the run. Every run limit is
**`0 = unlimited`, and `0` is the default** — nothing stops a long run out of the box.

When a guard does fire, it says which one and by how much, and the partial results are
preserved rather than discarded.

Two caveats worth knowing before you rely on a number:

- **`$0.00` does not mean free on OpenRouter or custom endpoints.** Their prices are not in
  the catalog, so estimated cost is always zero and the cost cap cannot fire. Cap spend at
  the provider.
- **Router aliases are not pinned models.** An `auto/*` route resolves differently per call,
  so what served the request may not be what the alias names. The run records what actually
  answered.

## Stopping, archiving, deleting

**Stop** a run that has not finished — running, or waiting for you at either gate — and it
moves to `CANCELLED`, recording when and by whom. That decision is durable: it is a column
on the run, not a cache entry that expires.

What it does **not** do is interrupt work already in flight. The pipeline runs on to its
next checkpoint, spending tokens after you have been told the run stopped; that spend is
still recorded on the run, because it was really incurred. What is guaranteed is that the run
cannot come back: when the pipeline finally delivers its outcome, the writer reads the stop
from the database and keeps the run cancelled instead of moving it to the review gate. That
holds wherever the stop lands — before the pipeline's first step, or in the middle of it —
on both the server and the desktop app; 3.0.0 closed the cases where it did not.

**Archive** moves a run out of History. It is reversible and loses nothing — the archive is
a destination, not a filter, so the default view never includes archived runs.

**Delete** is permanent and removes everything the run produced: its plans, sources,
evidence, revisions, claims, links, contradictions, reviews, artifact, trace and
project-memory chunks, and its graph checkpoints. Without that last step "delete" would leave
the full agent state — including fetched page content — behind, which is exactly what someone
deleting a run is asking you not to do. A run that is still active cannot be deleted; stop it
first.

## Failure states

A run that fails records **why**. `FAILED` is terminal and carries a reason: a breached
budget names the limit and the overshoot; a provider error surfaces the provider's own
message rather than a generic parse failure. Partial evidence is preserved and the sources
gathered so far still render.

The design principle behind that: a degraded pipeline produces an explicit failure with a
reason, never a silently thinner report.
