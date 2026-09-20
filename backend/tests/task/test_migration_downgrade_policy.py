"""
Every migration is reversible, or says in writing why it is not.

`docs/architecture/05-data-model.md` promised "every migration has a real `downgrade()`"
while two of them were `pass`. That was not a lie about those two — their reasons are sound
and written down — it was a policy stated as absolute when it has exceptions. A policy with
undeclared exceptions is one nobody can rely on, so the exceptions live here, each with the
reason, and everything outside them is held to the rule.

**Two exception classes, and conflating them would hide the difference that matters.**

`IRREVERSIBLE_BY_DESIGN` — the downgrade does nothing, on any database, ever. Reversing
would either destroy something or be impossible, so it declines. Two entries, both with the
reason in the migration itself.

`DATA_DEPENDENT_DOWNGRADE` — the downgrade is real and works, *unless* the database holds
rows the older schema cannot express. Both entries are the same shape: a migration that made
a foreign key polymorphic, whose downgrade reinstates it. A row naming the other pipeline
cannot satisfy the reinstated key, and refusing is correct — the alternative is a foreign key
that lies about what the column holds. **These are not broken and must not be "fixed"**;
`tests/workflow/test_migration_round_trip.py` characterises both directions of each.

Neither registry excuses `0008_chat_threads`, which was genuinely broken: it dropped a
constraint name the metadata convention had already expanded, so no database ever held it and
every downgrade past that revision died. That was fixed. It is the only production migration
A9 changed, and the distinction between "declines by design" and "was wrong" is the whole
reason these registries name their members rather than counting them.

No database is needed here: this reads the migration sources and the revision graph.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
VERSIONS = BACKEND / "alembic" / "versions"

#: A downgrade that is a no-op on every database, with the reason it declines. Both reasons
#: are quoted from the migrations themselves — if one ever grows a body, the anti-stale test
#: below fails rather than letting a stale entry sit here forever.
IRREVERSIBLE_BY_DESIGN: dict[str, str] = {
    "0006_pgvector": (
        "dropping the `vector` extension would take every vector column with it; the memory "
        "tables are removed by their own migration and leaving the extension installed is "
        "harmless"
    ),
    "0013_awaiting_plan_status": (
        "PostgreSQL cannot drop an enum value. Rebuilding the type fails the "
        "`status::text::session_status` cast on any session parked at the plan gate, and "
        "rewriting those rows first would discard a paused session to make a schema "
        "operation succeed"
    ),
}

#: A downgrade that works, and correctly refuses a database holding rows the older schema
#: cannot express. Both are the polymorphic-foreign-key pair `AGENTS.md` names: a column that
#: may hold a `sessions.id` or a `research_runs.id`, whose downgrade reinstates a foreign key
#: to `sessions` alone.
DATA_DEPENDENT_DOWNGRADE: dict[str, str] = {
    "0018_agent_logs_polymorphic": (
        "reinstates `fk_agent_logs_session_id_sessions`. A trace row belonging to a run "
        "names `research_runs`, so it cannot satisfy that key — refusing is correct, and "
        "the alternative is a foreign key that lies about what the column holds"
    ),
    "0022_memory_chunks_polymorphic": (
        "reinstates `fk_memory_chunks_source_session_id_sessions`. Project memory indexed "
        "from a run names `research_runs`, and the migration says so itself: 'Reinstating "
        "the FK fails if any run from the current pipeline has been indexed, which is "
        "correct'"
    ),
}

#: The one migration A9 repaired, named so that it can never be quietly reclassified as an
#: exception. Its downgrade dropped a constraint whose name the naming convention had already
#: rendered, producing `ck_chat_messages_ck_chat_messages_one_parent` — a name no database has
#: ever held. Characterised by `test_0008_downgrades_the_constraint_it_actually_created`.
REPAIRED_DEFECT = "0008_chat_threads"


def _migrations() -> dict[str, Path]:
    """`revision id -> source path`, read from the files rather than a hand-written list."""
    found: dict[str, Path] = {}
    for path in sorted(VERSIONS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.Assign | ast.AnnAssign):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            if "revision" in names and isinstance(node.value, ast.Constant):
                found[node.value.value] = path
    return found


def _downgrade_operations(path: Path) -> list[str]:
    """The `op.*` calls one migration's `downgrade()` makes.

    Counting operations rather than statements: a body holding only a docstring, a comment
    and `pass` is not a downgrade however many lines it occupies, and that is exactly the
    shape both `IRREVERSIBLE_BY_DESIGN` entries take.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fn = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "downgrade"),
        None,
    )
    if fn is None:
        return []
    return [
        ast.unparse(node.func)
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and ast.unparse(node.func).startswith("op.")
    ]


ALL_MIGRATIONS = _migrations()
EXEMPT = set(IRREVERSIBLE_BY_DESIGN) | set(DATA_DEPENDENT_DOWNGRADE)


# ── The rule ──────────────────────────────────────────────────────────────────────


def test_the_migrations_were_actually_found():
    """A registry test that read nothing would pass every assertion below."""
    assert len(ALL_MIGRATIONS) >= 27, f"only parsed {len(ALL_MIGRATIONS)} migrations"
    assert REPAIRED_DEFECT in ALL_MIGRATIONS


@pytest.mark.parametrize("revision", sorted(set(ALL_MIGRATIONS) - set(IRREVERSIBLE_BY_DESIGN)))
def test_every_migration_outside_the_registry_has_a_real_downgrade(revision):
    """The policy `docs/05` states, enforced instead of asserted.

    `DATA_DEPENDENT_DOWNGRADE` members are held to this too: theirs are real downgrades that
    decline particular *data*, not empty ones."""
    operations = _downgrade_operations(ALL_MIGRATIONS[revision])
    assert operations, (
        f"{revision} has no downgrade operations. If it genuinely cannot be reversed on any "
        "database, add it to IRREVERSIBLE_BY_DESIGN with the reason; if it refuses only "
        "certain data, it belongs in DATA_DEPENDENT_DOWNGRADE and still needs a real body."
    )


# ── The registries describe reality ──────────────────────────────────────────────


@pytest.mark.parametrize("registry", [IRREVERSIBLE_BY_DESIGN, DATA_DEPENDENT_DOWNGRADE])
def test_every_registry_entry_names_a_migration_that_exists(registry):
    unknown = set(registry) - set(ALL_MIGRATIONS)
    assert not unknown, f"registry names revisions that do not exist: {sorted(unknown)}"


@pytest.mark.parametrize("registry", [IRREVERSIBLE_BY_DESIGN, DATA_DEPENDENT_DOWNGRADE])
def test_every_registry_entry_states_a_reason(registry):
    """An entry without a reason becomes permanent by default — the same contract
    `test_layer_boundaries.KNOWN_EXCEPTIONS` and the parity tables carry."""
    thin = {rev: reason for rev, reason in registry.items() if len(reason.strip()) < 40}
    assert not thin, f"these entries do not explain themselves: {sorted(thin)}"


def test_irreversible_entries_are_still_irreversible():
    """The anti-stale direction. An entry whose migration has grown a real downgrade is an
    exception nobody will notice has stopped being one."""
    with_bodies = {
        rev: _downgrade_operations(ALL_MIGRATIONS[rev])
        for rev in IRREVERSIBLE_BY_DESIGN
        if _downgrade_operations(ALL_MIGRATIONS[rev])
    }
    assert not with_bodies, (
        f"these now have real downgrades — remove them from IRREVERSIBLE_BY_DESIGN: "
        f"{sorted(with_bodies)}"
    )


def test_data_dependent_entries_have_real_downgrades():
    """The other anti-stale direction, and the distinction the two registries exist to keep.

    A member of `DATA_DEPENDENT_DOWNGRADE` that had become a no-op would belong in the other
    registry; one that stopped reinstating a foreign key would belong in neither."""
    for revision in DATA_DEPENDENT_DOWNGRADE:
        operations = _downgrade_operations(ALL_MIGRATIONS[revision])
        assert operations, f"{revision} has no downgrade body — it is not data-dependent"
        assert "op.create_foreign_key" in operations, (
            f"{revision} no longer reinstates a foreign key, which is the whole reason its "
            "downgrade depends on the data. Re-classify it rather than leaving it here."
        )


def test_the_registries_do_not_overlap():
    """ "Declines always" and "declines on some data" are different claims about the same
    migration and it cannot make both."""
    both = set(IRREVERSIBLE_BY_DESIGN) & set(DATA_DEPENDENT_DOWNGRADE)
    assert not both, f"claimed by both registries: {sorted(both)}"


def test_the_repaired_defect_is_not_an_exception():
    """`0008` was broken, not exempt. Reclassifying a defect as a declared limitation is how
    a bug becomes a feature nobody fixes."""
    assert REPAIRED_DEFECT not in EXEMPT
    operations = _downgrade_operations(ALL_MIGRATIONS[REPAIRED_DEFECT])
    assert "op.drop_constraint" in operations
    source = ALL_MIGRATIONS[REPAIRED_DEFECT].read_text(encoding="utf-8")
    downgrade = source.split("def downgrade", 1)[1]
    assert '"ck_chat_messages_one_parent"' not in downgrade, (
        "the rendered constraint name is back in the downgrade; the naming convention will "
        "expand it a second time and no database will hold the result"
    )


# ── The graph itself ─────────────────────────────────────────────────────────────


def test_the_revision_graph_is_one_linear_chain():
    """One base, one head, no branch and no merge.

    V3 runs two parallel tracks writing migrations, which is precisely how a second head
    appears — and a suspected second head costs real time to disprove even when it is
    imaginary. Read from Alembic's own parser, not from a regex over the files."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    revisions = list(script.walk_revisions())

    assert len(script.get_heads()) == 1, f"expected one head, found {script.get_heads()}"
    assert len(script.get_bases()) == 1, f"expected one base, found {script.get_bases()}"
    branches = [r.revision for r in revisions if len(r.nextrev) > 1]
    assert not branches, f"the chain branches at {branches}"
    merges = [
        r.revision for r in revisions if r.down_revision and not isinstance(r.down_revision, str)
    ]
    assert not merges, f"the chain merges at {merges}"
    assert len(revisions) == len(ALL_MIGRATIONS)
