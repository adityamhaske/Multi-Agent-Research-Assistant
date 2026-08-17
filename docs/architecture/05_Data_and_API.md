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
| status | enum(`PENDING`,`RUNNING`,`AWAITING_PLAN`,`AWAITING_APPROVAL`,`COMPLETED`,`FAILED`) NOT NULL | server_default `PENDING`. `AWAITING_PLAN` is the design gate (migration 0013 `ALTER TYPE ... ADD VALUE`); it is a separate value from `AWAITING_APPROVAL` because the two gates resume with different payloads |
| research_depth | text NOT NULL CHECK in (`fast`,`balanced`,`comprehensive`) | |
| draft_report | text NULL | |
| final_report | text NULL | |
| sources | JSONB NULL | array of `{index, url, title, snippet}` — the citation table rendered by the UI |
| error_message | text NULL | |
| total_cost_usd | numeric(10,6) NOT NULL default 0 | **never Float** |
| total_tokens_input / total_tokens_output | bigint NOT NULL default 0 | |
| elapsed_seconds | numeric(10,2) NULL | |
| rework_count | int NOT NULL default 0 | |
| citation_resolution_rate | numeric(5,4) NULL | Share of the report's in-text `[n]` markers that resolve to a real source, computed once at finalize by `research_engine/citation_rate.py`. **NULL means *not measured*** — no citable claims, or a run older than the column — and must never render as `0.0`, which means every marker failed. `evals/metrics.py::citation_stats` delegates to the same function so a published number and a displayed number cannot disagree |
| plan_json / outline_json | JSONB NULL | The design the reviewer **approved** (`{tasks: [...]}` / `{sections: [...]}`), not the planner's raw proposal — written over at the gate, same reasoning as `model_routing` snapshotting what actually ran |
| plan_approved_at | timestamptz NULL | Null while `AWAITING_PLAN`; stamped by `POST /{id}/plan` |
| skip_plan_gate | bool NOT NULL default false | Both start endpoints always set this explicitly from the request, whose own default is the opposite (`true`, skip) so an un-updated caller is unaffected |
| topic_seeds / outline_template | JSONB NULL / varchar(64) NULL | What was asked for at start time, as opposed to what was decided at the gate. Persisted because `RunConfig` is rebuilt from this row on every resume |
| created_at / updated_at | timestamptz | |

Indexes: `(user_id, created_at DESC)` composite (history query), `status`.

### agent_logs  — durable event stream (SSE replay source)
| Column | Type | Notes |
|---|---|---|
| id | bigserial PK | doubles as SSE `Last-Event-ID` |
| session_id | UUID FK sessions ON DELETE CASCADE | |
| event_type | text NOT NULL | `agent_log`, `PLAN_READY`, `HITL_READY`, `COMPLETED`, `FAILED` |
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
| `POST /research` | `{query (10..2000 chars), depth, …, skip_plan_gate=true, topic_seeds=[], outline_template=null}` | 202 `{session_id, status}` |
| `GET /research` | `?page&limit&status` | paginated slim list — **no report bodies**; `message_count` via SQL count |
| `GET /research/{id}` | — | full session incl. draft/final report + sources |
| `GET /research/{id}/stream` | SSE | replay persisted logs (after `Last-Event-ID` if given), then live tail; closes after terminal event |
| `GET /research/outline-templates` | — | the four report structures, served from `research_engine/outlines.py` so the picker previews what the synthesizer is handed. Declared **before** `/{id}` — that route parses its segment as a UUID and would 422 this path |
| `GET /research/{id}/plan` | — | `{tasks, outline, approved_at}`; **404** when `plan_json` is null (the run never used the gate) rather than an empty plan — unmeasured is not zero |
| `POST /research/{id}/plan` | `{tasks?: [...], outline?: [...]}` | 200 the stored plan; 409 unless `AWAITING_PLAN`; 422 if nothing is left included. Absent `tasks` means *unedited*, `[]` means "excluded everything". Writes `audit_log` (`plan_approved`) then enqueues `resume_plan_gate` |
| `POST /research/{id}/approve` | `{approved: bool, feedback: str|null}` | 200; 409 unless `AWAITING_APPROVAL`; writes `audit_log`; enqueues resume |
| `GET /research/{id}/export.md` / `export.pdf` | — | file download (COMPLETED only) |

### Chat (COMPLETED sessions only)
| Endpoint | Req | Resp |
|---|---|---|
| `GET /research/{id}/chat` | — | message list |

### Corpus documents
`GET /projects/{id}/documents/{doc_id}/download` serves the original uploaded bytes.
**PDF is served `inline`; every other kind is `attachment`** (`app/api/v1/corpus.py::
download_headers`). That narrowing is deliberate and is the only exception to "an
uploaded document never renders in this origin": `application/pdf` + `nosniff` goes to
the browser's own sandboxed viewer, and in-place PDF preview cannot work any other way.
Markdown, text and HTML are previewed without this route — the client `fetch`es the bytes
and renders them itself, and `fetch` ignores `Content-Disposition`, so `attachment` costs
the preview nothing.

CSP differs with it: PDF gets `frame-ancestors 'self'` plus an explicit
`X-Frame-Options: SAMEORIGIN` (the security middleware `setdefault`s `DENY`, so the route
must state its own); everything else keeps `'none'` and adds `sandbox`. Accepted kinds
are `pdf`, `html`, `md`, `txt` — `research_engine/documents.py::kind_for` is the one
allowlist, and its rejection message must be edited in the same change as the set.
| `POST /research/{id}/chat` | `{message (1..4000 chars), scope="report"}` | SSE stream: `connected{scope, sources, notes}` → `chunk`* → `done{message_id}`; chat-specific rate limit. 400 when `scope=corpus` and the embedder is remote |

**Retrieval scope** (docs/07 §2, Phase 5; req 8). `scope` is `report` \| `corpus` \| `web`
\| `everything`, resolved by `app/services/chat_scope.py` — one module so the report chat
and the project chat cannot mean different things by the same word. `report` is the
default and is today's behaviour on both surfaces, so an un-updated client is unaffected.

`corpus` promises **no retrieval egress**, which is narrower than "no network calls" and
deliberately so: no web retriever runs, and `CorpusStore.search` refuses to embed the
question at all when the configured embedder is remote (the existing
`_require_local_embedder_in_corpus_mode` guard, armed here by installing
`corpus_mode=True` rather than reimplemented). The *answer* is still written by a model,
which is off-machine unless chat is routed to a local one — the UI copy says exactly
this, and `tests/test_chat_scope.py` asserts exactly this. Claiming the broader thing is
how `test_corpus_egress.py` stayed green while every corpus query egressed.

Web-scoped answers return the sources they found on the `connected` frame, numbered from
1, so their `[n]` markers resolve. A retriever failure arrives as a `notes` entry and is
stated to the model as a gap — never swallowed into an empty grounding block the model
would paper over.

**Desktop:** the sidecar implements report chat with the same scope contract. Project
chat (`/threads`) stays absent — project memory is pgvector-only. Follow-up chat is server-only today.

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

// PLAN_READY — the design gate. `cost_usd` is 0.00 on an ordinary run because the gate
// sits before the executor; it is reported rather than assumed, so a resumed run that
// reaches here shows a real number instead of a hardcoded zero.
{"type": "PLAN_READY", "id": 128, "ts": "…",
 "data": {"task_count": 5, "outline_section_count": 4, "cost_usd": 0.0}}

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
