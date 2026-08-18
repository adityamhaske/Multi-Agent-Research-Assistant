"""
The V1 → V2 migration command line (M2E §"CLI").

**The target is never inferred.** `--database-url` is required and `DATABASE_URL` is never
read — not as a default, not as a fallback. A tool that defaults to the operator's
environment is one keystroke away from migrating production because a shell happened to be
sourced, and the one absolute rule of M2E-2 is that production stays untouched.

Everything about this module is fail-closed:

* no `--database-url` → refuse
* writing requires `--apply` **and** `--confirm-database NAME` matching the database the
  DSN actually names; a typo in either produces a refusal rather than a write
* the default with no flags is a dry run: the whole migration executes and every
  transaction is rolled back
* the resolved target — driver, host, port, database, and whether it will commit — is
  printed before the first statement, with the password masked

`--resume` exists because operators expect it; it is a no-op flag that documents the
default. The migration always resumes, because a session carrying a terminal ledger row is
skipped (`runner.migrate_all`). `--retry-failed` is the opt-in that additionally re-attempts
the one retryable terminal state.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
from dataclasses import asdict
from urllib.parse import urlparse, urlunparse

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from migration.ledger import MigrationLedger
from migration.runner import MigrationReport, migrate_all


class Refused(Exception):
    """An invocation that will not be guessed at. Exits 2, writes nothing."""


# ── Target resolution ─────────────────────────────────────────────────────────────


def mask(dsn: str) -> str:
    """The DSN with the password replaced. Safe to print, and printed every time."""
    parsed = urlparse(dsn)
    if parsed.password is None:
        return dsn
    user = parsed.username or ""
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"{user}:***@{host}{port}" if user else f"***@{host}{port}"
    return urlunparse(parsed._replace(netloc=netloc))


def database_name(dsn: str) -> str:
    """The database this DSN names — a file path for SQLite, a db name for Postgres.

    Exactly **one** leading slash is stripped for SQLite, because that is SQLAlchemy's own
    rule: `sqlite:///a.db` opens the relative path `a.db`, `sqlite:////a.db` opens `/a.db`.
    Stripping all of them would print (and confirm against) a relative path while the
    engine opened an absolute one — a target description that disagrees with the target.
    """
    parsed = urlparse(dsn)
    raw = parsed.path or ""
    path = raw[1:] if parsed.scheme.startswith("sqlite") else raw.lstrip("/")
    if not path:
        raise Refused(f"the DSN names no database: {mask(dsn)}")
    return path


def describe(dsn: str, *, apply: bool) -> str:
    parsed = urlparse(dsn)
    where = parsed.hostname or "(local file)"
    port = f":{parsed.port}" if parsed.port else ""
    mode = (
        "APPLY — changes will be COMMITTED"
        if apply
        else "DRY RUN — every transaction is rolled back"
    )
    return (
        "V1 → V2 migration target\n"
        f"  dsn       : {mask(dsn)}\n"
        f"  driver    : {parsed.scheme}\n"
        f"  host      : {where}{port}\n"
        f"  database  : {database_name(dsn)}\n"
        f"  mode      : {mode}\n"
    )


def check_target(dsn: str, *, apply: bool, confirm: str | None) -> None:
    """Refuse anything ambiguous. Called before a connection is opened, not after."""
    if not dsn:
        raise Refused("--database-url is required; DATABASE_URL is deliberately not read")
    name = database_name(dsn)
    if not apply:
        return
    if not confirm:
        raise Refused(
            "--apply requires --confirm-database NAME, and NAME must match the database "
            f"the DSN names ({name})"
        )
    if confirm != name:
        raise Refused(f"--confirm-database {confirm!r} does not match the DSN's database {name!r}")


# ── Checkpoint saver ──────────────────────────────────────────────────────────────


@contextlib.asynccontextmanager
async def open_saver(url: str):
    """Open the LangGraph checkpointer the evidence is read from.

    There is no "skip checkpoints" mode. Running without a saver would classify every run
    as `CHECKPOINT_MISSING`, which is a false measurement — the exact failure this
    repository treats as P0 — rather than a convenience.
    """
    if url.startswith(("sqlite:", "sqlite+aiosqlite:", "file:")) or url.endswith(".sqlite"):
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        path = url.split("///")[-1] if "///" in url else url
        async with AsyncSqliteSaver.from_conn_string(path) as saver:
            yield saver
        return

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    # LangGraph's Postgres saver speaks psycopg, not asyncpg (mirrors
    # `app/services/checkpoints.py::_dsn`).
    async with AsyncPostgresSaver.from_conn_string(
        url.replace("postgresql+asyncpg://", "postgresql://")
    ) as saver:
        yield saver


# ── Run ───────────────────────────────────────────────────────────────────────────


async def execute(args: argparse.Namespace) -> tuple[int, MigrationReport | None]:
    """Resolve the target, refuse anything ambiguous, then migrate. Returns (exit code, report)."""
    try:
        check_target(args.database_url, apply=args.apply, confirm=args.confirm_database)
    except Refused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2, None

    print(describe(args.database_url, apply=args.apply), file=sys.stderr)

    engine = create_async_engine(args.database_url)
    try:
        async with engine.connect() as conn:
            # Ask the server which database it actually opened, rather than trusting the
            # string we were handed: a service file, a proxy or a connection pooler can
            # point somewhere else entirely.
            if conn.dialect.name == "postgresql":
                actual = (await conn.execute(text("SELECT current_database()"))).scalar_one()
                print(f"  connected : {actual}\n", file=sys.stderr)
                if args.apply and actual != args.confirm_database:
                    print(
                        f"refused: the server reports database {actual!r}, not the confirmed "
                        f"{args.confirm_database!r}",
                        file=sys.stderr,
                    )
                    return 2, None
            tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))

        missing = {"research_runs", "evidence", MigrationLedger.__tablename__} - tables
        if missing:
            print(
                f"refused: target is missing {sorted(missing)} — run `alembic upgrade head`",
                file=sys.stderr,
            )
            return 2, None

        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with open_saver(args.checkpoint_url or args.database_url) as saver, maker() as db:
            report = await migrate_all(
                db,
                saver,
                limit=args.limit,
                retry_failed=args.retry_failed,
                dry_run=not args.apply,
            )
    finally:
        await engine.dispose()

    # A FAILED run is retryable, not fatal — but it must not exit 0, or a scheduler will
    # record the migration as clean while runs are still unmigrated.
    return (1 if report.by_status.get("FAILED") else 0), report


async def _main(args: argparse.Namespace) -> int:
    code, report = await execute(args)
    if report is None:
        return code

    payload = asdict(report)
    payload["durations_ms"] = f"{len(report.durations_ms)} samples"  # a summary, not a dump
    print(json.dumps(payload, indent=2, sort_keys=True))
    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(asdict(report), fh, indent=2, sort_keys=True)
    return code


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m migration.cli",
        description="Migrate V1 sessions into the V2 domain tables. Dry run unless --apply.",
    )
    p.add_argument(
        "--database-url",
        required=True,
        help="SQLAlchemy async DSN of the target. REQUIRED — DATABASE_URL is never read.",
    )
    p.add_argument(
        "--checkpoint-url",
        default=None,
        help="LangGraph checkpointer DSN. Defaults to --database-url.",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="Commit. Without this the migration runs and rolls back (the default).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicit form of the default. Cannot be combined with --apply.",
    )
    p.add_argument(
        "--confirm-database",
        default=None,
        help="The database name --apply is allowed to write to. Must match the DSN.",
    )
    p.add_argument("--limit", type=int, default=None, help="Process at most N sessions.")
    p.add_argument(
        "--resume",
        action="store_true",
        help="Documents the default: terminal sessions are always skipped.",
    )
    p.add_argument(
        "--retry-failed",
        action="store_true",
        help="Also re-attempt sessions in the FAILED state (the one retryable outcome).",
    )
    p.add_argument("--report", default=None, help="Write the full JSON report to this path.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.apply and args.dry_run:
        print("refused: --apply and --dry-run are contradictory", file=sys.stderr)
        return 2
    return asyncio.run(_main(args))


if __name__ == "__main__":  # pragma: no cover — exercised through main()
    raise SystemExit(main())
