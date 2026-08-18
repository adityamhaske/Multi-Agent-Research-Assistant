"""
The migration CLI's refusals (M2E §"CLI", §"Production safety").

Every test here asserts that an ambiguous or under-specified invocation **writes nothing**.
The CLI's whole job is to make the target explicit, so the interesting cases are the ones
where it declines rather than the one where it runs.

The tests exercise argument handling and target resolution, which is where the safety lives:
`check_target` runs before a connection is opened, so a refusal cannot have touched a
database.
"""

from __future__ import annotations

import pytest

from migration.cli import Refused, check_target, database_name, describe, mask, parser
from migration.dryrun import parser as dryrun_parser

PROD = "postgresql+asyncpg://research_user:hunter2@localhost:5432/research_db"


def test_the_password_is_never_printed():
    printed = describe(PROD, apply=False)
    assert "hunter2" not in printed
    assert "***" in mask(PROD)
    assert "research_db" in printed


def test_the_target_is_named_before_anything_happens():
    printed = describe(PROD, apply=True)
    assert "research_db" in printed
    assert "COMMITTED" in printed
    assert "DRY RUN" in describe(PROD, apply=False)


def test_database_url_is_required_and_the_environment_is_not_read(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", PROD)
    with pytest.raises(SystemExit):  # argparse: required=True
        parser().parse_args([])
    # And the environment variable is not consulted anywhere in the module.
    with pytest.raises(Refused):
        check_target("", apply=False, confirm=None)


def test_apply_without_a_confirmation_is_refused():
    with pytest.raises(Refused, match="--confirm-database"):
        check_target(PROD, apply=True, confirm=None)


def test_a_confirmation_that_does_not_match_is_refused():
    with pytest.raises(Refused, match="does not match"):
        check_target(PROD, apply=True, confirm="research_test_db")


def test_a_matching_confirmation_is_accepted():
    check_target(PROD, apply=True, confirm="research_db")  # no exception


def test_a_dry_run_needs_no_confirmation_because_it_writes_nothing():
    check_target(PROD, apply=False, confirm=None)


def test_apply_and_dry_run_together_are_refused():
    from migration.cli import main

    assert main(["--database-url", PROD, "--apply", "--dry-run"]) == 2


def test_the_default_with_no_flags_is_a_dry_run():
    args = parser().parse_args(["--database-url", PROD])
    assert args.apply is False
    assert args.limit is None
    assert args.retry_failed is False


def test_a_dsn_naming_no_database_is_refused():
    with pytest.raises(Refused, match="names no database"):
        database_name("postgresql+asyncpg://user:pw@localhost:5432")


@pytest.mark.parametrize(
    ("dsn", "expected"),
    [
        # SQLAlchemy's own rule: three slashes is a relative path, four is absolute. The
        # printed target must be the file the engine will actually open.
        ("sqlite+aiosqlite:///data/v2.sqlite", "data/v2.sqlite"),
        ("sqlite+aiosqlite:////var/lib/v2.sqlite", "/var/lib/v2.sqlite"),
        ("postgresql+asyncpg://u:p@h:5432/research_db", "research_db"),
    ],
)
def test_the_named_database_is_the_one_that_will_be_opened(dsn, expected):
    assert database_name(dsn) == expected


def test_the_dry_run_tool_always_demands_a_confirmed_target():
    """`migration.dryrun` seeds data, so it has no read-only mode to fall back on."""
    with pytest.raises(SystemExit):
        dryrun_parser().parse_args(["--database-url", PROD])  # no --confirm-database
    args = dryrun_parser().parse_args(["--database-url", PROD, "--confirm-database", "research_db"])
    assert args.confirm_database == "research_db"
