# 5. Project Roadmap

> **Purpose**: Defines the phased execution plan for building the Multi-Agent Research Assistant. Each milestone builds on the last and delivers a demonstrable, testable outcome. Do not start Milestone N+1 until Milestone N's deliverable is verified.

---

## Table of Contents
1. [Guiding Philosophy](#1-guiding-philosophy)
2. [Milestone Overview](#2-milestone-overview)
3. [Milestone 1: Core Scaffolding & Infrastructure](#3-milestone-1-core-scaffolding--infrastructure-week-1)
4. [Milestone 2: Multi-Agent Orchestration](#4-milestone-2-multi-agent-orchestration-week-2)
5. [Milestone 3: HITL Gate & Persistence](#5-milestone-3-hitl-gate--persistence-week-3)
6. [Milestone 4: Scaling & Productionization](#6-milestone-4-scaling--productionization-week-4)
7. [Future Milestones (Post-MVP)](#7-future-milestones-post-mvp)
8. [Risk Register](#8-risk-register)
9. [Definition of Done (for all milestones)](#9-definition-of-done-for-all-milestones)

---

## 1. Guiding Philosophy

### Build Vertically, Not Horizontally

Each milestone delivers a **complete, testable vertical slice** of the system. We never build all the database models before any API endpoints; we never build all agents before testing one.

```
❌ Horizontal (wrong):
  Week 1: All DB models
  Week 2: All API endpoints
  Week 3: All agents
  Week 4: Frontend
  → Nothing testable until week 4

✅ Vertical (correct, our approach):
  Week 1: One endpoint + one agent + minimal UI → Chatbot works end-to-end
  Week 2: Add Planner + Executor + Critic → Full pipeline works
  Week 3: Add HITL + persistence → Users can approve/reject
  Week 4: Add scaling + cost tracking → Production-ready
```

### The "Walking Skeleton" Principle

At the end of every milestone, a demo user must be able to:
1. Open the browser
2. Type a research question
3. See something meaningful happen
4. Get a result

---

## 2. Milestone Overview

```
Week 1          Week 2          Week 3          Week 4
┌───────────┐   ┌───────────┐   ┌───────────┐   ┌───────────┐
│ M1: Core  │──►│ M2: Multi │──►│ M3: HITL  │──►│ M4: Scale │
│ Scaffold  │   │  Agent    │   │  & State  │   │  & Prod   │
│           │   │  Pipeline │   │           │   │           │
│ Deliverable   │ Deliverable   │ Deliverable   │ Deliverable
│ Single LLM│   │ Planner + │   │ System    │   │ 1,000+    │
│ chatbot   │   │ Executor+ │   │ pauses &  │   │ concurrent│
│ with SSE  │   │ Critic    │   │ resumes   │   │ sessions  │
└───────────┘   └───────────┘   └───────────┘   └───────────┘
```

---

## 3. Milestone 1: Core Scaffolding & Infrastructure (Week 1)

### Goal

Establish the complete foundational infrastructure and deliver a working end-to-end "chatbot" — a single LLM executor that can accept a query, search the web, and stream the result back to the browser via SSE.

### Tech Decisions for M1

- **Frontend**: Next.js 14 (App Router) with TailwindCSS
- **Backend**: FastAPI with `uvicorn`
- **LLM**: OpenAI GPT-4o (primary) + Google Gemini 1.5 Flash (fallback)
- **Search**: DuckDuckGo Search (free, no API key required)
- **Database**: PostgreSQL via Docker Compose (async SQLAlchemy)
- **Queue/Cache**: Redis via Docker Compose
- **Auth**: JWT-based (simple email/password for MVP)

### Deliverables

#### Backend

- [ ] `docker-compose.yml` — PostgreSQL 15, Redis 7 containers
- [ ] FastAPI app factory with lifespan hooks, CORS, health endpoint
- [ ] Async SQLAlchemy setup with asyncpg driver
- [ ] Alembic migration: create `users`, `sessions`, `agent_logs` tables
- [ ] `POST /api/v1/research/start` — creates session, queues Celery task, returns `session_id`
- [ ] `GET /api/v1/research/{session_id}/status` — returns session status + metadata
- [ ] `GET /api/v1/research/{session_id}/stream` — SSE endpoint (Redis pub/sub)
- [ ] Single LangChain executor with DuckDuckGo search tool
- [ ] `CostTrackingCallback` — intercepts token usage, updates session cost in Postgres
- [ ] Celery worker that runs the single executor and publishes log events to Redis
- [ ] Structured logging with `structlog`

#### Frontend (Next.js)

- [ ] Dark mode design system (Tailwind config with custom color tokens)
- [ ] `/dashboard` — Input Dashboard with query form, depth selector, source toggles
- [ ] `/session/[sessionId]` — Routes to Brain Monitor or ExportView based on status
- [ ] `BrainMonitor` component — Left panel (plan) + right panel (SSE log feed)
- [ ] `ExportView` component — Final answer + analytics bar
- [ ] `useAgentStream` SSE hook
- [ ] `useResearchStore` Zustand store
- [ ] TanStack Query setup for status polling

#### Infrastructure

- [ ] `docker-compose.yml` (local dev)
- [ ] `.env.example` with all required variables documented
- [ ] `Makefile` with: `make dev`, `make migrate`, `make worker`, `make test`

### Acceptance Criteria for M1

```gherkin
Feature: Single Agent Web Search

Scenario: User queries for AI news
  Given I am on the /dashboard page
  When I type "What are the latest developments in AI agents in 2024?"
  And I click "Start Research"
  Then I am redirected to /session/{sessionId}
  And within 2 seconds the Brain Monitor shows at least one log entry
  And the Executor performs a DuckDuckGo search
  And within 90 seconds the result appears in the Export View
  And the analytics bar shows cost > $0.00

Scenario: SSE stream connects and delivers events
  Given a session is in RUNNING status
  When I connect to GET /api/v1/research/{sessionId}/stream
  Then I receive agent_log events in real-time
  And the stream terminates with a COMPLETED event
```

---

## 4. Milestone 2: Multi-Agent Orchestration (Week 2)

### Goal

Replace the single LangChain executor with a full LangGraph state machine: Planner → Executor → Critic (with self-correction loop) → Synthesizer.

### Deliverables

#### Agent Pipeline

- [ ] `AgentState` TypedDict (session_id, tasks, raw_context, critic_feedback, critic_loop_count, etc.)
- [ ] `planner_node` — calls GPT-4o with `PLANNER_PROMPT`, parses JSON task list with Pydantic
- [ ] `executor_node` — picks current task from state, runs DuckDuckGo + `read_webpage` tools
- [ ] `critic_node` — calls Gemini Flash (cost optimization) with `CRITIC_PROMPT`, outputs pass/fail JSON
- [ ] `synthesizer_node` — compiles all `ContextChunk` objects into structured Markdown
- [ ] `route_after_critic()` — conditional edge with `critic_loop_count` circuit breaker (max 3)
- [ ] `error_handler_node` — graceful fallback when budget/loop limit exceeded
- [ ] LangGraph graph compilation with all nodes and edges
- [ ] LangSmith tracing integration (`LANGCHAIN_TRACING_V2=true`)

#### API Changes

- [ ] `AgentLog` writes for every node: `agent_name`, `action`, `result`, `timestamp`
- [ ] SSE publishes richer event types: `node_started`, `tool_called`, `critic_result`, `synthesis_started`
- [ ] Session `status` transitions: PENDING → RUNNING → COMPLETED/FAILED

#### Frontend Changes

- [ ] Plan panel dynamically shows tasks with status icons (⏳ → 🔄 → ✅/❌)
- [ ] Log feed shows critic pass/fail events with distinct color coding
- [ ] Progress bar calculates completion based on `current_task_index / tasks.length`

### Acceptance Criteria for M2

```gherkin
Scenario: Multi-step research with self-correction
  Given I submit query "Analyze top 5 AI startups that raised funding in Q3 2024"
  Then the Planner generates 3-5 search tasks
  And the Executor performs a web search for each task
  And the Critic evaluates each result
  And if Critic fails, the Executor retries (max 3 times per task)
  And the Synthesizer compiles all passed context into a structured Markdown report
  And the session moves to COMPLETED status
  And the final report contains at least 3 distinct cited sources
  And the critic_loop_count never exceeds 3 for any single task
```

---

## 5. Milestone 3: HITL Gate & Persistence (Week 3)

### Goal

Implement the Human-in-the-Loop interrupt pattern: the graph pauses before finalization, the user reviews the draft in the UI, and the graph resumes based on their decision.

### Deliverables

#### Persistence Layer

- [ ] LangGraph `AsyncRedisSaver` checkpointer — saves full graph state to Redis after each node
- [ ] Postgres backup of checkpoint: store serialized state in `sessions.checkpoint_data` column
- [ ] Alembic migration: add `checkpoint_data` (JSONB) and `draft_report` (Text) columns to `sessions`

#### HITL Implementation

- [ ] `hitl_gate_node` — writes draft to Postgres, sets `status=AWAITING_APPROVAL`, publishes `HITL_READY` SSE event
- [ ] `interrupt_before=["hitl_gate"]` in graph compilation
- [ ] `POST /api/v1/research/{session_id}/approve` endpoint:
  - Loads checkpoint from Redis
  - Injects `human_feedback` into state if rework requested
  - Resumes graph from checkpoint
- [ ] `finalizer_node` — generates PDF (weasyprint), saves final report, sets `status=COMPLETED`

#### Frontend Changes

- [ ] `HITLApprovalGate` component — split-screen layout (draft | decision panel)
- [ ] Markdown preview with proper code block and table rendering (use `react-markdown`)
- [ ] Quality signals panel: citation count, confidence indicator
- [ ] Rework feedback textarea with validation (required before submit)
- [ ] Loading states for both Approve and Rework actions
- [ ] Auto-redirect to Brain Monitor after "Rework" (agent is running again)

### Acceptance Criteria for M3

```gherkin
Scenario: HITL gate pauses and resumes (approve flow)
  Given a research session reaches the synthesis stage
  When the Synthesizer finishes the draft
  Then the session status changes to AWAITING_APPROVAL
  And the HITL Approval Gate component renders in the browser
  And the draft is visible in the left panel
  When I click "Approve & Finalize"
  Then the session status changes to COMPLETED
  And a PDF is available for download

Scenario: HITL gate pauses and resumes (rework flow)
  Given the HITL Approval Gate is displayed
  When I click "Reject & Rework" without providing feedback
  Then I see a validation error: "Please provide feedback"
  When I type "Include more data on European AI market" and click "Reject & Rework"
  Then the session status changes back to RUNNING
  And the Brain Monitor shows the agent is researching again
  And the new draft incorporates the feedback topic
```

---

## 6. Milestone 4: Scaling & Productionization (Week 4)

### Goal

Harden the system for production-scale: 1,000+ concurrent sessions, cost monitoring dashboard, containerized deployment, Kubernetes manifests, and end-to-end observability.

### Deliverables

#### Scaling Infrastructure

- [ ] Celery worker configuration:
  - `worker_prefetch_multiplier=1` (one heavy task per worker)
  - `task_acks_late=True` (don't lose tasks on worker crash)
  - Dead Letter Queue (DLQ) for failed tasks
- [ ] Redis Cluster mode configuration for high availability
- [ ] Postgres read replica for status polling (write to primary, read replica for `GET /status`)
- [ ] Kubernetes manifests:
  - `api-deployment.yaml` (3 replicas, HPA on CPU)
  - `worker-deployment.yaml` (2 baseline replicas, KEDA scaling on Redis queue depth)
  - `postgres-statefulset.yaml`
  - `redis-statefulset.yaml`
  - `ingress.yaml` (with TLS termination)
- [ ] KEDA `ScaledObject` for worker auto-scaling (2→50 replicas based on queue depth)

#### Cost Monitoring

- [ ] Real-time cost dashboard at `/admin/costs`:
  - Cost per session histogram
  - Daily spend by model (GPT-4o vs Gemini Flash)
  - Alert: email notification if daily spend > $100
- [ ] Per-user cost limits: configurable monthly budget cap
- [ ] Cost report API: `GET /api/v1/admin/costs/summary?period=day|week|month`

#### Security Hardening

- [ ] Rate limiting per user: 5 sessions/hour (Redis `INCR` with TTL)
- [ ] API key rotation: support multiple LLM API keys with round-robin selection
- [ ] Input sanitization: regex-based prompt injection detection
- [ ] Audit logging: every session start/approve/finalize logged with user IP

#### Observability

- [ ] Prometheus metrics endpoint: `GET /metrics`
- [ ] Grafana dashboard: active sessions, queue depth, cost/hour, p99 latency
- [ ] LangSmith project configured with all traces tagged by `session_id`
- [ ] Sentry integration for exception tracking

#### CI/CD

- [ ] GitHub Actions workflow:
  - `test.yml`: Run pytest on every PR
  - `deploy.yml`: Build Docker images, push to registry, apply K8s manifests on merge to `main`
- [ ] `Dockerfile` for both `api-service` and `agent-worker-service` (multi-stage, minimal image)

### Acceptance Criteria for M4

```gherkin
Scenario: System handles 100 concurrent sessions
  Given 100 sessions are started simultaneously
  Then all sessions complete within 10 minutes
  And no session fails due to resource contention
  And the Celery worker count auto-scales to handle the queue
  And the total cost for all 100 sessions is tracked accurately

Scenario: Cost budget enforcement
  Given a user's session is configured with a $0.50 budget
  When the accumulated cost reaches $0.50
  Then the agent pipeline is stopped gracefully
  And the session status is set to FAILED with reason "Budget exceeded"
  And the user sees a clear error message in the UI
```

---

## 7. Future Milestones (Post-MVP)

These features are explicitly out of scope for the initial 4-week build but are planned for future releases:

| Milestone | Feature | Priority | Notes |
|---|---|---|---|
| **M5** | Internal document search (PDF, Notion, Confluence) | High | Requires vector DB (Pinecone/Weaviate), chunking pipeline |
| **M6** | Academic paper search (PubMed, arXiv, Semantic Scholar) | High | Adds a new Executor tool; critical for research persona |
| **M7** | Parallel task execution (multiple Executors running concurrently) | Medium | LangGraph fan-out/fan-in pattern; reduces total time by ~60% |
| **M8** | Scheduled recurring research | Medium | Cron-based session initiation; email delivery of reports |
| **M9** | Multi-user session collaboration | Low | CRDTs or operational transformation for shared HITL review |
| **M10** | Fine-tuned Critic model | Low | Train a domain-specific critic on historical pass/fail data |

---

## 8. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| LLM API rate limits block Executor | Medium | High | Implement retry with exponential backoff; rotate between GPT-4o and Gemini |
| DuckDuckGo search is too slow or unreliable | Medium | Medium | Add SerpAPI or Brave Search as fallback; cache identical queries |
| Redis memory fills up with graph checkpoints | Low | High | Set TTL of 24 hours on all checkpoint keys; archive to Postgres |
| Postgres connection pool exhaustion | Medium | High | Use `pgbouncer` connection pooler; tune pool size to worker count |
| LangGraph library breaking changes | Low | High | Pin exact version in `requirements.txt`; write integration tests against pinned version |
| User provides adversarial query (prompt injection) | Medium | High | Regex sanitization in Pydantic validator; never pass raw user input to system prompt |

---

## 9. Definition of Done (for all milestones)

A milestone is "done" when ALL of the following are true:

- [ ] All acceptance criteria pass
- [ ] All new code has at least 1 unit test and 1 integration test
- [ ] `make test` exits with code 0
- [ ] `docker-compose up` starts all services without errors
- [ ] A pull request has been reviewed and merged to `main`
- [ ] The README is updated with any new setup steps
- [ ] All secrets are stored in `.env` and documented in `.env.example`
- [ ] No hardcoded API keys, URLs, or credentials exist in the codebase (checked by `grep -r "sk-" .`)
