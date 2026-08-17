# Projects and memory

A project is the container research lives in. It scopes your sessions, your uploaded
documents, and the chat that can read them.

```
Project
├── Research sessions      every run belongs to exactly one project
├── Corpus documents       files you uploaded, searchable as evidence
├── Memory chunks          embedded slices of APPROVED reports only
└── Chat threads           conversation over that approved research
```

**Project chat and project memory are server-only.** The desktop build has sessions and a
corpus but no cross-report memory, because memory is pgvector-backed. This is a design
boundary, not a gap that is about to close.

## Projects

Create as many as you like. Names are unique per user, case-insensitively — "Thesis" and
"thesis" as separate projects is a trap rather than a feature.

Every account gets a default project, so a first run never requires creating one first.
Existing sessions from before projects existed were backfilled into a per-user "General"
project.

**Archive** hides a project without losing anything. **Delete** removes it and cascades:
its sessions, threads, messages, and memory chunks all go. A project with a running session
refuses to delete until that session finishes.

## The approval gate is the memory filter

This is the load-bearing idea:

> **Only reports that passed the human approval gate enter project memory.**

Drafts, rejected work, and failed runs never pollute retrieval. Ingestion is not a
background heuristic — it hooks exactly one place, the transition to `COMPLETED`, which is
reachable only through the review gate.

The consequences are the point:

- Every chat answer traces to an approved report → its sources → their verbatim snippets.
  The provenance chain extends end to end with no new concept.
- Garbage-in-memory — the failure mode of every "the AI remembers everything" feature — is
  structurally prevented rather than mitigated.
- Approving is also curating, which makes the gate worth something beyond compliance.

### Deliberately excluded from memory

| Excluded | Why |
|---|---|
| Chat turns | Unverified. Recycling model output as fact compounds hallucination while citing itself. |
| Draft and rejected reports | They failed the human gate; that is the whole signal. |
| Raw evidence not used in a report | High noise. |

## How memory is built

An approved report is split on **Markdown structure** rather than at a character count, so a
chunk is a section rather than an arbitrary window. The nearest heading is carried into
continuation chunks, chunks overlap by a sentence, and short sections pack together instead
of sharding at every heading — each chunk is an embedding call, and that is spend.

Chunking is deterministic, and a uniqueness constraint on `(source_session_id, chunk_index)`
turns that into an idempotency guarantee: approving twice does not double the corpus or the
bill, and a failed ingestion is safe to retry.

### Embeddings

`EMBEDDINGS_PROVIDER` defaults to `auto`: a local Ollama when one is reachable with an
embedding model installed — free, no egress — otherwise whichever hosted provider has a key,
your own BYOK key first. `none` disables memory rather than degrading it.

**Equal width is not equal meaning.** Every supported provider is configured to 768
dimensions so switching one is a re-index rather than a migration, but vectors from
different models are not comparable at any width. Each chunk records the model that produced
it and retrieval filters on it. Chunks written by a retired model become **invisible** rather
than silently mis-ranked.

**The absent case fails closed.** With no embedder available, ingestion logs the failure and
leaves the report un-indexed — the run already succeeded and must not be failed
retroactively — and project chat returns 503 rather than answering ungrounded. A no-op would
write nothing, match nothing, and surface weeks later as "memory doesn't work" with no error
anywhere.

### Knowing when memory is incomplete

`GET /projects/{id}/memory/status` reports chunk and report counts, the current embedding
model, **stale models**, and **pending reports** (approved but not indexed). Those are the
two ways memory goes quietly incomplete — an ingestion that failed, and chunks from a model
no longer configured — and neither is otherwise distinguishable from "chat has nothing on
that".

## Isolation

**Isolation is a SQL boundary, never a prompt instruction.** Every retrieval is filtered by
`project_id` — after an ownership check — before any text reaches a model. A prompt-level
"only use Project X" is not a security control and is not treated as one.

That is asserted against a real database, for two projects owned by the **same user** (the
case a per-user check alone waves through) as well as across accounts. A question whose
answer exists only in a rejected draft retrieves nothing.

Cross-project chat is **planned**, and when it lands it will be explicit opt-in per thread,
visibly indicated, audited on change, and still a SQL predicate.

## Project chat

Threads are project-scoped conversations, titled from your first message and ordered by last
use. Answers cite retrieved chunks as `[R1]`, `[R2]`, which resolve to the report title,
date, and link, and through the report to its original sources.

Citations arrive on the stream's `connected` frame, before the first token — they describe
what was *retrieved*, which is settled the moment the query runs — so chips render as the
answer streams. Only markers the answer actually used are persisted.

Retrieved excerpts are wrapped in untrusted-content framing unconditionally. They originated
as web pages, so an injection captured months ago is still an injection when it resurfaces —
arguably a worse one, because nobody is watching the run any more.

The relevance cutoff is deliberately loose: retrieval drops only results worse than
orthogonal, and the prompt carries the weight instead — the excerpts' presence is explicitly
not evidence that they are relevant, and "this project's research doesn't cover that" is the
correct answer. Tightening that threshold is future tuning once there are real measurements
to tighten it against.

## The corpus

Separate from memory, and complementary. You upload documents — `pdf`, `html`, `md`, `txt` —
to a project, and they become searchable evidence.

Documents preview in place from the corpus list rather than downloading. PDFs render in the
browser's own sandboxed viewer; everything else is fetched and rendered by the client
without leaving the page.

**Corpus-only mode** is the airgapped tier: evidence comes exclusively from the corpus,
page fetching refuses every non-corpus URL, and the run makes zero network calls. Corpus
hits carry `corpus://` locations, and the synthesizer turns them into ordinary `[n]`
citations whose snippets resolve back to the exact character range in the source document —
so citation provenance is *more* exact on a closed corpus than on the open web.

Follow-up chat has its own scope selector: **this report**, **my corpus**, **web**, or
**everything**. "My corpus" promises no retrieval egress — no web retriever runs, and the
question is refused rather than embedded off-machine if the configured embedder is remote.
It does not promise zero network calls, because the answer is still written by a model that
is remote unless chat is routed to a local one. The UI says exactly that.

## Deletion

Deleting a project deletes its memory — no orphan vectors — as well as its sessions, threads
and messages. Deleting a single session removes its memory chunks and its graph checkpoints
along with it.
