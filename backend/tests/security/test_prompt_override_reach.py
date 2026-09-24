"""
What a user's prompt override can reach, pinned structurally (AgentSpec RFC §18.3, AC-19).

`docs/architecture/06-security.md` §6 states that a replacement prompt changes what the model
is told and nothing else: it cannot turn off a URL guard, widen corpus egress, raise a
budget, or change whether a run is recorded as a demo. RFC §18.3 requires that claim to be
asserted by test rather than assumed, and it rests on three structural facts:

1. **One reader.** `RunConfig.prompt_overrides` is read in exactly one place,
   `prompt_composition.system_prompt`. Its *writers* are pinned by
   `test_prompt_override_preferences::test_only_the_snapshot_path_dials_a_stored_override`;
   this pins the readers, which is the half that decides what an override can influence.
2. **One destination.** In the graph, what `system_prompt` returns becomes the content of a
   system message and nothing else — not a branch condition, not a tool argument.
3. **Not a preference.** The fields that decide those controls cannot be set through the one
   surface a user edits.

**What this does not claim.** A model following a user's prompt still chooses what to search
and which pages to read — that is the feature. The guards those requests pass through are
code, and the point is that no prompt text reaches the decision whether they run.
"""

from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path

from app.schemas.auth import UserPreferences
from app.services.run_config import PREFERENCE_FIELDS
from research_engine.runconfig import RunConfig

BACKEND = Path(__file__).resolve().parents[2]

#: Everything that executes against a real `RunConfig`. `evals` is included because the
#: custom-spec eval installs an override around the production graph.
RUNTIME_PACKAGES = ("app", "research_engine", "desktop", "evals")

#: `RunConfig` fields that decide a control rather than an instruction: whether custom model
#: endpoints are SSRF-checked, whether retrieval may leave the corpus, whether the run is
#: scripted and recorded as a demo, and the four budget limits.
CONTROL_PLANE_FIELDS = (
    "enforce_ssrf_guards",
    "corpus_mode",
    "demo",
    "llm_mode",
    "max_critic_loops",
    "max_cost_per_session_usd",
    "max_wallclock_seconds",
    "max_input_tokens",
)


def _runtime_trees():
    for package in RUNTIME_PACKAGES:
        for path in sorted((BACKEND / package).rglob("*.py")):
            yield path.relative_to(BACKEND).as_posix(), ast.parse(path.read_text("utf-8"))


class _OverrideReads(ast.NodeVisitor):
    """Every read of an attribute named `prompt_overrides`, with its enclosing function.

    Two spellings count: `x.prompt_overrides` in load context, and
    `getattr(x, "prompt_overrides")`. A dict key of that name is not counted — that is the
    *stored preference* (`users.preferences`), whose one path into a `RunConfig` is the
    writer test named above.
    """

    def __init__(self) -> None:
        self.scope: list[str] = []
        self.reads: set[str] = set()

    def _enter(self, node) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _enter

    def _record(self) -> None:
        self.reads.add(".".join(self.scope) or "<module>")

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr == "prompt_overrides" and isinstance(node.ctx, ast.Load):
            self._record()
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == "prompt_overrides"
        ):
            self._record()
        self.generic_visit(node)


def test_the_override_is_read_only_inside_system_prompt():
    reads = set()
    for rel, tree in _runtime_trees():
        visitor = _OverrideReads()
        visitor.visit(tree)
        reads |= {(rel, scope) for scope in visitor.reads}

    assert reads == {("research_engine/prompt_composition.py", "system_prompt")}, (
        "RunConfig.prompt_overrides must have exactly one reader, "
        f"prompt_composition.system_prompt; found {sorted(reads)}"
    )


def test_every_graph_prompt_is_system_message_content():
    tree = ast.parse((BACKEND / "research_engine/graph.py").read_text("utf-8"))
    parent = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}

    aliased = [
        a.asname
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for a in node.names
        if a.name == "system_prompt" and a.asname
    ]
    assert not aliased, f"system_prompt imported under another name: {aliased}"

    refs = [
        n
        for n in ast.walk(tree)
        if (isinstance(n, ast.Name) and n.id == "system_prompt")
        or (isinstance(n, ast.Attribute) and n.attr == "system_prompt")
    ]
    # Without this the loop below passes on a graph that composes nothing at all.
    assert refs, "graph.py no longer calls system_prompt — this test is checking nothing"

    misplaced = []
    for ref in refs:
        call = parent.get(ref)
        if not (isinstance(call, ast.Call) and call.func is ref):
            misplaced.append(f"line {ref.lineno}: referenced without being called")
            continue
        holder = parent.get(call)
        if isinstance(holder, ast.keyword) and holder.arg == "content":
            message = parent.get(holder)
        elif isinstance(holder, ast.Call) and holder.args and holder.args[0] is call:
            message = holder
        else:
            message = None
        if not (
            isinstance(message, ast.Call)
            and isinstance(message.func, ast.Name)
            and message.func.id == "SystemMessage"
        ):
            misplaced.append(f"line {call.lineno}: result is not SystemMessage content")

    assert not misplaced, "system_prompt output used outside a system message:\n" + "\n".join(
        misplaced
    )


def test_the_control_plane_list_names_real_fields():
    """A misspelt entry would make the preference check below pass vacuously."""
    assert set(CONTROL_PLANE_FIELDS) <= {f.name for f in fields(RunConfig)}


def test_no_control_plane_field_is_a_user_preference():
    exposed = set(CONTROL_PLANE_FIELDS) & (
        set(PREFERENCE_FIELDS) | set(UserPreferences.model_fields)
    )
    assert not exposed, f"settable through user preferences: {sorted(exposed)}"
