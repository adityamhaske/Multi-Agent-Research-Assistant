# Data model

Schema truth lives in the Alembic migrations under `backend/alembic/versions/`. This page
describes what those tables hold and why. The HTTP surface is documented separately in the
[API reference](../reference/34-api.md).

```
users
 ├── refresh_tokens
 └── projects
      ├── sessions ──┬── agent_logs
      │              ├── chat_messages
      │              ├── audit_log
      │              └── memory_chunks
      ├── chat_threads ── chat_messages
      └── (corpus: a SQLite file per project, outside Postgres)
```

## users

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `email` | varchar(255) UNIQUE NOT NULL | |
| `hashed_pw` | varchar(255) NOT NULL | bcrypt, cost 12 |
| `is_active` | bool NOT NULL default true | |
| `display_name`, `avatar_url` | varchar(80) / text, nullable | Profile. Avatar URLs must be `http(s)` — they render in an `<img>` |
| `api_key_encrypted` | text NULL | Fernet ciphertext of a user's own provider key. Never returned by any endpoint |
| `api_key_provider` | varchar(20) NULL | `google` \| `anthropic` \| `openai` \| `openrouter` \| `custom` |
| `api_key_base_url` | text NULL | Only for `custom` |
| `api_key_hint` | varchar(16) NULL | Display-only tail, e.g. `…aB3d` |
| `api_key_set_at` | timestamptz NULL | |
| `monthly_token_limit` | integer NOT NULL default 0 | **0 = unlimited** |
| `model_routing` | JSONB NULL | Per-role `provider:model`. NULL = use the deployment default |
| `preferences` | JSONB NULL | Free-form, validated shape-side. NULL = every preference unset |
| `created_at` | timestamptz | |

`preferences` is JSON rather than a column per setting, so a new knob is not a migration.
NULL means "use the default" — the same convention `model_routing` uses.

## sessions

One research run.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | Also the LangGraph checkpoint `thread_id` |
| `user_id` | UUID FK users ON DELETE CASCADE | |
| `project_id` | UUID FK projects ON DELETE CASCADE, NOT NULL | Backfilled into a per-user "General" project before being made NOT NULL |
| `prompt` | text NOT NULL | |
| `status` | enum | `PENDING`, `RUNNING`, `AWAITING_PLAN`, `AWAITING_APPROVAL`, `COMPLETED`, `FAILED` |
| `research_depth` | varchar(20) NOT NULL | `fast` \| `balanced` \| `comprehensive` |
| `draft_report`, `final_report` | text NULL | |
| `sources` | JSONB NULL | `[{index, url, title, snippet, snippets[]}]` — the citation table the UI renders |
| `error_message` | text NULL | |
| `total_cost_usd` | numeric(10,6) NOT NULL default 0 | **Numeric, never float** |
| `total_tokens_input` / `total_tokens_output` | integer NOT NULL default 0 | |
| `elapsed_seconds` | numeric(10,2) NULL | |
| `rework_count` | integer NOT NULL default 0 | |
| `archived_at` | timestamptz NULL | A timestamp rather than a boolean, so "when did this leave the list" is answerable |
| `model_routing` | JSONB NULL | What actually ran, snapshotted — not re-read from a preference that may since have changed |
| `citation_resolution_rate` | numeric(5,4) NULL | **NULL means *not measured***, never `0.0` |
| `corpus_mode` | bool NOT NULL default false | |
| `demo` | bool NOT NULL default false | Scripted models and fixture sources. Persisted so every export can stamp the artifact |
| `plan_json` / `outline_json` | JSONB NULL | The design the reviewer **approved**, not the planner's proposal |
| `plan_approved_at` | timestamptz NULL | Null while `AWAITING_PLAN` |
| `skip_plan_gate` | bool NOT NULL default false | Both start endpoints always set this explicitly |
| `topic_seeds` / `outline_template` | JSONB / varchar(64) NULL | What was asked for at start time, as opposed to what was decided at the gate. Persisted because the run config is rebuilt from this row on every resume |
| `created_at` / `updated_at` | timestamptz | |

Indexes: `user_id`, `project_id`, `status`.

Two nullable columns carry the same rule, and it is the rule this codebase is built around:
**`citation_resolution_rate` and `elapsed_seconds` are NULL when unmeasured.** `0.0` in the
first would mean "every marker points at nothing", which is the opposite finding. Storing
the two as one value is the bug the project exists to refuse.

## agent_logs

The durable event stream, and the source the SSE endpoint replays from.

| Column | Type | Notes |
|---|---|---|
| `id` | bigserial PK | Doubles as the SSE `Last-Event-ID` cursor |
| `session_id` | UUID FK sessions ON DELETE CASCADE | |
| `event_type` | varchar(40) NOT NULL | `agent_log`, `PLAN_READY`, `HITL_READY`, `COMPLETED`, `FAILED` |
| `agent_name` | varchar(50) NULL | planner / executor / critic / synthesizer / system |
| `payload` | JSONB NOT NULL | The event body |
| `created_at` | timestamptz NOT NULL | |

Events are written here **first** and published to Redis second. That ordering is what makes
the live feed lossless.

## audit_log

The compliance trail. One row per human decision.

| Column | Type | Notes |
|---|---|---|
| `id` | bigserial PK | |
| `session_id` | UUID FK sessions | |
| `user_id` | UUID FK users | |
| `action` | text NOT NULL | `approved`, `rework_requested`, `plan_approved` |
| `feedback` | text NULL | Verbatim rework feedback |
| `draft_hash` | text NOT NULL | SHA-256 of what was reviewed |
| `created_at` | timestamptz | |

`draft_hash` is what lets a bundle prove an approval applies to *that* report. For
`plan_approved` it hashes the approved tasks and outline instead, so the design decision is
carried in the same chain.

The row is written **before** the resume is queued, so the record of what a human chose
survives a worker that dies mid-run.

## projects

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK users ON DELETE CASCADE | |
| `name` | varchar(120) NOT NULL | |
| `description` | text NULL | |
| `archived_at` | timestamptz NULL | Archive hides; delete removes |
| `created_at` / `updated_at` | timestamptz | |

`UNIQUE (user_id, lower(name))` — "Thesis" and "thesis" as separate projects is a UI trap,
not a feature.

## chat_threads and chat_messages

| `chat_threads` | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `project_id` | UUID FK projects ON DELETE CASCADE | |
| `title` | varchar(200) NOT NULL | Derived from the first message |
| `created_at`, `last_message_at` | timestamptz | Ordering key — "recent" means last *used* |

| `chat_messages` | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `session_id` | UUID FK sessions ON DELETE CASCADE, **nullable** | Set for per-report chat |
| `thread_id` | UUID FK chat_threads ON DELETE CASCADE, nullable | Set for project chat |
| `role` | text NOT NULL | `user` \| `assistant` |
| `content` | text NOT NULL | |
| `citations` | JSONB | Resolved `[R{n}]` markers on a thread reply |
| `created_at` | timestamptz | |

`CHECK ((session_id IS NOT NULL) <> (thread_id IS NOT NULL))` — a message belongs to a
report **or** a thread, never both and never neither. Two nullable parents would permit a
row that appears in no history at all, whose first symptom is a user's question vanishing.

## memory_chunks

Embedded slices of approved reports. Requires **pgvector**.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `project_id` | UUID FK projects ON DELETE CASCADE | The isolation boundary |
| `source_session_id` | UUID FK sessions ON DELETE CASCADE | Resolves `[R{n}]` back to its report |
| `chunk_index` | integer NOT NULL | |
| `text` | text NOT NULL | |
| `embedding` | `vector(768)` NOT NULL | |
| `embedding_model` | varchar(120) NOT NULL | Equal width is not equal meaning |
| `created_at` | timestamptz | |

Indexes: `project_id`, `source_session_id`, `UNIQUE (source_session_id, chunk_index)`, and
HNSW on `embedding` with `vector_cosine_ops` — matching the operator retrieval uses.

Rows are written from exactly one place: the `COMPLETED` transition, reachable only through
the human approval gate. The unique index makes re-ingestion idempotent rather than
duplicating the corpus.

**Postgres must be a pgvector image**, not stock. Migration 0006 enables the extension and
0007 creates the vector column, so a stock image fails `alembic upgrade head` outright.

## refresh_tokens

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | The token's jti |
| `user_id` | UUID FK users ON DELETE CASCADE | |
| `token_hash` | text NOT NULL | SHA-256 of the token; the token itself is never stored |
| `expires_at` | timestamptz NOT NULL | |
| `revoked_at` | timestamptz NULL | Rotation and revocation |

## Corpus storage

Uploaded documents do **not** live in Postgres. Each project gets a SQLite file under the
configured `CORPUS_DIR`, holding the document bytes, extracted text spans, and their
embeddings.

That keeps the corpus portable and makes the desktop build's story identical apart from one
detail: on desktop it is a single `corpus.sqlite` for the whole app rather than one file per
project.

`CORPUS_DIR` defaults to the relative path `data/corpus`, resolved against the backend
package root rather than the process working directory — otherwise running from the
repository root and from `backend/` would create two different corpus roots, and a document
uploaded through one would simply not be there for the other.

## LangGraph checkpoints

Owned by `langgraph-checkpoint-postgres`, keyed by `thread_id` (the session id), in tables
this application does not define and never hand-edits.

They are dropped explicitly when a session is deleted. Cascades cannot reach them, and
without that step "delete" would leave the full agent state — including fetched page
content — behind.

## Migration policy

- **Alembic is the only schema writer.** No `create_all` in application code. It once masked
  an empty migration, and the whole class of "works locally, missing in production" follows
  from that.
- Autogenerate runs against a scratch database built from `alembic upgrade head` only.
- `compare_type` and `compare_server_default` are on; every model module is imported in
  `env.py`.
- Every migration has a real `downgrade()`, and the round-trip is exercised in CI.
- Migrations are append-only once merged. Fixing a merged migration means writing a new one.

The desktop build reads the ORM models directly via `create_all` plus a startup column sync,
so **a schema change needs both** a migration and the ORM model updated — they are two homes
for one contract.
