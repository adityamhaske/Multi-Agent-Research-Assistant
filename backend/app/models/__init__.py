"""ORM model registry.

Importing a model here is what registers it on `Base.metadata`, which is what both
`alembic --autogenerate` (server) and `create_all` (desktop) walk.

The V2 research tables (M2D) are **created and unused** — the database contract exists
before anything writes to it, so the migration plan's later phases have something to write
*into* (`internal/V2_Migration_Plan_M2C.md`).
"""

from app.models.agent_log import AgentLog
from app.models.audit_log import AuditLog
from app.models.base import Base
from app.models.chat_message import ChatMessage
from app.models.chat_thread import ChatThread
from app.models.memory_chunk import MemoryChunk
from app.models.project import Project
from app.models.project_memory import ProjectMemoryItem, ProjectMemoryProvenance
from app.models.refresh_token import RefreshToken
from app.models.research import (
    Contradiction,
    Evidence,
    ResearchPlan,
    ResearchRun,
    Source,
)
from app.models.review import AuditEvent, ClaimAnnotation, ResearchArtifact, Review
from app.models.revision import Claim, ClaimEvidenceLink, Revision
from app.models.session import Session, SessionStatus
from app.models.user import User

#: Tables that cannot exist on SQLite, and the single source of truth for that fact.
#:
#: Each carries a pgvector column, or references a table that does. The desktop host builds
#: its schema with `create_all` and must skip exactly these — previously it filtered one
#: table name inline in `sidecar.py`, which is the "two homes, one contract" shape this
#: repository keeps rediscovering. The sidecar now imports this set instead.
#:
#: Project memory is the one feature absent on desktop by design (docs/12 M10): the
#: airgapped corpus has its own SQLite store and local embeddings.
POSTGRES_ONLY_TABLES = frozenset(
    {
        MemoryChunk.__tablename__,
        ProjectMemoryItem.__tablename__,
        # Provenance to a table that does not exist is meaningless, so it goes with it.
        ProjectMemoryProvenance.__tablename__,
    }
)

__all__ = [
    "Base",
    "POSTGRES_ONLY_TABLES",
    "User",
    "Project",
    "Session",
    "SessionStatus",
    "AgentLog",
    "ChatMessage",
    "ChatThread",
    "MemoryChunk",
    "AuditLog",
    "RefreshToken",
    # V2 (M2D) — created, not yet written to.
    "ResearchRun",
    "ResearchPlan",
    "Source",
    "Evidence",
    "Contradiction",
    "Revision",
    "Claim",
    "ClaimEvidenceLink",
    "Review",
    "ClaimAnnotation",
    "ResearchArtifact",
    "AuditEvent",
    "ProjectMemoryItem",
    "ProjectMemoryProvenance",
]
