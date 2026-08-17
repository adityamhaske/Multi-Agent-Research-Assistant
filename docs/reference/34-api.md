# API reference

Base path `/api/v1`. Every endpoint requires authentication unless noted.

Authentication is the `access_token` httpOnly cookie, sent automatically by the browser
through the same-origin proxy. A `Bearer` header is also accepted for non-browser clients.

Interactive OpenAPI is served at `/docs` and `/redoc` — **disabled when
`ENVIRONMENT=production`**.

Errors are `{"detail": "..."}` with a conventional status code. Streaming endpoints are
documented in the [SSE protocol](35-sse.md).

---

## Health

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/health` | No | Liveness. `{"status": "ok", "version": "..."}` |
| `GET` | `/health/ready` | No | Readiness. `200` when database and Redis both answer, **`503`** otherwise with a per-check breakdown |

Both are outside `/api/v1`.

---

## Authentication

### `POST /auth/register`

`201`. Rate-limited per IP (5/hour).

```json
{ "email": "you@example.com", "password": "at least 12 chars" }
```

Returns a **neutral message either way**, so the endpoint cannot be used to enumerate
accounts. `422` if the password fails the policy.

### `POST /auth/login`

Sets the `access_token` (15 min, path `/`) and `refresh_token` (14 days, path
`/api/v1/auth`) cookies, both httpOnly.

Rate-limited per IP (20/min) and per account (5 failures / 15 min). `401` on bad
credentials, `403` if the account is deactivated, `429` when limited.

### `POST /auth/refresh`

Reads the refresh cookie, **rotates both cookies**. Reuse of an already-rotated token
revokes the whole family and returns `401` with both cookies cleared.

### `POST /auth/logout`

Revokes the refresh token server-side and clears both cookies.

### `GET /auth/me`

The current user. Never includes the stored provider key — only its provider, an
`api_key_hint` like `…aB3d`, and when it was set.

```json
{
  "id": "uuid", "email": "you@example.com", "is_active": true,
  "created_at": "...", "display_name": null, "avatar_url": null,
  "monthly_token_limit": 0,
  "api_key_provider": null, "api_key_base_url": null,
  "api_key_hint": null, "api_key_set_at": null,
  "connection_verdict": null,
  "preferences": { "retrieval_k": null, "min_sources_per_task": null,
                   "snippet_max_chars": null, "density": null }
}
```

### `PATCH /auth/me`

Updates `display_name`, `avatar_url`, `monthly_token_limit`, or `preferences`. Only fields
present in the body change.

**`preferences` is merged, never replaced** — a request from one settings section carries
only that section's fields, and overwriting would blank every other preference. Avatar URLs
must be `http(s)`; they render in an `<img>`.

### `POST /auth/me/password`

```json
{ "current_password": "...", "new_password": "..." }
```

Requires the current password — a stolen session cookie alone must not lock the owner out.
Revokes every refresh token for the account and re-issues for the caller. `403` if the
current password is wrong, `422` if the new one is unchanged or fails the policy.

### `PUT /auth/me/api-key`

```json
{ "provider": "anthropic", "api_key": "...", "api_base_url": null }
```

Providers: `google`, `anthropic`, `openai`, `openrouter`, `custom`. Stored encrypted; never
returned.

**Saving is testing.** After the key is committed it is probed against the provider, and the
response carries a `connection_verdict` of `ok`, `degraded`, or `failed` — three states,
because "the server rejected your key" needs a different fix from "nothing answered". A probe
failure never blocks the save. For `custom` in production, `api_base_url` is SSRF-validated
before storage.

### `DELETE /auth/me/api-key`

Removes the stored key; the deployment's server key applies again.

### `GET /auth/me/usage`

Token and cost usage for the current month, the rolling 7 days, and the last session, plus
`monthly_token_limit`, `limit_remaining` (`null` when unlimited) and `limit_reached`.

---

## Research

### `POST /research`

`202`. Starts a run.

```json
{
  "query": "10 to 2000 characters",
  "depth": "fast | balanced | comprehensive",
  "project_id": null,
  "model_routing": null,
  "corpus_mode": false,
  "demo": false,
  "topic_seeds": [],
  "outline_template": null,
  "skip_plan_gate": true
}
```

Only `query` is required. `project_id` omitted resolves to your default project.
`model_routing` omitted falls back to your saved preference, then the deployment default.

> **`skip_plan_gate` defaults to `true` here and that is deliberate.** The app's run form
> sends `false` explicitly, so a person using the product gets the design gate. This default
> governs a different population: a script posting the body it posted before the gate
> existed, for which an invisible pause it never polls past would be a breaking change.

Returns `{"session_id": "uuid", "status": "PENDING"}`.

`402` when the monthly token limit is already reached, checked **before** enqueueing so a
capped user gets a clear error rather than a session that fails mid-run. `422` on an
unroutable model. `429` when the research rate limit is enabled and hit.

### `GET /research`

Query parameters: `page` (default 1), `limit` (default 20, max 100), `archived` (default
`false`), `project_id`.

Returns `{sessions, total, page, limit}` with **slim** rows — no report bodies. Each row
carries `session_id`, `project_id`, `status`, `prompt`, `research_depth`, cost and token
totals, `elapsed_seconds`, `rework_count`, `created_at`, `archived_at`, `demo`,
`corpus_mode`, `citation_resolution_rate`, and `model_routing`.

`archived` selects one list or the other rather than merging them: archiving exists to get a
session *out* of the way, so the default view never includes archived sessions.

`citation_resolution_rate` is **`null` when not measured**, never `0.0`.

### `GET /research/{id}`

The full session: everything on the summary plus `draft_report`, `final_report`, `sources`,
`error_message`, and `updated_at`. `404` if it is not yours.

Each source is `{index, url, title, snippet, snippets[]}`. `snippets` holds **every** verbatim
snippet extracted from that source; `snippet` is the first, kept for older stored rows.

### `GET /research/{id}/stream`

Server-sent events. See the [SSE protocol](35-sse.md).

### `GET /research/outline-templates`

The report structures offered at the design gate, each with `id`, `label`, `summary`, and
`sections`. Served from the same module the synthesizer is handed, so the preview is what it
gets.

### `GET /research/{id}/plan`

The research design this run is working from:
`{session_id, status, tasks[], outline[], approved_at}`.

**`404` when the run has no plan**, rather than an empty one — a run that skipped the gate has
no design to show, and `{"tasks": []}` would read as "the planner proposed nothing".

### `POST /research/{id}/plan`

```json
{ "tasks": [ {"id": 1, "query": "...", "rationale": "...",
              "subtopics": [], "include": true, "source_hint": null} ],
  "outline": [ {"title": "...", "description": "..."} ] }
```

Both keys are optional, and **an absent key means *unedited*** — distinct from `[]`, which is
a reviewer who excluded everything. `include: false` drops a task from the run. Max 24 of
each.

Writes a `plan_approved` audit row hashing the approved design, then resumes. `409` unless
the session is `AWAITING_PLAN`. `422` if nothing is left included.

### `POST /research/{id}/approve`

```json
{ "approved": true, "feedback": null }
```

`feedback` is **required** when `approved` is `false`. Writes an audit row with the SHA-256
of the reviewed draft, then resumes: approve goes to the finalizer, reject re-runs synthesis.

`409` unless the session is `AWAITING_APPROVAL`, or when the rework limit (3) is reached.

### `POST /research/{id}/cancel`

Stops a `PENDING` or `RUNNING` run: the session becomes `FAILED` with "Research stopped by
user", a `FAILED` event is published, and a cancellation flag is set for the worker. `400`
from any other status.

### `POST /research/{id}/archive` · `POST /research/{id}/unarchive`

Move a session out of, or back into, the active list. Reversible, loses nothing.

### `DELETE /research/{id}`

`204`. Permanent. Agent logs, chat messages, and audit rows cascade; the graph checkpoints
are dropped explicitly, because cascades cannot reach them and they hold fetched page
content. `409` while the session is `RUNNING`.

### Exports

| Method | Path | Returns |
|---|---|---|
| `GET` | `/research/{id}/export.md` | `text/markdown`, as an attachment |
| `GET` | `/research/{id}/export.pdf` | `application/pdf`. **`501`** if WeasyPrint's native libraries are unavailable |
| `GET` | `/research/{id}/export.bundle.json` | `application/json`. **`400`** unless the session is `COMPLETED` |

`404` when there is no report to export. Demo sessions are stamped — see
[Exports](../user-guide/29-exports.md) and
[the bundle format](15-bundle-format.md).

---

## Report chat

### `GET /research/{id}/chat`

The message history for this report: `[{id, session_id, role, content, created_at}]`.

### `POST /research/{id}/chat`

```json
{ "message": "1 to 4000 characters", "scope": "report" }
```

`scope` is `report` (default), `corpus`, `web`, or `everything`. Streams SSE:
`connected{scope, sources, notes}` → `chunk`* → `done{message_id}`, or `error{detail}`.

`400` unless the session is `COMPLETED`. `400` when `scope=corpus` and the configured
embedder is remote — corpus scope promises the question is never embedded off-machine, so it
refuses rather than quietly sending it. `429` when the chat rate limit is enabled and hit.

**What `corpus` promises, exactly:** no *retrieval* egress. No web retriever runs and the
query is not embedded remotely. It does not promise zero network calls — the answer is still
written by a model, which is remote unless chat is routed to a local one.

---

## Projects

| Method | Path | Notes |
|---|---|---|
| `GET` | `/projects` | `{projects, total}`; each carries a denormalised `session_count` |
| `POST` | `/projects` | `{name, description?}` → `201`. `409` on a case-insensitive duplicate name |
| `PATCH` | `/projects/{id}` | `{name?, description?, archived?}` |
| `DELETE` | `/projects/{id}` | `204`. Cascades sessions, threads, and memory. `409` while a session is `RUNNING` |

---

## Corpus documents

Prefix `/projects/{project_id}/corpus`.

| Method | Path | Notes |
|---|---|---|
| `POST` | `/documents` | Multipart upload. Accepted kinds: `pdf`, `html`, `md`, `txt` |
| `GET` | `/documents` | `[{id, filename, chunks, created_at, size_bytes, downloadable}]` |
| `GET` | `/documents/{doc_id}/download` | The original bytes |
| `DELETE` | `/documents/{doc_id}` | `204` |
| `GET` | `/status` | `{documents, chunks, chunks_by_model, current_model}` |

`downloadable` is `false` for documents ingested before originals were retained; the UI keys
its affordance off it rather than assuming every row has a file.

**PDFs are served `inline`; every other kind is `attachment`.** That is the single exception
to "an uploaded document never renders in this origin": `application/pdf` plus `nosniff` goes
to the browser's own sandboxed viewer, which is the only way in-place PDF preview can work.
The route sets `frame-ancestors 'self'` and an explicit `X-Frame-Options: SAMEORIGIN` for
PDFs, and keeps `'none'` plus `sandbox` for everything else.

---

## Project chat

Server only — the desktop build has no project memory.

| Method | Path | Notes |
|---|---|---|
| `GET` | `/projects/{id}/threads` | `{threads, total}` |
| `POST` | `/projects/{id}/threads` | `{title?}` → `201`; the title is derived from the first message if omitted |
| `DELETE` | `/threads/{id}` | `204`; messages cascade |
| `GET` | `/threads/{id}/messages` | History with resolved citations |
| `POST` | `/threads/{id}/messages` | `{message, scope?}` → SSE. **`503`** when no embeddings provider is reachable |
| `GET` | `/projects/{id}/memory/status` | Memory legibility — see below |

`POST /threads/{id}/messages` streams `connected{citations}` → `chunk`* →
`done{message_id, citations}`. Citations are sent on `connected`, **before the first token**:
they describe what was *retrieved*, which is settled the moment the query runs.

It returns `503` rather than an ungrounded answer when embeddings are unavailable. This
endpoint's contract is that answers come from approved research.

`GET /projects/{id}/memory/status` returns `available`, `chunk_count`, `indexed_reports`,
`approved_reports`, `pending_reports`, `current_model`, a per-model breakdown, `stale_models`,
and `last_ingest_at`. `pending_reports` and `stale_models` are the two ways memory goes
quietly incomplete, and neither is otherwise distinguishable from "there is nothing on that".

---

## Models and routing

| Method | Path | Notes |
|---|---|---|
| `GET` | `/models` | The catalog, presets, available providers, and effective/user/deployment routing |
| `GET` | `/models/readiness` | Whether this user can run research at all: `{ready, has_cloud_key, local_reachable, local_chat_models}` |
| `GET` | `/models/routing` | `{routing, effective_routing}`; `routing` is `null` when on the deployment default |
| `PUT` | `/models/routing` | `{routing: {role: "provider:model"}}`. Validated on write |
| `DELETE` | `/models/routing` | Clears the preference |
| `POST` | `/models/providers/test` | Probe a key before storing it → an `ok`/`degraded`/`failed` verdict |
| `GET` | `/models/providers/health` | Re-probe the stored key |
| `GET` | `/models/local/status` | Ollama discovery |
| `POST` | `/models/local/pull` | Pull a model, streaming progress |

Each catalog entry carries `route`, `provider`, `model_id`, `display_name`, per-million input
and output prices (**`null` means the deployment must supply one, not free**), context window,
max output tokens, tool and structured-output support, notes, and whether *this user* has a
usable key for it.

`/models/local/status` returns `install_state` as `running`, `installed_not_running`, or
`not_installed` — three states, because "installed but not running" needs the start button
and "not installed" needs the installer link, and they used to look identical. Each listed
model reports `params_b`, `likely_underpowered`, `is_embedding`, and whether its family is in
the catalog.

**Routing validation runs on write**, so a stored preference is always startable and a run
cannot fail halfway on a model that could have been rejected when it was picked.

---

## Desktop-only endpoints

The desktop sidecar serves the same contract with three deliberate differences: keys come
from the OS keychain rather than a decrypted column, there is no rate-limit dependency (it
needs Redis and a user model, and the desktop has neither), and the corpus is one file for
the whole app.

It additionally exposes `/desktop/keys` (`GET`, `PUT /{provider}`, `DELETE /{provider}`,
`PUT /custom_endpoint`) and `/models/local/{start,stop}` for supervising a local model server.

**`/threads` is absent by design** — project memory is pgvector-only.
