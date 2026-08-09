# 05. Data Models & API Contracts

> Schema truth lives in Alembic migrations. This doc describes the intended design;
> if they diverge, fix the migration or this doc in the same PR.

## 1. Database schema (PostgreSQL 16)

### users
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | `gen_random_uuid()` server default |
| email | citext UNIQUE NOT NULL | |
| hashed_pw | text NOT NULL | bcrypt |
| is_active | bool NOT NULL server_default true | |
| created_at | timestamptz NOT NULL server_default now() | |

### sessions
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK users ON DELETE CASCADE, NOT NULL | |
| prompt | text NOT NULL | |
| status | enum(`PENDING`,`RUNNING`,`AWAITING_APPROVAL`,`COMPLETED`,`FAILED`) NOT NULL | server_default `PENDING` |
| research_depth | text NOT NULL CHECK in (`fast`,`balanced`,`comprehensive`) | |
| draft_report | text NULL | |
| final_report | text NULL | |
| sources | JSONB NULL | array of `{index, url, title, snippet}` — the citation table rendered by the UI |
| error_message | text NULL | |
| total_cost_usd | numeric(10,6) NOT NULL default 0 | **never Float** |
| total_tokens_input / total_tokens_output | bigint NOT NULL default 0 | |
| elapsed_seconds | numeric(10,2) NULL | |
| rework_count | int NOT NULL default 0 | |
| created_at / updated_at | timestamptz | |

Indexes: `(user_id, created_at DESC)` composite (history query), `status`.

### agent_logs  — durable event stream (SSE replay source)
| Column | Type | Notes |
|---|---|---|
| id | bigserial PK | doubles as SSE `Last-Event-ID` |
| session_id | UUID FK sessions ON DELETE CASCADE | |
| event_type | text NOT NULL | `agent_log`, `HITL_READY`, `COMPLETED`, `FAILED` |
| agent_name | text NULL | planner/executor/critic/synthesizer/system |
| payload | JSONB NOT NULL | event body (schema §4) |
| created_at | timestamptz NOT NULL server_default now() | |

Index: `(session_id, id)`.

### chat_messages
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| session_id | UUID FK sessions ON DELETE CASCADE, **nullable** | Set for per-report chat |
| thread_id | UUID FK chat_threads ON DELETE CASCADE, nullable | Set for project chat (0008) |
| role | text NOT NULL CHECK in (`user`,`assistant`) | |
| content | text NOT NULL | |
| citations | JSONB | Resolved `[R{n}]` markers on a thread reply |
| created_at | timestamptz | |

Indexes: `(session_id, created_at)`, `(thread_id, created_at)`.

`CHECK ((session_id IS NOT NULL) <> (thread_id IS NOT NULL))` — a message belongs to a
report **or** a thread, never both and never neither. Two nullable parents would permit a
row that appears in no history at all, whose first symptom is a user's question vanishing.

### projects  — the container research lives in (docs/14 §3)
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK users ON DELETE CASCADE | |
| name | varchar(120) NOT NULL | |
| description | text | |
| archived_at | timestamptz | Archive hides; delete removes |
| created_at / updated_at | timestamptz | |

`UNIQUE (user_id, lower(name))` — "Thesis" and "thesis" as separate projects is a UI trap,
not a feature. Migration 0005 backfilled existing sessions into a per-user `General`
project before making `sessions.project_id` NOT NULL.

### chat_threads  — project-scoped conversations (docs/14 §3)
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK projects ON DELETE CASCADE | |
| title | varchar(200) NOT NULL | Derived from the first message |
| created_at | timestamptz | |
| last_message_at | timestamptz | Ordering key — "recent" means last *used* |

Index: `(project_id, last_message_at DESC)`.

### memory_chunks  — embedded slices of approved reports (docs/14 §2)
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK projects ON DELETE CASCADE | The isolation boundary |
| source_session_id | UUID FK sessions ON DELETE CASCADE | Resolves `[R{n}]` back to its report |
| chunk_index | integer NOT NULL | |
| text | text NOT NULL | |
| embedding | `vector(768)` NOT NULL | Requires pgvector (0006) |
| embedding_model | varchar(120) NOT NULL | Equal width is not equal meaning |
| created_at | timestamptz | |

Indexes: `(project_id)`, `(source_session_id)`, `UNIQUE (source_session_id, chunk_index)`,
and HNSW on `embedding` with `vector_cosine_ops`. Rows are written from exactly one place
— the COMPLETED transition in `pipeline_runner._persist_outcome`, reachable only through
the human approval gate. The unique index makes re-ingestion idempotent rather than
duplicating the corpus.

**Requires `pgvector/pgvector:pgNN`, not a stock postgres image** — every compose file and
both CI service blocks are pinned accordingly.

### audit_log  — the compliance trail
| Column | Type | Notes |
|---|---|---|
| id | bigserial PK | |
| session_id | UUID FK sessions | |
| user_id | UUID FK users | |
| action | text NOT NULL | `approved` / `rework_requested` / `abandoned` |
| feedback | text NULL | verbatim rework feedback |
| draft_hash | text NOT NULL | sha256 of the draft that was reviewed |
| created_at | timestamptz | |

### refresh_tokens
| Column | Type | Notes |
|---|---|---|
| id | UUID PK (jti) | |
| user_id | UUID FK users ON DELETE CASCADE | |
| token_hash | text NOT NULL | sha256 of the token |
| expires_at | timestamptz NOT NULL | |
| revoked_at | timestamptz NULL | rotation + revocation |

Plus: LangGraph checkpoint tables owned by `langgraph-checkpoint-postgres` (created by
its own setup migration; never hand-edited).

## 2. Migration policy

- Alembic is the **only** schema writer. No `create_all` in app code.
- Autogenerate runs against a scratch DB built from `alembic upgrade head` only.
- `compare_type=True`, `compare_server_default=True` in `env.py`; every model module
  explicitly imported there.
- Every migration has a real `downgrade()`. Empty migrations are CI-rejected
  (a guard test asserts upgrade→downgrade→upgrade round-trips).

## 3. REST API (`/api/v1`)

All endpoints cookie-authed unless noted. Errors follow RFC-7807-style
`{detail, code}` bodies. Full request/response models are Pydantic schemas in
`app/schemas/`; OpenAPI at `/docs` (non-prod only).

### Auth
| Endpoint | Req | Resp | Notes |
|---|---|---|---|
| `POST /auth/register` | `{email, password}` | 201 neutral message | Rate-limited; neutral response (no account enumeration) |
| `POST /auth/login` | `{email, password}` | 200, sets `access` (15 min) + `refresh` (14 d) httpOnly cookies | Per-IP + per-account rate limits |
| `POST /auth/refresh` | refresh cookie | rotates both cookies | Rotation invalidates the used refresh token |
| `POST /auth/logout` | — | clears cookies, revokes refresh jti | |
| `GET /auth/me` | — | `{id, email, created_at}` | Frontend auth probe |

### Research
| Endpoint | Req | Resp |
|---|---|---|
| `POST /research` | `{query (10..2000 chars), depth}` | 202 `{session_id, status}` |
| `GET /research` | `?page&limit&status` | paginated slim list — **no report bodies**; `message_count` via SQL count |
| `GET /research/{id}` | — | full session incl. draft/final report + sources |
| `GET /research/{id}/stream` | SSE | replay persisted logs (after `Last-Event-ID` if given), then live tail; closes after terminal event |
| `POST /research/{id}/approve` | `{approved: bool, feedback: str|null}` | 200; 409 unless `AWAITING_APPROVAL`; writes `audit_log`; enqueues resume |
| `GET /research/{id}/export.md` / `export.pdf` | — | file download (COMPLETED only) |

### Chat (COMPLETED sessions only)
| Endpoint | Req | Resp |
|---|---|---|
| `GET /research/{id}/chat` | — | message list |
| `POST /research/{id}/chat` | `{message (1..4000 chars)}` | SSE stream: `chunk`* → `done{message_id}`; chat-specific rate limit |

### Projects & project chat (docs/14 §8)
| Endpoint | Req | Resp |
|---|---|---|
| `GET/POST /projects` | `{name, description?}` | list / 201; 409 on a case-insensitive duplicate name |
| `PATCH/DELETE /projects/{id}` | `{name?, description?, archived?}` | delete cascades sessions, threads and memory; 409 while a session is RUNNING |
| `GET/POST /projects/{id}/threads` | `{title?}` | thread list / 201 |
| `DELETE /threads/{id}` | — | 204; messages cascade |
| `GET /threads/{id}/messages` | — | message list with resolved citations |
| `POST /threads/{id}/messages` | `{message (1..4000 chars)}` | SSE: `connected{citations}` → `chunk`* → `done{message_id, citations}`; **503** when no embeddings provider is reachable |
| `GET /projects/{id}/memory/status` | — | chunk/report counts, current + stale embedding models, pending count |

`POST /threads/{id}/messages` sends citations on `connected`, before the first token:
they describe what was *retrieved*, which is settled when the query runs. It returns 503
rather than an ungrounded answer when embeddings are unavailable — this endpoint's
contract is that answers come from approved research.

## 4. SSE event contract

Every event: `id: <agent_logs.id>` line + `data: <json>` line.

```jsonc
// event_type: agent_log
{"type": "agent_log", "id": 123, "ts": "…", "agent": "executor",
 "message": "Searching: 'EU AI Act Article 14 obligations'",
 "detail": {"task_id": 2, "tool": "web_search"}}

// HITL_READY
{"type": "HITL_READY", "id": 130, "ts": "…",
 "data": {"word_count": 1240, "source_count": 9, "cost_usd": 0.18}}

// COMPLETED / FAILED
{"type": "COMPLETED", "id": 140, "ts": "…", "data": {"elapsed_s": 171.4, "cost_usd": 0.21}}
{"type": "FAILED",    "id": 141, "ts": "…", "data": {"reason": "Budget exceeded ($0.50)"}}
```

Chat streaming uses `{"type": "chunk", "text": …}` / `{"type": "done", "message_id": …}`
/ `{"type": "error", "detail": …}` — no `id:` lines (not replayable).

## 5. Data-layer rules

- Money: `numeric`, never float. Timestamps: `timestamptz`, server defaults.
- Relationships that rely on DB `ON DELETE CASCADE` set `passive_deletes=True`.
- List endpoints ship slim schemas; report bodies only on the detail endpoint.
- `sources` JSONB is written once by the finalizer and is the single source the UI
  renders citations from — the Markdown `[n]` markers must resolve against it.
