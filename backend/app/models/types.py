"""
Dialect-adaptive column types (docs/12 M9, docs/13 §7).

The server runs Postgres; the desktop sidecar runs SQLite. The ORM models are shared
between the two hosts — one schema, one set of migrations for Postgres, `create_all`
for the desktop — so column types must render correctly on both dialects.

`with_variant` keeps the Postgres behavior exactly as it was (JSONB, native UUID) and
only changes what SQLite sees (TEXT-backed JSON, CHAR(32) UUID). Nothing on the server
path changes; this is what lets the sidecar reuse `app.models` instead of forking them.

`memory_chunks.embedding` stays pgvector-only: that table is excluded from the desktop
`create_all` until M10 ships local embeddings (docs/12 M10).
"""

from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Uuid
from sqlalchemy.dialects import sqlite
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

# Shared instances are safe: TypeEngine objects are immutable after construction and
# SQLAlchemy copies them per-column as needed.
JsonType = JSON().with_variant(JSONB(), "postgresql")
UuidType = Uuid(as_uuid=True).with_variant(PG_UUID(as_uuid=True), "postgresql")

# Autoincrement big-int PKs. On Postgres this is plain BIGINT + SERIAL, exactly as
# before. On SQLite, BIGINT is *not* a rowid alias, so an insert without an explicit
# id fails `NOT NULL` — only `INTEGER PRIMARY KEY` auto-populates. This variant is
# what makes agent_logs/audit_log inserts work on the desktop.
BigIntAutoType = BigInteger().with_variant(sqlite.INTEGER(), "sqlite")
