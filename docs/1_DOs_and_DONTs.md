# 1. DOs and DON'Ts: Multi-Agent Research Assistant

> **Purpose**: This document is the **supreme law** for all development on this project. Any AI assistant, engineer, or contributor MUST read and comply with every rule here before writing a single line of code. Violations of these rules introduce production bugs, runaway API costs, and security vulnerabilities.

---

## Table of Contents
1. [Backend & Async Rules](#1-backend--async-rules)
2. [Type Safety & Schema Control](#2-type-safety--schema-control)
3. [State Management & Concurrency](#3-state-management--concurrency)
4. [Agent Loop Safety & Circuit Breakers](#4-agent-loop-safety--circuit-breakers)
5. [LLM Cost Control](#5-llm-cost-control)
6. [Security Rules](#6-security-rules)
7. [Prompt Engineering Rules](#7-prompt-engineering-rules)
8. [Frontend Rules](#8-frontend-rules)
9. [Database Rules](#9-database-rules)
10. [Testing & Observability Rules](#10-testing--observability-rules)

---

## 1. Backend & Async Rules

### ✅ DO: Use `async`/`await` for ALL I/O operations

Every database read, Redis call, HTTP request to an LLM API, and file I/O operation **must** be non-blocking.

```python
# ✅ CORRECT — Fully async FastAPI endpoint
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()

@router.post("/api/v1/research/start", status_code=202)
async def start_research(
    payload: ResearchStartRequest,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    session = Session(prompt=payload.query, status=SessionStatus.PENDING)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    # Queue the heavy agent work in a background Celery task
    run_agent_pipeline.delay(str(session.id))
    return {"session_id": str(session.id), "status": "PENDING"}
```

```python
# ❌ WRONG — Synchronous blocking call will freeze the entire event loop
@router.post("/api/v1/research/start")
def start_research(payload: ResearchStartRequest):   # Missing async!
    result = requests.post("https://api.openai.com/...")  # Blocking HTTP!
    return result.json()
```

### ✅ DO: Return `202 Accepted` immediately for long-running agent tasks

Agent pipelines take 1–5 minutes. The HTTP request must return a `job_id` immediately, never wait for completion.

```python
# ✅ CORRECT pattern
@router.post("/api/v1/research/start", status_code=202)
async def start_research(...):
    session_id = await create_session(db, payload)
    celery_task = run_agent_pipeline.delay(str(session_id))
    return ResearchStartResponse(session_id=session_id, task_id=celery_task.id)
```

### ❌ DON'T: Block the API with synchronous waits

```python
# ❌ NEVER DO THIS — Ties up a worker for minutes
@router.post("/api/v1/research/start")
async def start_research(...):
    result = await run_full_agent_pipeline(payload.query)  # Waits minutes!
    return result
```

---

## 2. Type Safety & Schema Control

### ✅ DO: Define strict Pydantic v2 models for every API boundary

```python
# ✅ CORRECT — Pydantic v2 strict models
from pydantic import BaseModel, Field, field_validator
from uuid import UUID
from enum import Enum

class ResearchDepth(str, Enum):
    FAST = "fast"
    BALANCED = "balanced"
    COMPREHENSIVE = "comprehensive"

class ResearchStartRequest(BaseModel):
    model_config = {"str_strip_whitespace": True}

    query: str = Field(
        ...,
        min_length=10,
        max_length=2000,
        description="The research question or topic to investigate.",
        examples=["Analyze AI investments in healthcare Q3 2024"]
    )
    depth: ResearchDepth = Field(
        default=ResearchDepth.BALANCED,
        description="Controls research thoroughness vs. speed."
    )
    sources: list[str] = Field(
        default=["web"],
        description="Data sources to query: 'web', 'academic', 'internal_db'."
    )

    @field_validator("query")
    @classmethod
    def query_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Query cannot be blank or whitespace.")
        return v
```

### ✅ DO: Use `TypedDict` for the LangGraph state — never plain dicts

```python
# ✅ CORRECT — Fully typed LangGraph state
from typing import TypedDict, Annotated
from langgraph.graph import add_messages

class AgentState(TypedDict):
    session_id: str
    original_query: str
    tasks: list[dict]           # Planner output: [{id, query, status}]
    current_task_index: int
    raw_context: list[dict]     # Executor output: [{task_id, content, url}]
    critic_feedback: str | None
    critic_loop_count: int      # CRITICAL: must be checked against recursion_limit
    synthesized_draft: str | None
    final_report: str | None
    total_tokens_used: int
    total_cost_usd: float
    error: str | None
```

### ❌ DON'T: Pass raw untyped dicts between agents

```python
# ❌ WRONG — Completely untyped, breaks observability
def executor_node(state: dict):
    state["stuff"] = "some result"  # What is 'stuff'? Nobody knows.
    return state
```

---

## 3. State Management & Concurrency

### ✅ DO: Use Redis for ephemeral session locks and graph state

When 1,000+ sessions run concurrently, you MUST use distributed locks to prevent race conditions when multiple workers try to write to the same session state.

```python
# ✅ CORRECT — Redis-backed distributed lock pattern
import asyncio
from redis.asyncio import Redis

async def acquire_session_lock(redis: Redis, session_id: str, timeout: int = 30) -> bool:
    """Acquire a distributed lock for a session. Returns True if acquired."""
    lock_key = f"lock:session:{session_id}"
    return await redis.set(lock_key, "1", ex=timeout, nx=True)

async def release_session_lock(redis: Redis, session_id: str) -> None:
    lock_key = f"lock:session:{session_id}"
    await redis.delete(lock_key)
```

### ❌ DON'T: Use in-memory Python dicts/globals for session state

```python
# ❌ CATASTROPHICALLY WRONG — Does not work across multiple worker processes
ACTIVE_SESSIONS = {}  # This is process-local; other Celery workers can't see it

def start_session(session_id: str):
    ACTIVE_SESSIONS[session_id] = {"status": "running"}  # Will be lost!
```

### ✅ DO: Separate the API tier from the Agent worker tier

- `api-service`: Handles HTTP requests, WebSocket connections, authentication. **No LLM calls**.
- `agent-worker-service`: Celery workers that run LangGraph pipelines. **No direct HTTP client connections**.

---

## 4. Agent Loop Safety & Circuit Breakers

### ✅ DO: Enforce a hard `recursion_limit` of 3 on all Critic→Executor cycles

```python
# ✅ CORRECT — LangGraph graph with explicit loop limit enforced in state
def route_after_critic(state: AgentState) -> str:
    """Conditional edge: routes back to executor or forward to synthesizer."""
    MAX_CRITIC_LOOPS = 3

    if state["critic_loop_count"] >= MAX_CRITIC_LOOPS:
        # Graceful fallback: log a warning and proceed with best available data
        logger.warning(
            f"Session {state['session_id']}: critic loop limit reached. "
            f"Proceeding to synthesis with best available context."
        )
        return "synthesizer"

    critic_result = state.get("critic_feedback", {})
    if not critic_result.get("passed", False):
        return "executor"  # Loop back

    return "synthesizer"  # Success path
```

### ✅ DO: Implement per-task timeouts with `asyncio.wait_for`

```python
# ✅ CORRECT — Executor tool calls never run forever
import asyncio

async def safe_tavily_search(query: str) -> list[dict]:
    try:
        return await asyncio.wait_for(
            tavily_client.search_async(query, search_depth="advanced"),
            timeout=15.0  # Hard 15-second cap per tool call
        )
    except asyncio.TimeoutError:
        logger.error(f"Tavily search timed out for query: '{query}'")
        return []  # Return empty, let Critic handle it
```

### ❌ DON'T: Rely solely on LangGraph's `recursion_limit` config

LangGraph's global `recursion_limit` counts ALL steps (nodes traversed), not loops specifically. Track your own `critic_loop_count` in state.

```python
# ❌ INSUFFICIENT — This only catches catastrophic runaway, not cost overruns
graph = graph_builder.compile(recursion_limit=10)  # Don't rely on this alone
```

---

## 5. LLM Cost Control

### ✅ DO: Implement a cost interceptor middleware on every LLM call

```python
# ✅ CORRECT — Centralized cost tracking wrapper
from langchain_core.callbacks import BaseCallbackHandler

# Pricing as of model versions in use (update when models change!)
MODEL_COST_PER_1K_TOKENS = {
    "claude-3-5-sonnet-20241022": {"input": 0.003, "output": 0.015},
    "gpt-4o-2024-11-20":          {"input": 0.0025, "output": 0.01},
}

class CostTrackingCallback(BaseCallbackHandler):
    def __init__(self, session_id: str, db_session: AsyncSession):
        self.session_id = session_id
        self.db = db_session
        self.accumulated_cost_usd = 0.0

    def on_llm_end(self, response, **kwargs):
        usage = response.llm_output.get("usage", {})
        model = response.llm_output.get("model_name", "unknown")
        pricing = MODEL_COST_PER_1K_TOKENS.get(model, {"input": 0, "output": 0})

        input_tokens  = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)

        cost = (input_tokens / 1000 * pricing["input"]) + \
               (output_tokens / 1000 * pricing["output"])

        self.accumulated_cost_usd += cost
        # Persist asynchronously — fire and forget
        asyncio.ensure_future(self._persist_cost(cost, input_tokens, output_tokens))

    async def _persist_cost(self, cost: float, in_tok: int, out_tok: int):
        await db_update_session_cost(self.db, self.session_id, cost)
```

### ✅ DO: Set a maximum per-session cost budget

```python
# ✅ CORRECT — Kill the pipeline if it's burning money
MAX_COST_PER_SESSION_USD = 0.50

def check_cost_budget(state: AgentState) -> str:
    if state["total_cost_usd"] >= MAX_COST_PER_SESSION_USD:
        raise ValueError(
            f"Session {state['session_id']} exceeded cost budget of "
            f"${MAX_COST_PER_SESSION_USD:.2f}. Aborting."
        )
    return "continue"
```

---

## 6. Security Rules

### ✅ DO: Validate and sanitize all user query inputs

```python
# ✅ CORRECT — Prevent prompt injection and oversized inputs
import re

PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+previous\s+instructions",
    r"you\s+are\s+now\s+.*?mode",
    r"<\|.*?\|>",  # Token-stuffing patterns
    r"system\s*:\s*",
]

def validate_query_safety(query: str) -> str:
    for pattern in PROMPT_INJECTION_PATTERNS:
        if re.search(pattern, query, re.IGNORECASE):
            raise ValueError("Query contains disallowed content.")
    return query
```

### ✅ DO: Store API keys ONLY in environment variables — never in source code

```bash
# ✅ CORRECT — Use .env files with python-dotenv (NEVER commit .env to git)
# .env (gitignored)
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
TAVILY_API_KEY=tvly-...
DATABASE_URL=postgresql+asyncpg://user:pass@localhost/research_db
REDIS_URL=redis://localhost:6379/0
```

### ❌ DON'T: Hardcode secrets anywhere in the codebase

```python
# ❌ CRITICAL SECURITY VIOLATION
client = openai.OpenAI(api_key="sk-proj-abc123...")  # NEVER EVER DO THIS
```

### ✅ DO: Use Row-Level Security for multi-tenant data

Users must only ever be able to access their own sessions. Enforce this at the DB query level, never rely only on the frontend.

```python
# ✅ CORRECT — Always scope queries to the authenticated user
async def get_session(db: AsyncSession, session_id: UUID, user_id: UUID) -> Session | None:
    result = await db.execute(
        select(Session).where(
            Session.id == session_id,
            Session.user_id == user_id  # ← Non-negotiable security filter
        )
    )
    return result.scalar_one_or_none()
```

---

## 7. Prompt Engineering Rules

### ✅ DO: Version control all system prompts in a dedicated config module

```python
# ✅ CORRECT — prompts/v1/planner.py
PLANNER_PROMPT_V1 = """..."""

# prompts/v2/planner.py — can be deployed without redeploying the entire app
PLANNER_PROMPT_V2 = """..."""
```

### ✅ DO: Always include output format enforcement in every prompt

Every agent prompt MUST end with an explicit "Output Format" section that specifies the exact JSON schema the LLM must produce.

### ❌ DON'T: Use a single generic prompt for all agents

```python
# ❌ WRONG — One vague prompt for everything
AGENT_PROMPT = "You are a helpful AI. Do the research task."
```

### ❌ DON'T: Pass raw unverified LLM output directly to downstream functions

```python
# ❌ WRONG — What if the LLM returns malformed JSON?
raw_output = llm.invoke(planner_prompt)
tasks = json.loads(raw_output.content)  # Will crash on malformed JSON
run_tasks(tasks)
```

```python
# ✅ CORRECT — Always validate with Pydantic before using LLM output
from pydantic import ValidationError

class PlannerOutput(BaseModel):
    tasks: list[Task]

try:
    planner_result = PlannerOutput.model_validate_json(raw_output.content)
except ValidationError as e:
    logger.error(f"Planner produced invalid JSON: {e}")
    # Trigger retry or fallback gracefully
```

---

## 8. Frontend Rules

### ✅ DO: Use SSE (Server-Sent Events) for live agent log streaming

```typescript
// ✅ CORRECT — SSE hook using the EventSource API
import { useEffect, useRef, useState } from "react";

export function useAgentStream(sessionId: string) {
  const [logs, setLogs] = useState<AgentLog[]>([]);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!sessionId) return;
    esRef.current = new EventSource(`/api/v1/research/${sessionId}/stream`);

    esRef.current.onmessage = (event) => {
      const log: AgentLog = JSON.parse(event.data);
      setLogs((prev) => [...prev, log]);
    };

    esRef.current.onerror = () => esRef.current?.close();

    return () => esRef.current?.close(); // ← Cleanup on unmount!
  }, [sessionId]);

  return logs;
}
```

### ❌ DON'T: Poll the status endpoint in a tight loop

```typescript
// ❌ WRONG — Creates 100s of unnecessary HTTP requests
useEffect(() => {
  const interval = setInterval(async () => {
    const res = await fetch(`/api/v1/research/${sessionId}/status`);
    // ...
  }, 500); // 2 requests/second per user — does not scale
  return () => clearInterval(interval);
}, [sessionId]);
```

### ✅ DO: Handle loading, error, and empty states in every component

Every async data display must explicitly handle all three states to prevent blank-screen user experiences.

---

## 9. Database Rules

### ✅ DO: Use Alembic for all schema migrations — never `Base.metadata.create_all()` in production

```bash
# ✅ CORRECT workflow
alembic revision --autogenerate -m "add_agent_logs_table"
alembic upgrade head
```

```python
# ❌ NEVER DO THIS IN PRODUCTION — destroys migration history
await engine.execute(Base.metadata.create_all())
```

### ✅ DO: Always use database transactions for multi-step writes

```python
# ✅ CORRECT — Atomic: either both writes succeed or neither does
async with db.begin():
    db.add(session)
    db.add(initial_log)
    # Commit happens automatically at end of `async with` block
```

---

## 10. Testing & Observability Rules

### ✅ DO: Write integration tests for every agent node in isolation

```python
# ✅ CORRECT — Test the planner node in isolation with a mock LLM
async def test_planner_node_produces_valid_tasks():
    mock_llm = MockLLM(response='{"tasks": [{"id": 1, "query": "test"}]}')
    state = AgentState(original_query="test query", ...)
    result = await planner_node(state, llm=mock_llm)
    assert len(result["tasks"]) >= 1
```

### ✅ DO: Emit structured logs with `session_id` in every log line

```python
# ✅ CORRECT — Structured logging for distributed tracing
import structlog

logger = structlog.get_logger()

async def executor_node(state: AgentState) -> AgentState:
    log = logger.bind(session_id=state["session_id"], node="executor")
    log.info("executor_started", task=state["tasks"][state["current_task_index"]])
    # ...
    log.info("executor_finished", sources_found=len(state["raw_context"]))
```

### ❌ DON'T: Use `print()` for logging in any production code path

```python
# ❌ WRONG — print() has no severity, no structure, no correlation ID
print("Agent started")
print(f"Got result: {result}")
```
