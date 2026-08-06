# 14. Projects & Project Memory

> **[PLANNED]** Design contract for project containers, project-scoped chat, and
> retrieval over approved research. Written before implementation per
> [00_INDEX.md](../00_INDEX.md). Nothing here is built yet; each section states the
> milestone that delivers it.

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
| `chat_messages` | **+ thread_id** FK | `session_id` retained nullable so legacy per-report chat keeps working |
| `memory_chunks` | id, project_id FK, source_session_id FK, chunk_index, text, `embedding vector(768)`, created_at | Written only on approval; `ON DELETE CASCADE` from both project and session |

Indexes: `sessions(project_id, created_at DESC)`, `chat_threads(project_id, last_message_at DESC)`,
`memory_chunks(project_id)` + an HNSW/IVFFlat index on `embedding`.

### Infrastructure change required

`docker-compose*.yml` currently uses `postgres:16-alpine`, which **does not ship
pgvector**. Projects memory requires swapping to `pgvector/pgvector:pg16` (or installing
the extension), plus a migration running `CREATE EXTENSION IF NOT EXISTS vector`.
This is a prerequisite, not an optional optimization.

## 4. Embeddings: a new engine port

`research_engine` must not learn about Postgres or the host ([13_Local_First_Architecture.md](13_Local_First_Architecture.md) §2),
so embeddings arrive the same way every other capability does — as an injected port
alongside `event_sink` / `cache` / `provider_keys`:

```python
class EmbeddingsPort(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
```

| Deployment | Implementation |
|---|---|
| Self-host / desktop | Ollama `nomic-embed-text` — local, free, no egress (768-dim) |
| Cloud / BYOK | Provider embeddings (Google/OpenAI), dimension recorded per chunk |

**Dimension is not interchangeable.** `memory_chunks` stores the model that produced each
vector; changing embedding models requires a re-index, and the retrieval query must never
mix dimensions. Store `embedding_model` on the row and filter by it.

This is where local-LLM support and Projects reinforce each other: a fully local
deployment can do private retrieval with zero cost and zero egress.

## 5. Retrieval & isolation

**Isolation is a SQL boundary, never a prompt instruction.** Every retrieval is filtered
`WHERE project_id = :project_id` (plus the user's ownership check) before anything
reaches a model. A prompt-level "only use Project X" instruction is not a security
control and must not be treated as one ([06_Security.md](../engineering/06_Security.md) §4).

Chat turn flow:

1. Embed the user's message.
2. Top-k nearest `memory_chunks` **within this project** (k tuned; start 8).
3. Build the prompt: system rules + retrieved chunks wrapped in
   `<untrusted_web_content>` framing (they originate from the web) + thread history
   as proper `AIMessage`/`HumanMessage` roles.
4. Answer must cite retrieved chunks as `[R1]`, `[R2]` → resolved to
   *report title + date + link*, and through the report to its original sources.
5. A claim with no resolvable citation renders with the existing ⚠ "unverified" chip
   ([07_UIUX_Guidelines.md](../product/07_UIUX_Guidelines.md) §5).

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
| `GET /projects/{id}/sessions` | Project-scoped history |
| `GET/POST /projects/{id}/threads` | List/create chat threads |
| `GET/POST /threads/{id}/messages` | History; POST streams SSE like existing chat |
| `GET /projects/{id}/memory/status` | Chunk count, last ingest, embedding model — makes memory legible rather than magic |

## 9. Definition of Done

- [ ] A project's chat answers a question using a report approved in that project, and
      every claim carries a citation resolving to that report and its sources.
- [ ] A question about a report in a *different* project returns "not in this project's
      knowledge" — verified by an automated isolation test, not by inspection.
- [ ] Rejected/draft reports are provably absent from retrieval.
- [ ] Deleting a project deletes its memory (no orphan vectors).
- [ ] History and chat are scoped per project in the UI.
- [ ] Existing sessions still open, chat, and export after migration.
