"""
A column added to the ORM reaches an app somebody already installed.

The desktop builds its schema with `create_all`, which creates *missing tables* and never
alters an existing one — so every column added after a user's first launch was invisible to
them until `_add_missing_columns` was written. Its own docstring says why that mattered:
"the first release that adds a column would otherwise break every install." It has never had
a test. A7 added `revisions.report_document` and 0024 added two columns to `research_runs`;
nobody had checked that either reaches an installed database.

**Built from a real file, not from trimmed metadata.** Each test creates the current schema,
then `ALTER TABLE … DROP COLUMN`s its way back to an older one. The result is a database that
genuinely lacks the column, rather than a description of a schema that may never have
shipped — the same reasoning as `test_corpus_versioning`'s `_make_pre_a4`.

**The limits are pinned, not assumed.** `_add_missing_columns` handles added columns and
nothing else: renames, drops, type changes and CHECK-constraint changes are out of reach
without a table rebuild, and SQLite will not express most of them. Those tests exist so the
boundary is a decision somebody can read, and so the day one is needed it fails loudly.

The one case that could brick an install is a NOT NULL column with no `server_default` added
to a table that already has rows: SQLite refuses it, and it used to surface as a raw driver
error at startup with no indication of which column. It is refused by name now.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.models import POSTGRES_ONLY_TABLES, Base
from desktop.sidecar import _add_missing_columns

#: The set the sidecar itself syncs — read the same way it reads it, so this cannot describe
#: a different schema from the one the app builds.
TABLES = [t for t in Base.metadata.sorted_tables if t.name not in POSTGRES_ONLY_TABLES]


@pytest.fixture()
def installed(tmp_path):
    """A database at the current schema, standing in for an app somebody already runs."""
    engine = create_engine(f"sqlite:///{tmp_path / 'desktop.sqlite'}")
    Base.metadata.create_all(engine, tables=TABLES)
    yield engine
    engine.dispose()


def _drop(engine, table: str, column: str) -> None:
    """Take one column back out, making the file genuinely older than the models."""
    with engine.begin() as conn:
        conn.exec_driver_sql(f'ALTER TABLE "{table}" DROP COLUMN "{column}"')


def _columns(engine, table: str) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns(table)}


def _sync(engine) -> None:
    """The sidecar hands `_add_missing_columns` a *sync* connection out of `run_sync`; this
    engine is already synchronous, so the connection goes straight in."""
    with engine.begin() as conn:
        _add_missing_columns(conn, TABLES)


def _insert(engine, table: str, **values) -> None:
    """Insert one row, filling in every NOT NULL column the caller did not name.

    Derived from the metadata rather than spelled out: most NOT NULL columns here default in
    Python, not in the database, so a hand-written INSERT has to name them all and grows a
    new omission every time a model gains a column — which is the drift this whole file is
    about."""
    columns = Base.metadata.tables[table].columns
    placeholder = {"INTEGER": 0, "BIGINT": 0, "BOOLEAN": 0, "NUMERIC": 0, "FLOAT": 0.0}
    row = dict(values)
    for column in columns:
        if column.name in row or column.nullable or column.server_default is not None:
            continue
        kind = column.type.compile(dialect=engine.dialect).split("(")[0].upper()
        row.setdefault(column.name, placeholder.get(kind, f"{table[:2]}-{column.name}"))
    names = ", ".join(f'"{k}"' for k in row)
    binds = ", ".join(f":{k}" for k in row)
    with engine.begin() as conn:
        conn.execute(text(f"INSERT INTO {table} ({names}) VALUES ({binds})"), row)  # noqa: S608


def _seed_user(engine) -> str:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, hashed_pw, is_active, monthly_token_limit) "
                "VALUES ('u1', 'sync@x.invalid', 'x', 1, 0)"
            )
        )
    return "u1"


# ── The thing it exists to do ────────────────────────────────────────────────────


def test_a_column_added_after_a_release_reaches_an_installed_database(installed):
    _seed_user(installed)
    _drop(installed, "users", "display_name")
    assert "display_name" not in _columns(installed, "users")

    _sync(installed)

    assert "display_name" in _columns(installed, "users")


def test_the_rows_that_were_already_there_survive_it(installed):
    """The half that matters to a user: their research is still in the file afterwards."""
    _seed_user(installed)
    _drop(installed, "users", "display_name")

    _sync(installed)

    with installed.begin() as conn:
        rows = conn.execute(text("SELECT id, email, hashed_pw FROM users")).fetchall()
    assert rows == [("u1", "sync@x.invalid", "x")]


@pytest.mark.parametrize(
    ("table", "column"),
    [
        # A7 — the typed view of a report revision.
        ("revisions", "report_document"),
        # 0024 — which corpus a run read, and what state it was in.
        ("research_runs", "corpus_id"),
        ("research_runs", "corpus_version"),
    ],
)
def test_the_most_recent_columns_reach_an_installed_database(installed, table, column):
    """Named individually rather than covered by the generic test above: these are the
    columns shipped since the sync was written, and nobody had checked them."""
    _drop(installed, table, column)

    _sync(installed)

    assert column in _columns(installed, table)


def test_running_it_twice_changes_nothing(installed):
    """A startup path runs on every launch, so it has to be a no-op once it is done."""
    _drop(installed, "users", "display_name")
    _sync(installed)
    first = {t.name: _columns(installed, t.name) for t in TABLES}

    _sync(installed)

    assert {t.name: _columns(installed, t.name) for t in TABLES} == first


def test_a_not_null_column_keeps_the_default_a_fresh_install_would_get(installed):
    """SQLite needs a value for the existing rows, and the right one is the column's own
    `server_default` — anything else would give an upgraded install a different starting
    state from a fresh one.

    `sessions.demo` rather than something on `users`: it is NOT NULL *with* a real
    `server_default`, which is the combination this branch is about. Most NOT NULL columns
    here default in Python instead, and those are the refusal case below."""
    _seed_user(installed)
    _insert(installed, "projects", id="p1", user_id="u1", name="P")
    _insert(installed, "sessions", id="s1", user_id="u1", project_id="p1", prompt="q")
    _drop(installed, "sessions", "demo")

    _sync(installed)

    with installed.begin() as conn:
        value = conn.execute(text("SELECT demo FROM sessions")).scalar()
    assert value in (0, False), f"the existing row did not get the column's own default: {value!r}"


# ── The case that could brick an install ─────────────────────────────────────────


def test_a_required_column_with_no_default_is_refused_by_name(installed):
    """A NOT NULL column with no `server_default`, added to a table that already has rows.

    SQLite cannot do it — there is no value to give the existing rows — and this used to
    reach a user as a raw driver error during startup, naming neither the table nor the
    column. It refuses with both now, so the fix is obvious to whoever added the column."""
    _seed_user(installed)
    _drop(installed, "users", "hashed_pw")  # NOT NULL, no server_default

    with pytest.raises(RuntimeError) as excinfo:
        _sync(installed)

    message = str(excinfo.value)
    assert "users" in message and "hashed_pw" in message
    assert "server_default" in message, "the message must say what would fix it"


def test_the_same_column_is_added_happily_when_the_table_is_empty(installed):
    """There are no rows to give a value to, so nothing is in the way. This is what keeps
    the refusal above narrow — it is about existing data, not about the column."""
    _drop(installed, "users", "hashed_pw")

    _sync(installed)

    assert "hashed_pw" in _columns(installed, "users")


# ── The limits, pinned so the boundary is a decision and not a surprise ──────────


def test_a_check_constraint_change_is_not_applied(installed):
    """Out of reach without a table rebuild, and stated in the sync's own docstring.

    Concretely already true of `ck_source_ret`: widening it reaches a fresh install's
    `create_all` and the server's Alembic run, but an existing file keeps the narrower
    constraint it was created with. Pinned rather than fixed — building constraint-migration
    machinery is not what A9 is for, and this is the assertion that will fail the day it
    becomes necessary."""
    with installed.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS narrow")
        conn.exec_driver_sql(
            "CREATE TABLE narrow (id TEXT PRIMARY KEY, state TEXT CHECK (state IN ('A')))"
        )

    _sync(installed)

    with installed.begin() as conn:
        sql = conn.execute(text("SELECT sql FROM sqlite_master WHERE name = 'narrow'")).scalar()
        assert "'A'" in sql and "'B'" not in sql, "the constraint was rewritten unexpectedly"
        with pytest.raises(IntegrityError):
            conn.exec_driver_sql("INSERT INTO narrow VALUES ('1', 'B')")


def test_a_dropped_model_column_is_left_alone(installed):
    """Additive only: a column the models no longer declare stays in the file. Removing it
    would be a table rebuild, and doing that automatically on somebody's data is a much
    larger decision than this function is entitled to make."""
    with installed.begin() as conn:
        conn.exec_driver_sql('ALTER TABLE "users" ADD COLUMN "left_over" TEXT')

    _sync(installed)

    assert "left_over" in _columns(installed, "users")
