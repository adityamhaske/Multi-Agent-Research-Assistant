"""
Alembic environment configuration for async SQLAlchemy.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

# Import every model module explicitly so Alembic sees the full metadata
# (docs/05 §2 — no hidden transitive imports).
from app.config import settings
from app.models import (  # noqa: F401
    agent_log,
    audit_log,
    chat_message,
    project,
    refresh_token,
    session,
    user,
)
from app.models.base import Base

# The migration ledger lives outside `app.models` (it belongs to the V1 → V2 migration
# tool, not to the product), so importing `app.models` does not register it. Without this
# line `--autogenerate` would see the table as unknown and propose dropping it.
from migration import ledger  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = settings.database_url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(settings.database_url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
