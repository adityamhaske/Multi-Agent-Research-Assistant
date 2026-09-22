"""
Which surfaces apply prompt overrides, and which say so instead (PR-6, scope freeze §17).

Three surfaces, three different answers, and each is a deliberate decision:

- **Runs** apply them from a snapshot frozen at start — `test_prompt_override_snapshot.py`.
- **Chat** applies them live. There is no run to stay consistent with and no resume, so a
  turn answers under the preferences as they stand.
- **Sessions** do not apply them at all and are *recorded* as not having. The session
  pipeline predates the AgentSpec contract and is not gaining it — runs are the product, and
  AGENTS.md is explicit that the session path stays readable rather than deepened. The
  alternative to recording it is a report that quietly ignored a configuration its reader
  believes was in force, which is the class of unverifiable output this product refuses.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest

from app.models.session import Session as SessionRow
from app.services.run_config import (
    OVERRIDES_APPLIED,
    chat_prompt_context,
    snapshot_overrides,
)
from research_engine import prompts
from research_engine.prompt_composition import system_prompt
from tests.dataflow.test_corpus_egress import _SessionDb

BACKEND = Path(__file__).resolve().parents[2]

BODY = "Answer in one sentence."


class _User:
    """The structural type `run_config` takes, which is why it takes one — the rule is about
    the mapping, not about a table, and the desktop's user is not the server's row."""

    def __init__(self, preferences):
        self.preferences = preferences


# ── Chat: live, and through the one enforcement point ─────────────────────────────


def test_a_chat_turn_answers_under_the_users_current_override():
    with chat_prompt_context(_User({"prompt_overrides": {"chat": BODY}})):
        assert BODY in system_prompt("chat.general")


def test_a_chat_turn_with_no_override_is_byte_identical():
    with chat_prompt_context(_User({})):
        assert system_prompt("chat.general") is prompts.CHAT_PROMPT


def test_a_malformed_stored_override_leaves_the_chat_prompt_alone():
    with chat_prompt_context(_User({"prompt_overrides": {"chat": BODY, "nope": "x"}})):
        assert system_prompt("chat.general") is prompts.CHAT_PROMPT


def test_the_override_does_not_outlive_the_turn():
    """A chat route runs on the request's own task. A config left installed would answer
    whatever that event loop picked up next under someone else's instructions."""
    with chat_prompt_context(_User({"prompt_overrides": {"chat": BODY}})):
        pass
    assert system_prompt("chat.general") is prompts.CHAT_PROMPT


def test_the_project_chat_prompt_is_unreachable_even_from_chat_scope():
    """`chat` fans out to two purposes and only one is eligible. Project chat carries the
    memory-grounding contract, so a body stored against the same role must stop there."""
    with chat_prompt_context(_User({"prompt_overrides": {"chat": BODY}})):
        assert system_prompt("chat.project") is prompts.PROJECT_CHAT_PROMPT


@pytest.mark.parametrize("relpath", ["app/api/v1/chat.py", "desktop/sidecar.py"])
def test_both_hosts_compose_chat_through_the_shared_context(relpath):
    """One contract, two hosts. The server installed no per-request config at all before
    this and the desktop installed one carrying no preferences, so neither host applied an
    override — the same shape of two-host gap AGENTS.md catalogues."""
    src = (BACKEND / relpath).read_text(encoding="utf-8")
    called = {
        getattr(c.func, "attr", getattr(c.func, "id", ""))
        for c in ast.walk(ast.parse(src))
        if isinstance(c, ast.Call)
    }
    assert "chat_prompt_context" in called


# ── Sessions: not applied, and recorded as not applied ────────────────────────────


async def test_a_session_run_config_carries_no_prompt_overrides():
    """Driven through the server's own session builder, not a hand-built config."""
    import app.workers.pipeline_runner as runner_mod

    row = SessionRow(prompt="q", research_depth="fast")
    row.corpus_mode = False
    row.demo = False

    cfg = await runner_mod._run_config_for(_SessionDb(), row, str(uuid.uuid4()))

    assert cfg.prompt_overrides == {}


@pytest.mark.parametrize(
    ("preferences", "expected"),
    [
        ({"prompt_overrides": {"planner": BODY}}, True),
        ({}, False),
        ({"prompt_overrides": {"planner": BODY, "nope": "x"}}, False),
    ],
)
def test_the_disclosure_rule_fires_only_on_an_override_that_would_have_applied(
    preferences, expected
):
    """The flag answers "did this path ignore something that would otherwise have taken
    effect". A malformed set would not have applied on a run either, so claiming the session
    ignored it would overstate — the flag has to be as honest as the thing it discloses."""
    _, status = snapshot_overrides(_User(preferences))
    assert (status == OVERRIDES_APPLIED) is expected


@pytest.mark.parametrize(
    ("relpath", "guard"),
    [
        ("app/workers/pipeline_runner.py", ("resume", "plan")),
        ("desktop/sidecar.py", ("approved", "plan")),
    ],
)
def test_both_session_drivers_record_the_disclosure_at_start(relpath, guard):
    """Structural: `_execute` needs a broker and `_drive_session` a packaged host, so the
    write itself is not reachable from here. The claim pinned is the narrow one that would
    actually rot — that both hosts write the flag, and write it on a start rather than
    re-deciding it on every resume.
    """
    tree = ast.parse((BACKEND / relpath).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        body = ast.unparse(node)
        if "prompt_overrides_not_applied" not in body:
            continue
        assert {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)} == set(guard)
        return
    raise AssertionError(f"{relpath} never records prompt_overrides_not_applied")


def test_the_flag_is_visible_to_a_reader_of_the_report():
    """A disclosure nothing serves is not a disclosure. `SessionDetail` is what the report
    view reads, so the field has to be declared there — Pydantic silently drops anything
    that is not, which is exactly how `model_routing` went missing from this same class."""
    from app.schemas.research import SessionDetail

    assert "prompt_overrides_not_applied" in SessionDetail.model_fields
