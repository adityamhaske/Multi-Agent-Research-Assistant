# 14. Projects & Project Memory

> **Built.** Projects shipped in M16; memory, threads and cited project chat in M17.
> This document was written before implementation per [00_INDEX.md](../00_INDEX.md) and
> has been updated to describe what exists. Where the built thing differs from the
> original sketch, the difference is marked **[changed]** with the reason — the sketch
> was written before the call sites existed, and pretending otherwise is the divergence
> these docs exist to prevent.
>
> One thing here remains unmeasured rather than unbuilt, and is marked
> **[unmeasured]** in §5 and §9: whether a real model, handed correct excerpts, reliably
> writes correct `[R{n}]` markers. That is a model-quality question for the eval harness,
> not something the fake-mode CI can demonstrate.

## 1. Why this exists

Today a research session is an island: one query → one report → chat bound to that one
report. Users accumulate dozens of unrelated sessions in a flat history, and knowledge
from one run is invisible to the next.

**Projects** make the workspace the unit of organization, and make prior *approved*
research retrievable by chat. This is the same infrastructure [12_Launch_Plan.md](../product/12_Launch_Plan.md)
M10 ("airgapped corpus mode") needs — scoped knowledge store, embeddings, retrieval,
isolation — under a name users already understand from Claude/ChatGPT/NotebookLM.

### The positioning constraint (binding)

**Projects are containers for research. This is not a chat app.** The differentiator
remains the pipeline + approval gate + verifiable citations. Chat is how a user
interrogates verified project knowledge — not a general assistant that happens to
research. Every design decision below defers to that.

Competing head-on with Claude Projects/NotebookLM on generic project-chat is explicitly
rejected ([01_Product_Vision.md](../product/01_Product_Vision.md) positioning). What they
do not do is per-claim provenance; independent testing (Tow Center, 2025) found AI search
misattributes citations >60% of the time. **Cited chat over your own verified research is
the wedge.**

## 2. The approval gate becomes the memory filter

The load-bearing idea, and the reason this fits *this* product rather than any chat app:

> **Only reports that passed the human approval gate enter project memory.**

Drafts, rejected work, and failed runs never pollute retrieval. Memory ingestion is
therefore not a background heuristic — it is a deliberate, human-verified event that the
system already models. Concretely, ingestion hooks exactly one place:
`app/workers/pipeline_runner._persist_outcome`, on the transition to `COMPLETED`.

Consequences:

- Every chat answer traces to an approved report → its sources → their snippets. The
  existing citation chain ([05_Data_and_API.md](05_Data_and_API.md) `sessions.sources`)
  extends end-to-end with no new provenance concept.
- Garbage-in-memory — the failure mode of every "AI remembers everything" feature — is
  structurally prevented rather than mitigated.
- The gate gains value instead of being friction: approving is also curating.

### Excluded from memory (deliberately, v1)

| Excluded | Why |
|---|---|
| Chat turns | Unverified. Recycling model output as fact compounds hallucination while citing itself. **[PLANNED]** later as a visually distinct "from our earlier conversation" tier — never as a cited fact. |
| Draft / rejected reports | Failed the human gate; that is the whole signal. |
| Raw evidence snippets not used in a report | High noise. Reconsider after measuring recall. |
| Uploaded documents | Real, but a separate milestone (M10). Same tables, later phase. |

## 3. Data model

```
users
 └── projects (1:N)
      ├── sessions          (project_id FK — research runs live in a project)
      ├── chat_threads      (project_id FK — chat is NOT bound to one report)
      └── memory_chunks     (project_id FK — embeddings of APPROVED reports only)
```

| Table | Key columns | Notes |
|---|---|---|
| `projects` | id, user_id FK, name, description, created_at, archived_at | `unique(user_id, lower(name))` — names are per-user unique, case-insensitive |
| `sessions` | **+ project_id** FK NOT NULL | Existing rows backfill into a per-user "General" project (§7) |
| `chat_threads` | id, project_id FK, title, created_at, last_message_at | Multiple parallel threads per project; title auto-derived from first message |
| `chat_messages` | **+ thread_id** FK, **+ citations** JSONB | `session_id` relaxed to nullable so legacy per-report chat keeps working |
| `memory_chunks` | id, project_id FK, source_session_id FK, chunk_index, text, `embedding vector(768)`, **embedding_model**, created_at | Written only on approval; `ON DELETE CASCADE` from both project and session |

Indexes: `sessions(project_id, created_at DESC)`, `chat_threads(project_id, last_message_at DESC)`,
`memory_chunks(project_id)` + an HNSW index on `embedding` (`vector_cosine_ops`, matching
the retrieval operator). Migrations 0007 and 0008.

**[changed] Two constraints the sketch did not name, both load-bearing:**

- `unique(source_session_id, chunk_index)` on `memory_chunks`. Chunking is deterministic,
  so re-ingesting a report collides with its existing rows instead of doubling the corpus
  — which is what makes ingestion safe to retry after a failure.
- `CHECK ((session_id IS NOT NULL) <> (thread_id IS NOT NULL))` on `chat_messages`.
  "`session_id` retained nullable" alone permits a row with *neither* parent: a message
  that appears in no history at all, whose first symptom is a user's question vanishing.
  Exactly one parent, enforced by the database.

`chat_messages.citations` stores the resolved `[R{n}]` markers for a thread reply, so the
chips still resolve when history is re-read without re-running retrieval.

### Infrastructure change required

`docker-compose*.yml` currently uses `postgres:16-alpine`, which **does not ship
pgvector**. Projects memory requires swapping to `pgvector/pgvector:pg16` (or installing
the extension), plus a migration running `CREATE EXTENSION IF NOT EXISTS vector`.
This is a prerequisite, not an optional optimization.

## 4. Embeddings: a new engine port

`research_engine` must not learn about Postgres or the host ([13_Local_First_Architecture.md](13_Local_First_Architecture.md) §2),
so embeddings are declared as a port in `research_engine/ports.py`:

```python
@runtime_checkable
class Embeddings(Protocol):
    @property
    def model_id(self) -> str: ...
    @property
    def dimensions(self) -> int: ...
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
```

**[changed] `model_id` and `dimensions` are part of the contract**, not just `embed`.
Retrieval has to filter on the model that produced a vector (below), so the port has to
be able to say which model it is.

**[changed] It is passed explicitly, not installed as a ContextVar** — the sketch said
"injected alongside `event_sink` / `cache` / `provider_keys`". Those two are ambient
because graph *nodes* reach for them mid-run, so there is nowhere to pass them. Nothing
in the graph embeds: ingestion happens in the host after approval (§2) and retrieval is
a SQL query in the host (§5). An ambient holder for a port the engine never reads would
be indirection with no reader, so hosts construct an adapter and hand it to the two
functions that use it. The `Embeddings` protocol still lives in the engine, because the
*shape* is the engine's contract even when the call sites are not.

| Deployment | Implementation |
|---|---|
| Self-host / desktop | Ollama `nomic-embed-text` — local, free, no egress (768-dim) |
| Cloud / BYOK | Google `text-embedding-004`, or OpenAI `text-embedding-3-small` truncated to 768 |

`EMBEDDINGS_PROVIDER` defaults to `auto`: local Ollama when one is reachable with an
embedding model installed, else whichever hosted provider has a key — the user's BYOK key
first, exactly as their research ran. `none` disables memory rather than degrading it.

**Dimension is not interchangeable, and equal width is not equal meaning.** Every
supported provider is configured to 768 so switching one is a *re-index* rather than a
migration — but vectors from different models are not comparable at any width, so
`memory_chunks.embedding_model` records what produced each row and retrieval filters on
it. Chunks written by a retired model become invisible rather than silently mis-ranked,
and `memory/status` reports them as `stale_models` so the gap is legible.

**The absent case fails closed.** `research_engine/embeddings.py` supplies `NoEmbeddings`,
which raises `EmbeddingsUnavailable` rather than returning empty vectors. A no-op would
write nothing, match nothing, and surface weeks later as "memory doesn't work" with no
error anywhere — indistinguishable from an empty corpus. Callers decide what the failure
means: ingestion logs it and leaves the report un-indexed (the run already succeeded and
must not be failed retroactively), chat returns 503 rather than answering ungrounded.

### Chunking

`research_engine/chunking.py`, pure text in and out, so the server and the desktop build
chunk identically. Splits on Markdown structure rather than a character count, carries the
nearest heading into continuation chunks, and overlaps by a sentence. ~1200 characters
(≈300 tokens) per chunk, and short sections pack together rather than sharding at every
heading — each chunk is an embedding call, which is spend against the docs/12 ceiling.
Deterministic, which is what makes the unique index above an idempotency guarantee.

This is where local-LLM support and Projects reinforce each other: a fully local
deployment can do private retrieval with zero cost and zero egress.

## 5. Retrieval & isolation

**Isolation is a SQL boundary, never a prompt instruction.** Every retrieval is filtered
`WHERE project_id = :project_id` (plus the user's ownership check) before anything
reaches a model. A prompt-level "only use Project X" instruction is not a security
control and must not be treated as one ([06_Security.md](../engineering/06_Security.md) §4).

Chat turn flow:

1. Embed the user's message (one call).
2. Top-k nearest `memory_chunks` **within this project**, k = 8, filtered by
   `embedding_model` as well as `project_id`.
3. Build the prompt: system rules + retrieved chunks wrapped in
   `<untrusted_web_content>` framing (they originate from the web) + thread history
   as proper `AIMessage`/`HumanMessage` roles.
4. Answer must cite retrieved chunks as `[R1]`, `[R2]` → resolved to
   *report title + date + link*, and through the report to its original sources.
5. A claim with no resolvable citation renders with the existing ⚠ "unverified" chip
   ([07_UIUX_Guidelines.md](../product/07_UIUX_Guidelines.md) §5).

**[changed] The relevance cutoff is deliberately loose.** `MAX_COSINE_DISTANCE = 1.0`
drops only results that are worse than orthogonal. A tighter threshold would encode a
guess about what "relevant" means, and picking a number without a real model to measure
against is precisely the unfalsifiable metric [12_Launch_Plan.md](../product/12_Launch_Plan.md) §7
rules out. Retrieval therefore always returns its nearest matches, and rule 2 of
`PROJECT_CHAT_PROMPT` carries the weight: the excerpts' presence is explicitly not
evidence that they are relevant, and "this project's research doesn't cover that" is the
correct answer. Tightening this is future tuning, once there are real measurements.

**[unmeasured]** Whether a real model obeys that instruction reliably — refusing when the
excerpts do not support an answer, and citing accurately when they do — is a model-quality
property. The fake LLM in CI cannot demonstrate it. Everything *handed to* the model and
everything done *with its output* is tested (§9); the model's own behaviour needs an eval
run against a real model, which is blocked on the same working-model problem as the rest
of the eval harness.

Citations are computed from what was retrieved — a fact — then narrowed at persist time to
the markers the answer actually used. An unused excerpt is not a citation, and listing it
as one would be the sources theatre the ⚠ chip exists to prevent.

### Prompt-injection note

Memory persists attacker-influenced web text indefinitely, so injected content can
resurface long after the run that ingested it. Retrieved chunks therefore inherit the
untrusted-content framing unconditionally, and cross-project retrieval (§6) widens that
blast radius — which is why it is opt-in and visible.

## 6. Cross-project chat **[PLANNED — later phase]**

A thread may be attached to more than one project via `chat_thread_projects(thread_id,
project_id)`. Requirements, all non-negotiable:

- **Explicit opt-in per thread.** Never a default, never inferred.
- **Visible scope indicator** in the UI listing exactly which projects are readable.
- **Audit row** when scope changes, reusing `audit_log`.
- Retrieval filter becomes `project_id IN (:scoped_ids)` — still SQL, still server-side.

Isolation is the default; joining projects is a deliberate act the user can see.

## 7. Migration & compatibility

- Create one `General` project per existing user; backfill every existing session into
  it. `sessions.project_id` becomes NOT NULL only after backfill.
- Legacy per-report chat (`/research/{id}/chat`) keeps working unchanged — those messages
  keep `session_id` and simply have no `thread_id`.
- No behavioral change to the pipeline, the gate, or exports.

## 8. API sketch

| Endpoint | Purpose |
|---|---|
| `GET/POST /projects`, `PATCH/DELETE /projects/{id}` | CRUD; delete cascades sessions/threads/memory |
| `GET /research?project_id=` | Project-scoped history |
| `GET/POST /projects/{id}/threads` | List/create chat threads |
| `DELETE /threads/{id}` | Delete a thread; messages cascade |
| `GET/POST /threads/{id}/messages` | History; POST streams SSE like existing chat |
| `GET /projects/{id}/memory/status` | Chunk count, last ingest, embedding model — makes memory legible rather than magic |

`memory/status` also returns `pending_reports` (approved minus indexed) and
`stale_models`. Those are the two ways memory can be quietly incomplete — an ingestion
that failed, and chunks written by a model no longer configured — and a user cannot
otherwise distinguish either from "chat has nothing on that". `pending_reports` is derived
rather than stored, so it needs no status column to keep in sync and falls on its own
after a re-index.

The POST stream sends `citations` on the `connected` event, before the first token: they
describe what was retrieved, which is settled the moment the query runs, so chips render
as the answer streams.

## 9. Definition of Done

Asserted in `backend/tests/test_project_memory.py` against a real Postgres with pgvector
— these are properties *of the database*, and a mocked query would prove only that the
mock behaves. The suite skips with a stated reason when no such database is present; CI
always has one (both `postgres` services pin `pgvector/pgvector:pg16`).

- [x] A project's chat answers using a report approved in that project, and every claim
      carries a citation resolving to that report and its sources.
      *Mechanically verified*: retrieval returns the right chunks, `[R{n}]` markers resolve
      to their source session with the excerpt, unresolvable markers render ⚠, and unused
      excerpts are not persisted as citations. **[unmeasured]**: whether a real model
      writes the markers correctly — see §5.
- [x] A question about a report in a *different* project returns nothing from this one —
      `test_cross_project_isolation`, covering two projects owned by the **same user**
      (the case a per-user check alone waves through), plus a cross-account variant.
- [x] Rejected/draft reports are provably absent from retrieval —
      `test_rejected_draft_is_provably_absent_from_retrieval` asserts the strong form: a
      question whose answer exists only in a rejected draft retrieves nothing.
- [x] Deleting a project deletes its memory (no orphan vectors) — asserted at the DB
      level, with session-scoped deletion covered separately.
- [x] History and chat are scoped per project in the UI — `/chat` reads the active project
      from the same context the dashboard and history use.
- [x] Existing sessions still open, chat, and export after migration — legacy `session_id`
      messages and new `thread_id` messages coexist, and the one-parent CHECK is asserted.

Also covered: ingestion is idempotent (approving twice does not double the corpus or the
bill), a forced re-index replaces rather than accumulates, and vectors from a different
embedding model refuse to rank against the current one.
