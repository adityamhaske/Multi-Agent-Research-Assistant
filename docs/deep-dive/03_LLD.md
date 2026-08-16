# 03 · Low-Level Design (LLD)

> Module-by-module internals: the actual mechanisms, the invariants they hold, and the
> subtle bits that would be easy to break in a refactor.

---

## 1. Code map

```
backend/app/
├── agent/                 # the pipeline — no HTTP, no Celery
│   ├── graph.py           # StateGraph: nodes, routing, budgets
│   ├── state.py           # AgentState TypedDict (the graph's contract)
│   ├── schemas.py         # PlannerOutput, ExecutorOutput, CriticVerdict, Source
│   ├── llm_factory.py     # provider routing, BYOK ContextVar, pricing, text_of()
│   ├── tools.py           # web_search, read_webpage (ToolNode surface)
│   ├── retrievers.py      # Tavily → Brave → ddgs chain + Redis cache
│   ├── net_guard.py       # SSRF guard (post-DNS-resolution)
│   ├── prompts.py         # versioned role prompts
│   ├── events.py          # emit() indirection via ContextVar
│   └── fakes.py           # LLM_MODE=fake scripted models + fixtures
├── api/v1/                # HTTP only — no business logic
│   ├── auth.py            # register/login/refresh/logout, profile, password, BYOK, usage
│   ├── research.py        # start, list, detail, SSE stream, approve, exports
│   └── chat.py            # grounded follow-up chat (SSE)
├── services/              # reusable, HTTP-free
│   ├── tokens.py          # JWT + opaque refresh tokens, cookie kwargs
│   ├── auth_service.py    # refresh rotation, reuse detection, revoke-all
│   ├── passwords.py       # bcrypt direct + policy
│   ├── crypto.py          # Fernet for BYOK keys (HKDF-derived)
│   ├── rate_limit.py      # atomic Lua limiter
│   ├── usage.py           # month/week/last-session aggregation
│   ├── export.py          # md → HTML → PDF
│   ├── sse.py             # SSE_HEADERS (no-transform)
│   └── security_headers.py
├── workers/
│   ├── pipeline_runner.py # the async engine: locks, checkpointer, BYOK, persistence
│   ├── tasks.py           # thin Celery wrappers (deliberately non-retrying)
│   └── celery_app.py
└── models/                # SQLAlchemy 2.0 typed mappings
```

**Layering rule:** `agent/` never imports from `api/`; `services/` never imports FastAPI
request objects. That's what lets the whole pipeline run in a test with no HTTP stack.

---

## 2. The graph

### 2.1 State contract

`AgentState` is a `TypedDict` — the single shared structure every node reads and patches.
Nodes return **partial dicts**, LangGraph merges them. Key fields:

| Field | Owner | Notes |
|---|---|---|
| `tasks` | planner | the work list; researched concurrently in rounds (docs/12 M7) |
| `evidence[]` | executor | **rebuilt each round in task order**, never completion order — otherwise citation numbers shuffle between identical runs; each item tagged `task_id` |
| `verdicts{}`, `retries{}` | critic | per task, keyed by `str(task_id)` (state is JSON in the checkpointer); a task leaves the pending set when it passes or exhausts retries |
| `research_round` | executor | how many executor→critic rounds have run |
| `draft_report`, `sources[]` | synthesizer | `sources` is the numbered citation table |
| `approved`, `human_feedback`, `rework_count` | gate | set from the resume `Command` |
| `cost_usd`, `tokens_input`, `tokens_output` | every node via `_acc()` | budget inputs |
| `started_at` | init | wall-clock budget basis |
| `error` | any | non-empty routes to `failer` |

### 2.2 Nodes

**Planner** — structured output → `PlannerOutput.tasks`. One retry, then `error` (routes
to `failer`). Emits the task list so the UI can show `n/total` progress.

**Executor** — the only node with tools:

```python
model = get_llm("executor").bind_tools(EXECUTOR_TOOLS)
for _round in range(_MAX_TOOL_ROUNDS):        # bounded — no unbounded agent loop
    resp = await model.ainvoke(messages)
    cost += estimate_cost(resp, "executor"); ...
    messages.append(resp)
    if not resp.tool_calls: break
    for call in resp.tool_calls:
        observation = await tool.ainvoke(call["args"])   # errors become observations
        messages.append(ToolMessage(json.dumps(observation), tool_call_id=call["id"]))
```

Then evidence extraction, with the recovery path added after real-model testing:

```python
final_text = text_of(final) if isinstance(final, AIMessage) else ""
evidence = _parse_evidence(final_text) if final_text.strip() else []

if not evidence:                     # loop ran out of rounds, or JSON came fenced/prosed
    observations = "\n\n".join(text_of(m) for m in messages if isinstance(m, ToolMessage))
    if observations.strip():
        logger.info("executor_wrapup", ...)          # observable, not silent
        parsed, ... = await _structured("executor", [...observations...], ExecutorOutput)
        evidence = [e.model_dump() for e in parsed.evidence] if parsed else []
```

*Invariant to preserve:* a tool error must become an **observation string**, never an
exception — a 404 on one page shouldn't kill the task.

**Critic** — fails closed (see [01 §7.2](01_End_to_End_System.md)). Judges only the
current task's evidence, selected by `task_id`.

**Synthesizer** — builds the numbered `sources` table in *code* from unique evidence URLs,
then hands the model a pre-numbered evidence list. `human_feedback` is injected here on
rework and cleared after use (so it applies exactly once).

**Gate** — `interrupt({...})`. On resume, `decision = {"approved", "feedback"}`; rejection
increments `rework_count`.

**Finalizer / Failer** — terminal; set `final_report` or `error`.

### 2.3 Routing

```python
def _over_budget(state):
    # 0 disables a guard, and all three default to 0. The token ceiling was once a
    # hardcoded 1_000_000 that no config could reach — it killed a real run at 1,003,721.
    return (cost_cap and state["cost_usd"] >= cost_cap
            or token_cap and state["tokens_input"] >= token_cap
            or time.time() - state["started_at"] >= settings.max_wallclock_seconds)

def route_after_critic(state):
    if _over_budget(state): return "failer"
    if not verdict["passed"] and retries < max_critic_loops: return "executor"
    return "next_task" if more_tasks else "synthesizer"
```

One place, three ceilings, cannot be forgotten by a new node.

### 2.4 `text_of()` — the content-shape normalizer

`.content` is a `str` on some models and a **list of typed blocks** on others (Gemini 3.x,
`*-latest`, thinking-enabled models). `str(content)` on a list splices a Python `repr`
into the report; ignoring the list drops the text entirely. Both were live bugs.

```python
def text_of(m) -> str:
    content = getattr(m, "content", m)
    if isinstance(content, str): return content
    if isinstance(content, list):
        return "".join(b["text"] for b in content
                       if isinstance(b, dict) and b.get("type") in (None, "text")
                       and isinstance(b.get("text"), str))
    return ""
```

Used at all three consumption sites: synthesizer draft, executor final answer, chat stream.
**Any new place that reads `.content` must use it.**

---

## 3. Worker

### 3.1 Run scope

```python
async with AsyncSessionLocal() as db:                 # ONE session for the whole run
    session.status = RUNNING; await db.commit()
    user_keys = await _user_provider_keys(db, user_id)
    keys_token = llm_factory.set_user_keys(user_keys)  # BYOK, ContextVar-scoped
    token = events.set_emitter(_make_sink(db, session_id))
    try:
        async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
            graph = build_graph(saver)
            result = await graph.ainvoke(initial_or_resume, config)
            state = (await graph.aget_state(config)).values   # ASYNC getter — see below
            await _persist_outcome(db, session, session_id, result, state)
    finally:
        events.reset_emitter(token)
        llm_factory.reset_user_keys(keys_token)
```

Three invariants worth guarding in review:

1. **One DB session for the whole run.** A previous iteration wrote to a closed session —
   the regression test is `test_pipeline_persists_within_open_session`.
2. **`await graph.aget_state()`, never `graph.get_state()`.** The sync getter raises on an
   async checkpointer from the main thread. This shipped as a real crash.
3. **The checkpointer DSN is psycopg-flavored**
   (`postgresql://`, not `postgresql+asyncpg://`) and needs `psycopg[binary]` — omitting it
   fails at runtime with "no pq wrapper available".

### 3.2 Locking

```python
await redis.set(f"lock:session:{sid}", token, ex=timeout+60, nx=True)   # acquire
# release: compare-and-delete, so we only delete a lock we still own
if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end
```

TTL **exceeds** the Celery task timeout — otherwise a lock expires under a still-running
task and a second worker joins. Tests: `test_session_lock_outlives_task_timeout`,
`test_lock_release_is_owner_only`.

### 3.3 Event sink

```python
row = AgentLog(session_id=..., event_type=..., payload=event)
db.add(row); await db.flush()      # get the id
event["id"] = row.id               # id travels with the live event
await db.commit()
await publish_event(session_id, event)   # durable first, then broadcast
```

Order matters: **persist then publish**. A client that reconnects can always reconstruct
from `agent_logs`; a published-but-unpersisted event would be unrecoverable.

### 3.4 Celery tasks: deliberately non-retrying

`task_acks_late=False`, no autoretry. The pipeline is **not idempotent** — broker
redelivery would re-run research and re-charge the user. Recovery is an explicit resume
from the checkpoint. On unexpected exception the task marks the session `FAILED` with the
reason.

---

## 4. Retrieval and web safety

**Chain:** Tavily → Brave → `ddgs`, first non-empty wins, results cached in Redis 24h by
normalized query. Degradation is logged (`retriever_hit retriever=…`), never silent.

**SSRF guard** (`net_guard.py`) — the ordering is the whole point:

```
parse URL → scheme must be http(s) → resolve DNS →
for each resolved IP: reject loopback / private / link-local / reserved / metadata
→ only then fetch, with size + timeout caps, no redirects to unvalidated hosts
```

Checking the *hostname* would be trivially bypassed by a DNS record pointing at
`169.254.169.254`. Parameterized test corpus:
`test_ssrf_guard_blocks_metadata_and_private_ranges`.

---

## 5. Auth

### 5.1 Tokens

| Token | Form | Lifetime | Storage |
|---|---|---|---|
| Access | HS256 JWT, `type: "access"` | 15 min | httpOnly cookie, path `/` |
| Refresh | 256-bit opaque `secrets.token_urlsafe(32)` | 14 d | httpOnly cookie, path `/api/v1/auth`; server keeps **sha256 only** |

Refresh tokens are opaque, not JWTs: they must be revocable, and revocability requires
server state anyway — so a JWT would add parsing risk for no benefit.

### 5.2 Rotation and reuse detection

Every refresh **rotates**. Presenting an already-rotated token means the token leaked, so
the entire family is revoked:

```
rotate(raw):
  row = find(sha256(raw))
  if not row or expired: return None
  if row.revoked_at is not None:        # reuse of a rotated token
      revoke_all_for_user(row.user_id)  # nuke the family
      return None
  row.revoked_at = now(); issue new token in same family
```

`revoke_all_for_user` is also the public entry point used by password change.

### 5.3 Password change

Requires the current password (a stolen cookie alone must not permit takeover), rejects
reuse of the same password, applies the registration policy, revokes **all** refresh
tokens, then re-issues cookies for the caller so they stay signed in. Rate-limited on the
login limiter because it verifies a password.

### 5.4 Rate limiting

One Lua script, so increment + TTL are atomic (a non-atomic version can leave a key with
no expiry and permanently lock a user out):

```lua
local n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return n
```

Keys are **per operation** (`rl:research:{uid}`, `rl:chat:{uid}`, `rl:login:ip:{ip}`,
`rl:register:ip:{ip}`) — sharing one key across operations let chat exhaust a user's
research budget. Test: `test_rate_limit_keys_are_per_operation`.

---

## 6. BYOK crypto

```python
def _fernet():
    secret = (settings.encryption_key or settings.jwt_secret_key).encode()
    derived = HKDF(SHA256, length=32, salt=None, info=b"mara.user-api-key.v1").derive(secret)
    return Fernet(base64.urlsafe_b64encode(derived))
```

- **HKDF with a distinct `info`** keeps this key domain-separated from JWT signing even
  when both derive from the same secret.
- **`salt=None` is deliberate**, not an oversight: the input is already high-entropy (≥32
  chars, enforced at startup), so HKDF-Extract without salt is sound here.
- **`decrypt()` returns `None`** rather than raising, so a rotated secret degrades to the
  server key instead of crashing a worker.
- **`hint()` returns only the last 4 characters** — the only form that ever reaches a
  response body.

Resolution order at build time: user key → server key → **actionable `ValueError`**
naming both remedies (add a key in Settings, or set `PROVIDER_API_KEY`).

---

## 7. SSE

### 7.1 Server

```python
SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",   # no-transform is load-bearing
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}
```

Shared constant used by both stream endpoints, with a test asserting both use it — a
local dict in one endpoint would drift and silently break that stream.

Generator: emit `connected` → replay backlog (`id > Last-Event-ID`) → subscribe → tail
live, skipping ids ≤ the replay high-water mark → terminate on a terminal event.

### 7.2 Client

`useSessionStream` — native `EventSource` (same-origin cookies authenticate it), de-dupes
on durable id, and on a terminal event invalidates the session query and closes.

Two subtleties that lint and correctness both care about:

- Subscription reset is a **render-phase state reset** keyed on the subscription target,
  not a `setState` in an effect (which causes cascading renders).
- The ref holding seen ids is reset **inside the effect**, because refs must not be
  written during render.

And the safety net: `useSession` self-polls every 5s while status is `PENDING`/`RUNNING`.
SSE is the fast path; polling guarantees convergence.

---

## 8. Frontend

**Server state** is TanStack Query only — no parallel hand-rolled store. SSE handlers write
*into* the query cache rather than maintaining a second copy.

**Auth shape:** a server component checks the access cookie and redirects before any app
chrome renders; the client `AppShell` handles the "cookie present but expired" case via
`/auth/me` + the API client's single silent refresh-and-retry.

**Citation rendering** (`lib/citations.tsx`) — the important detail is *where* the
transform happens:

```
markdown → remark-gfm → HAST → custom rehype plugin walks text nodes,
           skipping <code>/<pre>/<a>/<cite>, replacing [n] with <cite data-index data-resolved>
        → components.cite → resolved ? <CitationChip> : <UnverifiedChip>
```

Operating on the tree (not a regex over the markdown string) is why `arr[2]` inside a code
span never becomes a citation. No `rehype-raw`, CI-grep-guarded.

**Design system:** Academic Research-Paper aesthetic. Every color is a CSS variable defined for
both themes (paper backgrounds `#FBFBFA`/`#121214`, academic forest accent `#3F5E4D`/`#527A65`, strict hairline borders);
CI greps for hardcoded hex, for `localStorage`/`sessionStorage`, and for `rehype-raw`/
`dangerouslySetInnerHTML`. Strict 0px border radius is enforced globally, with square 8x8 status
markers and academic typography hierarchy (serif headings, sans body, monospace telemetry).

---

## 9. Schema and migrations

Alembic only; **no `create_all` anywhere** (it once masked an empty migration). Two
revisions: `0001_initial_v2` (full v2 schema) and `0002_user_profile_byok` (additive
profile/BYOK/limit columns — every column nullable or defaulted, so it applies to a
populated table without backfill). Both render forward and backward
(`test_empty_migration_rejected` guards the round-trip).

The API container runs `alembic upgrade head` in its entrypoint before serving, and the
worker/frontend gate on its readiness — so migrations apply exactly once per deploy.

---

## 10. Testing map

| Layer | Runs | Covers |
|---|---|---|
| Unit | ms, no I/O | crypto round-trip + hint, BYOK isolation, rate-limit keys, SSRF corpus, password policy, usage math, eval metrics, SSE headers |
| Pipeline | s, no network | whole graph on scripted models: gate reached, approval finalizes without replanning, rework loop, critic fail-closed |
| Integration | s, real PG/Redis | auth flows incl. rotation + reuse detection, migrations |
| Golden E2E | min, packaged stack | the three journeys through a real browser |
| Evals | offline | report quality on a fixed query set, dated JSON baseline |

**Named regression tests** exist per historical bug — `test_resume_enters_graph_at_gate`,
`test_pipeline_persists_within_open_session`, `test_sse_parser_handles_split_utf8_and_partial_events`,
`test_sse_headers_forbid_transformation`. When a bug is found, the test is named after it.

## 11. If you're changing this code

Highest-risk edits, and what to re-check:

| Change | Watch for |
|---|---|
| Reading `.content` anywhere new | Use `text_of()` or you'll break block-list models |
| Adding an SSE endpoint | Use `SSE_HEADERS`, or a proxy will buffer it into silence |
| Touching the executor's evidence path | Keep the tool-free fallback + the log line; silent `[]` is the failure mode |
| Touching the critic | Keep it failing closed |
| New model routing | Add a price-table entry or startup refuses to boot (by design) |
| Anything with a user key | It must never enter a response body, a log, or a module global |
| New graph node | Budgets are on edges — make sure your path passes through one |
