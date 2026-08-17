# Agent architecture

The complete contract for the agent layer. The graph is a real compiled
`langgraph.StateGraph` with Postgres checkpointing. There is no fallback "simplified
runner"; that pattern is banned.

## Graph topology

```mermaid
flowchart TD
    START([START]) --> planner
    planner -->|skip_plan_gate| executor
    planner --> plan_gate
    plan_gate -->|"interrupt() — waits for a human"| plan_gate
    plan_gate -->|edited tasks + outline| executor
    executor --> critic
    critic -->|tasks still pending| executor
    critic -->|all tasks settled| contradiction_detector
    contradiction_detector --> synthesizer
    synthesizer --> hitl_gate
    hitl_gate -->|"interrupt() — waits for a human"| hitl_gate
    hitl_gate -->|approved| finalizer
    hitl_gate -->|rejected + feedback| synthesizer
    finalizer --> END([END])

    planner -. error .-> failer
    critic -. budget/time exceeded .-> failer
    failer --> END
```

Nine nodes: `planner`, `plan_gate`, `executor`, `critic`, `contradiction_detector`,
`synthesizer`, `hitl_gate`, `finalizer`, `failer`. Compiled with a checkpointer whose
`thread_id` is the session id.

### Two gates, one thread

Both gates call `interrupt()` on the same graph thread. Which one fired must be **read** off
the interrupt payload's `type` field, never assumed — assuming would tell the host a draft
was ready before a single search had run.

That is also why `resume()` takes exactly one of `approved=` or `plan=` and raises on both
or neither. There is no safe default: `approved=True` would approve a draft that does not
exist yet, and `False` would count a rework nobody asked for.

| | `plan_gate` | `hitl_gate` |
|---|---|---|
| Payload type | `PLAN_READY` | `HITL_READY` |
| Payload carries | proposed tasks, proposed outline | word count, source count, contradiction count, cost |
| Resumes with | `{tasks?, outline?}` | `{approved, feedback?}` |
| Session status | `AWAITING_PLAN` | `AWAITING_APPROVAL` |

At the design gate, an **absent** key means *unedited* — distinct from `[]`, which is a
reviewer who excluded everything. `include: false` on a task drops it before the executor
sees it, which is what makes it a review rather than a rubber stamp.

## State

A plain `TypedDict` managed by LangGraph and persisted at every step, so it stays
JSON-serialisable — primitives, lists, and dicts only.

```python
class AgentState(TypedDict, total=False):
    session_id: str
    user_id: str

    original_query: str
    research_depth: str          # fast | balanced | comprehensive

    tasks: list[dict]            # from PlannerOutput
    proposed_outline: list[dict] # editable at the design gate
    plan_approved: bool | None   # distinguishes "never reached the gate" from "passed it"

    evidence: list[dict]         # rebuilt each round in TASK order, never completion order
    verdicts: dict[str, dict]    # keyed by str(task_id)
    retries: dict[str, int]      # keyed by str(task_id)
    research_round: int

    draft_report: str | None
    sources: list[dict]
    contradictions: list[dict]
    human_feedback: str | None
    rework_count: int
    approved: bool | None

    final_report: str | None

    tokens_input: int
    tokens_output: int
    cost_usd: float
    started_at: float

    error: str | None
```

Two details are load-bearing:

**`evidence` is rebuilt in task-definition order, never completion order.** Tasks run
concurrently, and ordering by completion would number the citations differently on every
run.

**`verdicts` and `retries` are keyed by `str(task_id)`**, because the checkpointer
serialises state as JSON and JSON object keys are always strings.

## Structured outputs

Every LLM boundary is validated against a Pydantic model in `research_engine/schemas.py`.
A parse or validation failure is a node failure — never a silent fallback.

```python
class ResearchTask(BaseModel):
    id: int | str = 0            # coerced to int; normalised to 1..n by the planner
    query: str                   # a concrete, independently searchable query
    rationale: str = ""
    status: Literal["pending", "running", "passed", "failed"] = "pending"
    subtopics: list[str] = []
    include: bool = True         # False → dropped at the design gate
    source_hint: str | None = None

class PlannerOutput(BaseModel):
    tasks: list[ResearchTask]              # >= 1; capped at max_planner_tasks (default 6)
    proposed_outline: list[OutlineSection] = []

class EvidenceChunk(BaseModel):
    task_id: int = 0
    source_url: str
    source_title: str = ""
    snippet: str = Field("", max_length=500)   # verbatim supporting text
    key_fact: str = ""                          # the claim this snippet supports
    retrieved_at: str = ""

class CriticVerdict(BaseModel):
    passed: bool
    confidence: float = 0.5                     # 0..1
    reasons: list[str] = []
    feedback_for_executor: str | None = None    # supplied automatically when passed=False

class Source(BaseModel):
    index: int
    url: str
    title: str = ""
    snippet: str = ""          # the first snippet, kept for older stored rows
    snippets: list[str] = []   # EVERY snippet extracted from this source
```

`Source.snippets` is plural for a reason: one page routinely supports several distinct
facts, and keeping only one meant a citation chip could show a quote unrelated to the
sentence it was attached to.

`CriticVerdict.confidence` is coerced rather than rejected — models routinely answer `60`
instead of `0.6`, and a benign scale difference must not discard an otherwise-valid verdict.

## Node contracts

| Node | Role model | Input → output | On failure |
|---|---|---|---|
| `planner` | reasoning | query, depth, seed subtopics → `PlannerOutput` | One retry, then the session fails. **No silent single-task fallback** |
| `plan_gate` | none | `interrupt()` with the proposal; on resume, filters `include: false` and writes the approved outline | — |
| `executor` | tool-calling | task (+ critic feedback on retry) → `list[EvidenceChunk]` | Bounded tool loop; zero evidence counts as a critic failure with explicit "no results" feedback |
| `critic` | fast | task + its evidence → `CriticVerdict` | **Fails closed**: a validation error becomes `passed=False` with the reason. Never defaults to pass |
| `contradiction_detector` | fast | all evidence → conflicting-claim pairs | Pairs whose source URL is not in the evidence are dropped; overflow is capped at 10, not rejected |
| `synthesizer` | reasoning | query + evidence (+ feedback on rework) → cited Markdown | Markers referencing nonexistent evidence get one retry with the errors, then the run fails |
| `hitl_gate` | none | `interrupt()` with the draft summary | — |
| `finalizer` | none | draft → final report | — |
| `failer` | none | records the breach reason and preserves partial results | — |

Every node emits an event on entry and exit, and updates the running token and cost totals
from the model response's own usage metadata.

## The executor tool loop

A bounded loop, at most **8 tool-call rounds per task**:

```
loop (max 8 rounds):
    if the budget guard has tripped: stop
    response = model.invoke(messages)          # bound with tools + submit_evidence
    if no tool calls: break
    if submit_evidence was called: validate, record, done
    otherwise: execute the tools, append results, continue
```

| Tool | Contract | Guards |
|---|---|---|
| `web_search(query, max_results?)` | Retriever chain Tavily → Brave → DuckDuckGo, first success wins, normalised to `{title, url, snippet}`. Omitting `max_results` falls back to the configured `retrieval_k` (default 5) | Redis cache, 24h TTL. Chain exhaustion returns an explicit error the executor must surface, never an empty list |
| `read_webpage(url)` | Fetch and extract main text (≤ 8000 chars) plus title | **SSRF guard** on every hop: scheme and port allowlist, resolve-and-check every address, redirects re-validated (max 3), 2 MB body cap, 10s timeout, content-type must be `text/html` or `text/plain` |
| `calculate(expression)` | AST-restricted arithmetic | Numbers and `+ - * / **` only |

In corpus-only mode the fetch half changes: `read_webpage` resolves `corpus://` locations
from the installed corpus and **refuses every other URL**, so the tool surface makes zero
network calls. It fails closed rather than falling back to the web.

### Snippets must be text that was really fetched

The executor records what the tools actually returned, keyed by URL — search-result snippets
count as seen text too, since a quote may legitimately come from one. Every submitted
snippet is checked against that record, and one that does not occur there is **blanked and
flagged** rather than dropped: the source and the claim may still be sound, and a citation
that loses its quote is far better than one displaying an invented quotation.

A model that writes a plausible quote from memory does not get to attach it to a real URL.
That is a fabricated citation, and it is the precise failure this system exists to prevent.

### Untrusted-content framing

All retrieved text enters prompts wrapped in `<untrusted_web_content>` tags, under a
standing instruction that content inside those tags is **data**, that instructions found
there must never be followed, and that they should be reported as suspicious.

## Prompts

Versioned constants in `research_engine/prompts.py`, never inline in node code.

- **Planner** — decompose into independently searchable tasks, each with a concrete query
  and a rationale. Seed subtopics, when given, are named as a coverage floor rather than a
  ceiling.
- **Executor** — gather facts only, no synthesis; every fact carries a verbatim snippet and
  a URL; retrieved content is explicitly framed as data.
- **Critic** — check coverage of the task, independent sources, whether the snippet actually
  supports the claim, and recency where it matters. Must produce actionable feedback on
  failure.
- **Synthesizer** — use only the provided evidence; every factual claim carries `[n]`
  markers mapping to evidence indices. An outline approved at the design gate *replaces* the
  default section list, because a human chose it. It never relaxes a citation rule: an
  outline decides what the sections are, never what may be said in them without a source.
- **Chat** — answers grounded in the report and its sources; must say the report does not
  cover something rather than invent. History is replayed with correct roles.

## Routing and budgets

Conditional edges do the routing, and the budget guards live on them:

- **After the planner** — an error routes to `failer`; otherwise the design gate, unless
  `skip_plan_gate` is set.
- **After the critic** — a budget breach routes to `failer`; tasks still pending route back
  to the executor; otherwise on to contradiction detection. A task leaves the pending set
  when it **passes or exhausts its retries**, so a task whose evidence never satisfies the
  critic still contributes what it found.
- **After the review gate** — approved routes to `finalizer`, rejected back to
  `synthesizer` with the feedback.

| Bound | Default | On breach |
|---|---|---|
| Critic retries per task | 2 | Task settles with what it has; the gap is stated in the report |
| Tool-call rounds per executor run | 8 | Evidence so far is returned; the critic judges it |
| Rework loops | 3 | The gate refuses further rework; approve or abandon |
| Cost per session | **0 = unlimited** | → `failer`, partial results preserved |
| Wall-clock per session | **0 = unlimited** | → `failer` |
| Cumulative input tokens | **0 = unlimited** | → `failer` |
| Parallel tasks per round | 4 | — |

**Every limit is `0 = unlimited`, and `0` is the default.** A guard that fires names itself:
`cost ceiling reached: $0.5100 of $0.50`, not a generic "budget or loop limit exceeded".

The rule lives in two places — the edge check and the in-flight guard used during parallel
execution — and both must agree. A naive `>=` would read a zero limit as already exceeded
and skip every task at zero spend.

Concurrency bounds overshoot rather than eliminating it: with N tasks in flight, up to N
calls may already be running when the ceiling is crossed. `MAX_PARALLEL_TASKS=1` is the only
setting where overshoot is impossible.

## Model routing

Five roles route independently as `"provider:model"`, split on the **first** colon only —
so `ollama:qwen2.5:7b` is provider `ollama`, model `qwen2.5:7b`.

| Role | Default |
|---|---|
| planner | `google:gemini-2.5-pro` |
| executor | `google:gemini-2.5-flash` |
| critic | `google:gemini-2.5-flash` |
| synthesizer | `google:gemini-2.5-pro` |
| chat | `google:gemini-2.5-flash` |

Resolution is most-specific-first: **the session's snapshot → the user's saved preference →
the deployment's `MODEL_*`**. Validation runs on *write*, so a stored preference is always
startable and a run cannot fail halfway on a model that could have been rejected when it was
picked. The session snapshots what it ran, so a resumed run keeps its models and a finished
report stays attributable to what wrote it.

Prices come from a catalog and are never estimated. `None` means "this deployment must
supply it", not "free". `openrouter`, `custom` and `ollama` are exempt from the check —
they serve model ids the catalog cannot know — with the consequence stated where it bites:
cost caps do not bind on the first two.

**Router aliases are not pinned models.** An `auto/*` route resolves differently per call
and can disagree with what served the request, so it is never recorded as a disclosed model;
what actually answered is.

## Configuration surface

Threaded through `RunConfig`. Every default reproduces existing behaviour exactly, so an
account that has never touched Settings is indistinguishable from one with everything set to
the default.

| Field | Default | Consumed by |
|---|---|---|
| `retrieval_k` | 5 | `web_search`, when the model omits `max_results` |
| `min_sources_per_task` | 0 (no floor) | The critic — fails a task closed, without a model call, below the floor |
| `snippet_max_chars` | 500 | Truncation before validation; can only tighten the schema's own ceiling |
| `topic_seeds` | empty | The planner prompt, as a coverage floor |
| `outline_template` | unset | Resolved into the outline shown at the design gate |
| `max_planner_tasks` | 6 | What the planner may propose unprompted; the reviewer adds more at the gate |
| `skip_plan_gate` | `True` at the engine level | Routing after the planner — see below |
| `prompt_overrides` | empty | Declared, no consumer yet |

`skip_plan_gate` has three defaults and they disagree deliberately. The engine default is
`True`, so the CLI and the evaluation harness — neither of which can render or resume a
second interrupt — keep working unattended. The API request default is also `True`, so a
script posting an un-updated body is unaffected. The database column default is `False`.
Both start endpoints always set it explicitly, and the app's run form sends `false`, so the
gate is the product default. Making these three agree would break one of the three
populations.

## Design notes

Three decisions worth recording, because each replaced something that failed.

**A compiled graph rather than an orchestration loop.** `interrupt()` is a first-class
pause: the graph checkpoints durably and the worker process exits, and approval hours later
resumes the same state. In a hand-rolled loop, human-in-the-loop degenerates into "poll a
flag and hope the process is alive", which is a materially different and worse program.

**Budgets belong on edges, not in `if` statements.** Routing functions consult them, so
every path through the graph passes a check by construction. A new node cannot forget to
check the budget; it can only be placed on an edge that does.

**A caught provider error must surface its message.** Swallowing an exception into `None`
once produced "planner: could not produce a valid task list" for what was actually an
exhausted quota, and sent debugging in the wrong direction for days.
