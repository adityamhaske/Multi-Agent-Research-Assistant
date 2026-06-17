# 6. Data Models & API Specifications

> **Purpose**: The single source of truth for all database schemas, API contracts, and data transfer objects. Any change to database schemas must be preceded by an Alembic migration. Any change to API contracts must be reflected in both the Pydantic schemas and the OpenAPI docs.

---

## Table of Contents
1. [PostgreSQL Schema](#1-postgresql-schema)
2. [SQLAlchemy ORM Models](#2-sqlalchemy-orm-models)
3. [Alembic Migration Strategy](#3-alembic-migration-strategy)
4. [Pydantic v2 API Schemas](#4-pydantic-v2-api-schemas)
5. [API Endpoint Contracts](#5-api-endpoint-contracts)
6. [SSE Event Schema](#6-sse-event-schema)
7. [Redis Key Conventions](#7-redis-key-conventions)
8. [Error Response Format](#8-error-response-format)

---

## 1. PostgreSQL Schema

### Entity Relationship Diagram

```
┌─────────────┐         ┌──────────────────────────┐        ┌─────────────────┐
│   users     │         │        sessions           │        │   agent_logs    │
├─────────────┤         ├──────────────────────────┤        ├─────────────────┤
│ id (UUID PK)│◄────────│ id (UUID PK)              │◄───────│ id (SERIAL PK)  │
│ email       │   1:N   │ user_id (UUID FK)         │  1:N   │ session_id (FK) │
│ hashed_pw   │         │ prompt (TEXT)             │        │ agent_name      │
│ created_at  │         │ status (ENUM)             │        │ action (TEXT)   │
│ is_active   │         │ research_depth (VARCHAR)  │        │ result (JSONB)  │
└─────────────┘         │ selected_sources (JSONB)  │        │ timestamp       │
                        │ total_cost_usd (NUMERIC)  │        └─────────────────┘
                        │ total_tokens_input (INT)  │
                        │ total_tokens_output (INT) │
                        │ elapsed_seconds (FLOAT)   │
                        │ draft_report (TEXT)       │
                        │ final_report (TEXT)       │
                        │ checkpoint_data (JSONB)   │
                        │ error_message (TEXT)      │
                        │ created_at (TIMESTAMPTZ)  │
                        │ updated_at (TIMESTAMPTZ)  │
                        └──────────────────────────┘
```

### Session Status State Machine

```
PENDING ──► RUNNING ──► AWAITING_APPROVAL ──► COMPLETED
                │                                 ▲
                │              ┌──────────────────┘
                │              │ (resume after rework)
                └──► FAILED    └──► RUNNING (rework loop)
```

### Full DDL (Reference — use Alembic for actual migrations)

```sql
-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- users table
CREATE TABLE users (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email       VARCHAR(255) UNIQUE NOT NULL,
    hashed_pw   VARCHAR(255) NOT NULL,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_users_email ON users(email);

-- Session status enum
CREATE TYPE session_status AS ENUM (
    'PENDING', 'RUNNING', 'AWAITING_APPROVAL', 'COMPLETED', 'FAILED'
);

-- sessions table
CREATE TABLE sessions (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    prompt              TEXT NOT NULL,
    status              session_status NOT NULL DEFAULT 'PENDING',
    research_depth      VARCHAR(20) NOT NULL DEFAULT 'balanced',
    selected_sources    JSONB NOT NULL DEFAULT '["web"]',
    total_cost_usd      NUMERIC(10, 6) NOT NULL DEFAULT 0.0,
    total_tokens_input  INTEGER NOT NULL DEFAULT 0,
    total_tokens_output INTEGER NOT NULL DEFAULT 0,
    elapsed_seconds     FLOAT,
    draft_report        TEXT,
    final_report        TEXT,
    checkpoint_data     JSONB,   -- Serialized LangGraph checkpoint
    error_message       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_sessions_user_id ON sessions(user_id);
CREATE INDEX ix_sessions_status  ON sessions(status);

-- agent_logs table
CREATE TABLE agent_logs (
    id          BIGSERIAL PRIMARY KEY,
    session_id  UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    agent_name  VARCHAR(50) NOT NULL,  -- planner|executor|critic|synthesizer|system
    action      TEXT NOT NULL,
    result      JSONB,
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_agent_logs_session_id  ON agent_logs(session_id);
CREATE INDEX ix_agent_logs_timestamp   ON agent_logs(timestamp DESC);
```

---

## 2. SQLAlchemy ORM Models

```python
# app/models/base.py
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import MetaData

# Naming convention for Alembic to generate constraint names automatically
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=convention)
```

```python
# app/models/user.py
import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

class User(Base):
    __tablename__ = "users"

    id:         Mapped[uuid.UUID]   = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email:      Mapped[str]         = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_pw:  Mapped[str]         = mapped_column(String(255), nullable=False)
    is_active:  Mapped[bool]        = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime]    = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationship
    sessions:   Mapped[list["Session"]] = relationship("Session", back_populates="user", lazy="select")
```

```python
# app/models/session.py
import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, Float, Integer, Enum as SAEnum, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base
import enum

class SessionStatus(str, enum.Enum):
    PENDING           = "PENDING"
    RUNNING           = "RUNNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    COMPLETED         = "COMPLETED"
    FAILED            = "FAILED"

class Session(Base):
    __tablename__ = "sessions"

    id:                  Mapped[uuid.UUID]        = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id:             Mapped[uuid.UUID]        = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    prompt:              Mapped[str]              = mapped_column(Text, nullable=False)
    status:              Mapped[SessionStatus]    = mapped_column(SAEnum(SessionStatus), nullable=False, default=SessionStatus.PENDING, index=True)
    research_depth:      Mapped[str]              = mapped_column(String(20), nullable=False, default="balanced")
    selected_sources:    Mapped[list]             = mapped_column(JSONB, nullable=False, default=list)
    total_cost_usd:      Mapped[float]            = mapped_column(Float, nullable=False, default=0.0)
    total_tokens_input:  Mapped[int]              = mapped_column(Integer, nullable=False, default=0)
    total_tokens_output: Mapped[int]              = mapped_column(Integer, nullable=False, default=0)
    elapsed_seconds:     Mapped[Optional[float]]  = mapped_column(Float, nullable=True)
    draft_report:        Mapped[Optional[str]]    = mapped_column(Text, nullable=True)
    final_report:        Mapped[Optional[str]]    = mapped_column(Text, nullable=True)
    checkpoint_data:     Mapped[Optional[dict]]   = mapped_column(JSONB, nullable=True)
    error_message:       Mapped[Optional[str]]    = mapped_column(Text, nullable=True)
    created_at:          Mapped[datetime]         = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at:          Mapped[datetime]         = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user:       Mapped["User"]          = relationship("User", back_populates="sessions")
    agent_logs: Mapped[list["AgentLog"]] = relationship("AgentLog", back_populates="session", cascade="all, delete-orphan", lazy="select")
```

```python
# app/models/agent_log.py
import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, DateTime, ForeignKey, func, BigInteger
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

class AgentLog(Base):
    __tablename__ = "agent_logs"

    id:         Mapped[int]            = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_name: Mapped[str]            = mapped_column(String(50), nullable=False)
    action:     Mapped[str]            = mapped_column(Text, nullable=False)
    result:     Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    timestamp:  Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Relationship
    session: Mapped["Session"] = relationship("Session", back_populates="agent_logs")
```

---

## 3. Alembic Migration Strategy

### Setup

```bash
# Initialize Alembic (run once)
alembic init alembic

# Generate initial migration from models
alembic revision --autogenerate -m "initial_schema"

# Apply migration
alembic upgrade head

# Rollback one step
alembic downgrade -1
```

### `alembic/env.py` (Async Configuration)

```python
# alembic/env.py
import asyncio
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine
from alembic import context
from app.config import settings
from app.models.base import Base

# Import all models so Alembic can detect them
from app.models import user, session, agent_log  # noqa: F401

config = context.config
fileConfig(config.config_file_name)

target_metadata = Base.metadata

def run_migrations_offline():
    context.configure(url=settings.DATABASE_URL, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()

def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()

async def run_migrations_online():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()

if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

---

## 4. Pydantic v2 API Schemas

```python
# app/schemas/research.py
from pydantic import BaseModel, Field, field_validator
from uuid import UUID
from datetime import datetime
from typing import Optional
from app.models.session import SessionStatus

# ─── Request Schemas ───────────────────────────────────────────────────────────

class ResearchStartRequest(BaseModel):
    model_config = {"str_strip_whitespace": True}

    query: str = Field(
        ...,
        min_length=10,
        max_length=2000,
        description="The research question or topic.",
        examples=["Analyze AI investments in healthcare Q3 2024"]
    )
    depth: str = Field(
        default="balanced",
        pattern="^(fast|balanced|comprehensive)$",
        description="Research thoroughness level."
    )
    sources: list[str] = Field(
        default=["web"],
        description="Data sources: 'web', 'academic', 'internal'."
    )

    @field_validator("sources")
    @classmethod
    def validate_sources(cls, v: list[str]) -> list[str]:
        allowed = {"web", "academic", "internal"}
        invalid = set(v) - allowed
        if invalid:
            raise ValueError(f"Invalid sources: {invalid}. Must be one of {allowed}")
        return v

class ApprovalRequest(BaseModel):
    approved: bool = Field(..., description="True = approve and finalize; False = reject and rework.")
    feedback: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Required if approved=False. Instructions for the agent on what to improve."
    )

    @field_validator("feedback")
    @classmethod
    def feedback_required_on_reject(cls, v: Optional[str], info) -> Optional[str]:
        if info.data.get("approved") is False and (not v or not v.strip()):
            raise ValueError("Feedback is required when rejecting a draft.")
        return v

# ─── Response Schemas ──────────────────────────────────────────────────────────

class ResearchStartResponse(BaseModel):
    session_id: UUID
    status: SessionStatus
    message: str = "Research session created and queued."

class AgentLogSchema(BaseModel):
    id: int
    session_id: UUID
    agent_name: str
    action: str
    result: Optional[dict] = None
    timestamp: datetime

    model_config = {"from_attributes": True}

class SessionStatusResponse(BaseModel):
    session_id: UUID
    status: SessionStatus
    prompt: str
    research_depth: str
    total_cost_usd: float
    total_tokens_input: int
    total_tokens_output: int
    elapsed_seconds: Optional[float]
    draft_report: Optional[str]
    final_report: Optional[str]
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
```

```python
# app/schemas/auth.py
from pydantic import BaseModel, Field, EmailStr

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
```

---

## 5. API Endpoint Contracts

### Authentication Endpoints

```
POST /api/v1/auth/register
  Request:  RegisterRequest
  Response: { "message": "User created successfully." }
  Errors:   409 Conflict (email already registered)

POST /api/v1/auth/login
  Request:  LoginRequest
  Response: TokenResponse
  Errors:   401 Unauthorized (invalid credentials)
            403 Forbidden (account deactivated)

POST /api/v1/auth/refresh
  Request:  { "refresh_token": "..." }
  Response: TokenResponse
```

### Research Endpoints

```
POST /api/v1/research/start
  Auth:     Required (JWT Bearer)
  Request:  ResearchStartRequest
  Response: 202 ResearchStartResponse
  Errors:   422 Validation error
            429 Too Many Requests (rate limit: 5/hour)

GET /api/v1/research/{session_id}/status
  Auth:     Required
  Response: 200 SessionStatusResponse
  Errors:   404 Not Found
            403 Forbidden (session belongs to another user)

GET /api/v1/research/{session_id}/stream
  Auth:     Required
  Response: 200 text/event-stream (SSE)
            Streams AgentLog events until COMPLETED/FAILED/HITL_READY
  Headers:  Cache-Control: no-cache
            X-Accel-Buffering: no

POST /api/v1/research/{session_id}/approve
  Auth:     Required
  Request:  ApprovalRequest
  Response: 200 { "message": "Approved. Finalizing report." }
          | 200 { "message": "Rework requested. Agent is resuming." }
  Errors:   404 Not Found
            409 Conflict (session not in AWAITING_APPROVAL status)
            422 Validation error (feedback missing on reject)

GET /api/v1/research/{session_id}/export
  Auth:     Required
  Query params: format=pdf|docx|markdown
  Response: 200 File stream (application/pdf | application/vnd.openxmlformats...)
  Errors:   404 Not Found
            409 Conflict (session not in COMPLETED status)

GET /api/v1/research/
  Auth:     Required
  Query params: page=1&limit=20&status=COMPLETED
  Response: 200 { "sessions": [SessionStatusResponse...], "total": 42 }
```

---

## 6. SSE Event Schema

All SSE messages follow this envelope:

```typescript
interface SSEEvent {
  type: SSEEventType;
  timestamp: string;   // ISO 8601
  data: object;        // Type-specific payload
}

type SSEEventType =
  | "connected"          // Handshake on connect
  | "agent_log"          // New AgentLog entry
  | "node_started"       // A new graph node started
  | "tool_called"        // Executor invoked a tool
  | "tool_result"        // Tool returned a result
  | "critic_result"      // Critic pass/fail judgment
  | "HITL_READY"         // Draft ready for review
  | "COMPLETED"          // Session successfully finished
  | "FAILED"             // Session failed with error
  | "cost_update"        // Real-time cost update
```

#### Event Examples

```json
// agent_log event
{
  "type": "agent_log",
  "timestamp": "2024-11-15T17:04:08Z",
  "data": {
    "id": 42,
    "session_id": "a3f8b9c2-...",
    "agent_name": "executor",
    "action": "Searching web for: 'AI investments healthcare Q3 2024'",
    "result": null
  }
}

// critic_result event
{
  "type": "critic_result",
  "timestamp": "2024-11-15T17:04:14Z",
  "data": {
    "task_id": 1,
    "passed": false,
    "reason": "Missing Q3 2024 specific revenue figures",
    "feedback_for_executor": "Search specifically for Q3 2024 funding amounts in USD",
    "loop_count": 1
  }
}

// HITL_READY event
{
  "type": "HITL_READY",
  "timestamp": "2024-11-15T17:04:55Z",
  "data": {
    "session_id": "a3f8b9c2-...",
    "draft_word_count": 1842,
    "source_count": 12,
    "total_cost_usd": 0.089
  }
}

// cost_update event
{
  "type": "cost_update",
  "timestamp": "2024-11-15T17:04:22Z",
  "data": {
    "total_cost_usd": 0.043,
    "tokens_input": 8420,
    "tokens_output": 1205
  }
}
```

---

## 7. Redis Key Conventions

All Redis keys must follow a structured naming convention to avoid collisions:

| Key Pattern | TTL | Purpose |
|---|---|---|
| `session:{session_id}:events` | 24h | Redis pub/sub channel for SSE events |
| `lock:session:{session_id}` | 30s | Distributed session lock (released on completion) |
| `checkpoint:{session_id}` | 24h | Serialized LangGraph checkpoint |
| `rate:user:{user_id}:sessions` | 1h | Session rate limit counter (INCR with TTL) |
| `cost:session:{session_id}` | 24h | Running cost accumulator for real-time updates |

---

## 8. Error Response Format

All API errors return a consistent JSON envelope:

```python
# app/schemas/common.py
from pydantic import BaseModel
from typing import Optional

class ErrorResponse(BaseModel):
    error: str           # Machine-readable error code (e.g., "SESSION_NOT_FOUND")
    message: str         # Human-readable message
    detail: Optional[dict] = None   # Additional context (e.g., validation errors)

# Examples:
# 404: {"error": "SESSION_NOT_FOUND", "message": "Session a3f8b9 does not exist or you don't have access."}
# 409: {"error": "INVALID_STATUS", "message": "Session must be in AWAITING_APPROVAL to approve. Current status: RUNNING"}
# 422: {"error": "VALIDATION_ERROR", "message": "Request body invalid.", "detail": {...pydantic errors...}}
# 429: {"error": "RATE_LIMIT_EXCEEDED", "message": "Maximum 5 sessions per hour. Retry after 23 minutes."}
```

```python
# app/main.py — Register global exception handlers
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": "VALIDATION_ERROR",
            "message": "Request body is invalid.",
            "detail": exc.errors()
        }
    )
```
