# 04 · Interview Defense

> The questions a skeptical senior engineer actually asks, and honest answers — including
> the parts that don't flatter the project. The war stories in §3 are the most useful
> content here: they're the difference between "I read the docs" and "I shipped it".

---

## 1. The 90-second pitch

> LLMs answer research questions fluently and unverifiably — and wrong output looks exactly
> like right output. I built a research assistant where **a human approves before anything
> is final** and **every claim resolves to a source snippet**.
>
> Four specialized agents run as a compiled LangGraph `StateGraph`: a planner decomposes
> the question, an executor runs real search and page-read tool calls per task, a critic
> grades the evidence and **fails closed**, and a synthesizer writes a cited draft. Then
> the graph hits `interrupt()` — a real checkpoint, not a flag. State persists in Postgres
> and the worker exits. When you approve hours later, it **resumes at the gate** instead of
> re-running research. There's a test asserting the planner runs exactly once across submit
> and approve.
>
> It's a deployable product, not a notebook: cookie auth with refresh rotation and reuse
> detection, per-user BYOK keys encrypted at rest, an SSRF guard, atomic rate limits, an
> eval harness with a committed baseline, container images, CI.
>
> The most interesting part isn't the happy path — it's the four production bugs that only
> appeared when I ran it against real models and a real browser. Two of them were
> *silent*: the system reported success while doing nothing useful.

---

## 2. Design questions

**Why LangGraph? Isn't this a `while` loop with extra steps?**

The previous iteration *was* a `while` loop "simplified for M1", and it shipped four
critical defects. But the structural argument matters more than the anecdote: I need
**durable human-in-the-loop**. `interrupt()` checkpoints graph state to Postgres and lets
the worker process exit; approval resumes that state. A hand-rolled loop turns HITL into
"hold a process open and poll a flag", which is a materially worse program — it can't
survive a deploy.

Secondary wins: budgets live on conditional edges so no node can forget them, and the
executor⇄critic retry cycle is visible topology rather than nested `if`s.

**What did LangGraph cost you?**

A heavy dependency with real API churn, and two Postgres drivers in one process —
`AsyncPostgresSaver` needs `psycopg` while the app uses `asyncpg`. That cost me a
production bug (missing `psycopg[binary]` in the slim image → every worker run failed).
I'd take the trade again, because durable HITL *is* the product, but I don't pretend it
was free.

**Why is the frontend the only published service?**

It's a security decision disguised as a topology one. The Next `rewrites` proxy makes the
API same-origin, which lets auth be **httpOnly cookies** — and cookies are what let native
`EventSource` authenticate. The prior iteration used `localStorage` tokens: XSS-
exfiltratable *and* unable to authenticate an `EventSource`. One choice removes a
vulnerability class and unblocks live streaming.

**Why does the critic fail closed? Doesn't that hurt throughput?**

It costs retries, and that's the point. The default failure mode of LLM-as-judge is
fail-*open*: malformed JSON → `except` → treated as "no objection". A quality gate that
fails open is worse than no gate, because it manufactures confidence. So an unparseable
verdict is an explicit `passed=False` with a stated reason.

**Why numbered sources in code instead of asking the model to cite?**

Because "please cite your sources" is unverifiable. I build the numbered table in Python
from unique evidence URLs and hand the model a pre-numbered list; the frontend resolves
each `[n]` against that same table. A marker that resolves to nothing renders as a visible
⚠ chip. The system is designed to *show* its failures — hiding an unresolved citation
would make the output look better and be worth less.

**Why is money `Numeric` and not `float`?**

Binary floating point can't represent most decimal fractions exactly. For a budget guard
that gates spending, accumulated rounding is a real correctness issue, and it's free to
avoid.

**Why a `ContextVar` for BYOK keys rather than passing them down?**

Threading a key through every node signature would put a secret in a dozen call sites and
make it easy to log by accident. A `ContextVar` scopes it to the run. Critically it must
**not** be a module global: Celery prefork plus async means concurrent runs share a
process, and a global would be a cross-tenant key leak. There's a test asserting a Google
BYOK key is never handed to an Anthropic-routed role.

**Your worker doesn't retry. Isn't that fragile?**

Deliberate. The pipeline is **not idempotent** — broker redelivery would re-run research
and re-charge the user's key. `task_acks_late=False`, no autoretry; recovery is an explicit
resume from the last checkpoint. Retrying a non-idempotent task is how you get duplicate
spend.

---

## 3. The war stories

These are the answers to "tell me about a hard bug". All four are real, all were found by
running the system rather than reading it, and two produced *successful-looking* output.

### 3.1 The live feed that was never live (gzip buffering SSE)

**Symptom.** The pipeline ran perfectly — events in the database, worker logs healthy —
but the browser's live monitor sat on "Waiting for the pipeline to start…" forever.

**Why it hid.** My end-to-end test drove the API with polling, not a browser. The SSE
transport was never exercised by a real client, so every test passed.

**Diagnosis.** I bisected by client, not by code:

| Client | Result |
|---|---|
| Python `urllib` through the same proxy | events instantly |
| Browser `EventSource` | 0 events, **no `onerror`** |
| Browser `fetch` + `ReadableStream` | HTTP 200, correct content-type, **0 bytes** |

Headers arrived but the body didn't — that's buffering, not a failure. The only meaningful
difference between the two clients was `Accept-Encoding`. Confirmed directly:

| `Accept-Encoding` | Bytes in 4s |
|---|---|
| `identity` | 40 (instant) |
| `gzip, deflate, br` | 10, then timeout |

**Root cause.** Next.js gzips by default; compression buffers a `text/event-stream` while
filling its window.

**Fix.** `Cache-Control: no-transform` — the HTTP-standard "don't alter this payload",
honored by Next's `compression` middleware, nginx, and CDNs alike. One header in a shared
`SSE_HEADERS` constant, plus a test asserting both endpoints use it. I chose this over
`compress: false` because disabling compression app-wide to fix one route is a bad trade.

**What I took from it.** *A healthy-looking connection is not a working connection.* Any
streaming feature needs an end-to-end test through the real client stack.

### 3.2 The report that said "no evidence was provided"

**Symptom.** A run completed successfully and produced a well-formatted report stating
there was no evidence. 0 sources, 0 citations.

**The misleading part.** Search was working perfectly the whole time — `retriever_hit
count=5`, pages returning 200. The obvious hypothesis (retrieval broken) was wrong.

**Root cause.** After the tool loop the executor must emit `ExecutorOutput` JSON. Two ways
that fails: the loop exhausts `_MAX_TOOL_ROUNDS` while still calling tools (so the last
message is a `ToolMessage`, not a summary), or the model wraps its JSON in a markdown
fence. Both hit `except: evidence = []` — **an entire task's research discarded with no log
line**.

**Fix.** Fence/prose-tolerant parsing; a **tool-free structured-output retry** over the
observations already gathered (the work is in hand — don't throw it away); and an
`executor_wrapup` log so the fallback is observable.

**What I took from it.** Every `except: pass` around a model response is a place the
system can succeed loudly while producing nothing. **Silent degradation is worse than a
crash** — a crash gets fixed.

### 3.3 Two Postgres drivers, one missing wheel

**Symptom.** Every pipeline run failed in the container: `no pq wrapper available`.

**Root cause.** `AsyncPostgresSaver` runs on `psycopg`, not the app's `asyncpg`. My slim
image had neither `psycopg[binary]` nor a system `libpq`. It passed locally only because
my dev venv happened to have libpq.

**Fix.** Pin `psycopg[binary]` explicitly.

**What I took from it.** A transitive dependency that works on your laptop is not a
declared dependency. This would also have broken CI's golden-E2E worker.

### 3.4 The model that returned a list instead of a string

**Symptom.** Latent, caught while switching models: newer Gemini (`3.x`, `*-latest`)
return `.content` as a **list of typed blocks**, not a `str`.

**Impact if shipped.** `synthesizer_node` did `str(resp.content)` — that splices a Python
`repr` of the block list into the report body. Chat did `isinstance(content, str) ? ... :
""` — streams nothing at all.

**Fix.** One `text_of()` normalizer handling both shapes (skipping thinking blocks), used
at all three consumption sites.

**What I took from it.** Provider response *shape* is a compatibility surface, not just
provider *choice*. Normalize at the boundary, once.

---

## 4. Hard questions I expect

**Isn't this just a wrapper around an LLM API?**

The LLM calls are the least interesting part. What's actually here: durable checkpointed
HITL that survives worker death; a fail-closed quality gate; citations as a verifiable
data structure with visible failure; lossless event streaming with replay; per-user key
isolation inside a shared worker; real cost accounting with a budget guard. Those are
systems problems that exist regardless of which model you call.

**How do you know the reports are any good?**

Partly I don't, and I built the instrument rather than claim otherwise. `make eval` runs a
versioned 10-query set and writes dated JSON to `backend/evals/results/` — citation
resolution rate, uncited-claim count, source count, cost, latency, completion rate — so
"did that prompt change help?" is answerable instead of vibes. Release criteria are
written down (citation support ≥95%, completion ≥90%).

**Honest gap:** the committed baseline is a *fake-mode* run. It exercises the plumbing and
pins structural numbers; it is not a real-model quality claim. The LLM-judged citation
support rate needs a real-model run with keys, and I'd rather say that than imply a
quality number I haven't measured.

**What happens if the model ignores your citation format?**

Two backstops. The synthesizer gets a pre-numbered evidence table so the mapping isn't
invented. And the renderer resolves every marker — anything unresolvable renders ⚠ rather
than passing as a real citation. If the model cites `[7]` with six sources, the user sees
that immediately.

**Your executor loop is bounded at 8 rounds. What if a task needs more?**

Then it wraps up with what it has — and after the §3.2 fix, that partial evidence is
*recovered* rather than dropped. The bound exists because an unbounded tool loop is
unbounded spend. I'd rather ship a bounded loop with honest partial results than an
open-ended one with a surprise bill.

**Why no vector store / RAG over user documents?**

It's on the v2 list, and it's out of scope on purpose. The wedge is *web research with
verifiable provenance and a human gate*. Document ingestion is a different product with
its own failure modes (chunking, embedding drift, permissions). Half-building it would
weaken the part that works.

**How would this scale to 1000 concurrent users?**

Not as-is, and the path is concrete: raise Celery concurrency (per-session locks already
make that safe), then partition queues per tenant so one heavy user can't starve others,
add a read replica for history, share the retrieval cache across users. Redis pub/sub is
already broadcast, so multiple API replicas work unchanged — replay comes from Postgres.
The first real ceiling isn't CPU, it's **provider rate limits**, which is why BYOK matters:
it moves both cost *and* rate limits to the user.

**What's the weakest part of the system?**

Retrieval quality is the ceiling on report quality, and with no Tavily/Brave key the
DuckDuckGo fallback is slow and rate-limited. Second: the critic grades per-task evidence
but nothing re-validates at runtime that the synthesizer's `[n]` usage is *faithful* to the
snippet it points at — the eval harness measures that offline, but it isn't a gate.

**What would you do next, in order?**

1. Real-model eval baseline with keys — I can't defend quality claims without it.
2. Runtime citation-faithfulness check (a cheap judge pass over cited claims before the
   gate), which closes the gap above.
3. Evidence dedup by content hash, not URL-exact.
4. Multi-citation chips (`[3, 11, 18]`).
5. `v1.0.0` tag once CI is green on `main`.

**What would you do differently from the start?**

Test through the real client earlier. Both silent bugs (§3.1, §3.2) survived because my
tests exercised the API rather than the product. I'd write one browser-driven smoke test
on day one, before any feature work.

---

## 5. Things I will not claim

Stating these explicitly, because over-claiming is the fastest way to lose a technical
room:

- The eval baseline is fake-mode. It is not a real-model quality measurement.
- `v1.0.0` isn't tagged and images aren't published to GHCR — that needs green CI on
  `main`, and tagging is an outward action I left to the owner.
- The golden E2E journeys run locally and are wired into CI, but I have not watched them
  pass in GitHub Actions.
- Multi-agent "collaboration" here is a pipeline with a retry cycle, not emergent
  negotiation between agents. That framing would be marketing.
- The system is only as good as its retrieval, which today is a keyless fallback in the
  default configuration.

## 6. One-line answers

| Question | Answer |
|---|---|
| Hardest bug? | gzip silently buffering SSE — a healthy-looking connection delivering zero bytes |
| Most important design decision? | The gate is a durable checkpoint, not a status flag |
| Most important safety decision? | The critic fails closed |
| What makes it deployable? | Migrations on start, one published service, BYOK, per-session and per-month budget ceilings |
| What proves it works? | 18 real sources, all 18 citations resolving, $0.027, exports verified — plus 69 backend / 39 frontend tests |
| Biggest risk in production? | Retrieval quality and provider rate limits, not model quality |
