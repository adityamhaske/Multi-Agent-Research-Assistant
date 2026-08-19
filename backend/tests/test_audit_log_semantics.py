"""
What an `audit_log` row means, pinned (issue #53).

These rows are the record of every human decision in the product, and the bundle's
`approval_chain` is derived from them — so `verify_bundle._check_approval_chain`, the check
that decides whether an artifact is trustworthy, is ultimately ruling on this table. A
reader verifying a bundle is trusting these semantics, which makes "documented nowhere" a
different kind of gap from ordinary doc debt.

The prose lives in `docs/architecture/05-data-model.md`. This file is the half that fails
when the prose stops being true. Nothing here changes behaviour; it records it.

Several of these read the source rather than exercising a route. That is deliberate for
claims of the form "nothing anywhere does X" — no fixture can demonstrate the absence of a
writer, and a behavioural test would pass simply by not calling the code that breaks it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent

#: The complete set of writers, by file and enclosing function. Server and desktop hosts
#: write the same two decisions each: one at the design gate, one at the report gate.
EXPECTED_WRITERS = {
    ("app/api/v1/research.py", "submit_plan"),
    ("app/api/v1/research.py", "approve_or_rework"),
    ("desktop/sidecar.py", "submit_plan"),
    ("desktop/sidecar.py", "approve_or_rework"),
}

#: Every module that could plausibly write one. Scanned in full, so a new writer added
#: anywhere in them is caught rather than assumed absent.
SCANNED = ["app", "desktop", "research_engine"]


def _audit_writers() -> set[tuple[str, str]]:
    """Every `AuditLog(...)` construction, as (relative path, *innermost* function).

    Innermost matters: the sidecar declares its routes inside `create_sidecar_app`, so
    attributing a call to the outermost enclosing function would name the factory for
    every route it contains and lose which gate actually writes.
    """
    found: set[tuple[str, str]] = set()
    for root in SCANNED:
        for path in (BACKEND / root).rglob("*.py"):
            if "models" in path.parts:
                continue  # the declaration itself, not a write
            tree = ast.parse(path.read_text(encoding="utf-8"))
            enclosing: dict[ast.AST, str] = {}

            def descend(node: ast.AST, current: str | None, table=enclosing) -> None:
                for child in ast.iter_child_nodes(node):
                    name = (
                        child.name
                        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
                        else current
                    )
                    if name is not None:
                        table[child] = name
                    descend(child, name)

            descend(tree, None)
            for node, func_name in enclosing.items():
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "AuditLog"
                ):
                    found.add((str(path.relative_to(BACKEND)), func_name))
    return found


def test_only_the_four_gate_routes_write_an_audit_row():
    """A decision is recorded where a human makes one, and nowhere else.

    In particular the graph never writes one. A pipeline state change is not a decision,
    and a chain containing entries no human authored would make `approval_chain` describe
    something other than what it claims to describe.
    """
    assert _audit_writers() == EXPECTED_WRITERS


def test_nothing_updates_or_deletes_an_audit_row():
    """Append-only in practice — there is no database constraint enforcing it.

    Rows do cascade-delete with their session, which is the one legitimate removal: the
    decision is about that session and does not outlive it. What must not appear is a
    targeted update or delete, because a mutable chain is not evidence.
    """
    offenders = []
    for root in SCANNED:
        for path in (BACKEND / root).rglob("*.py"):
            if "models" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            for pattern in (r"update\(AuditLog", r"delete\(AuditLog", r"AuditLog\)\.delete"):
                if re.search(pattern, text):
                    offenders.append(f"{path.relative_to(BACKEND)}: {pattern}")
    assert not offenders, f"audit_log is append-only; found mutation: {offenders}"


def test_both_hosts_read_the_chain_in_insertion_order():
    """`id` ascending, on both hosts.

    The chain is a sequence of decisions and its order is its meaning: a rework followed
    by an approval is a different history from an approval followed by a rework. Ordering
    by `created_at` would be subtly wrong — two decisions inside one second would be free
    to swap.
    """
    for rel in ("app/api/v1/research.py", "desktop/sidecar.py"):
        text = (BACKEND / rel).read_text(encoding="utf-8")
        assert "AuditLog.id.asc()" in text, f"{rel} does not order the chain by id ascending"
        assert "AuditLog.created_at" not in text, (
            f"{rel} orders or filters the chain by timestamp; two decisions in the same "
            "second could then be reported in the wrong order"
        )


def test_the_draft_hash_column_carries_two_different_hashed_objects():
    """The overload, pinned rather than tidied away.

    At the report gate `draft_hash` is `sha256(draft_report)` — the link the verifier
    checks, tying an approval to the exact text approved. At the design gate the same
    column holds `sha256(json.dumps({"tasks","outline"}, sort_keys=True))`, hashing a
    *plan*, and no shipped tool verifies it.

    Documented as intentional (docs/05) rather than split, because splitting the column is
    a schema change and this issue is explicitly not that. The test exists so the second
    meaning cannot be forgotten by someone reading only the verifier.
    """
    text = (BACKEND / "app/api/v1/research.py").read_text(encoding="utf-8")

    plan_at = text.index('action="plan_approved"')
    plan_window = text[plan_at : plan_at + 600]
    assert "json.dumps" in plan_window and "sort_keys=True" in plan_window, (
        "the design gate no longer hashes a canonicalised plan; if the hashed object "
        "changed, docs/05 and the V2 Review mapping both need updating"
    )

    approved_at = text.index('action="approved"')
    approved_window = text[max(0, approved_at - 1500) : approved_at + 600]
    assert "draft_hash" in approved_window, "the report gate no longer records a draft hash"
