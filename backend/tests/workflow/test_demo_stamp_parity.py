"""
Demo-stamp parity between the two hosts (#52).

The server stamped `.md` and `.pdf` exports for demo sessions; the desktop sidecar did
not. `docs/user-guide/29-exports.md` said "every export path stamps the artifact", which
was true on the server and false on the desktop — so a scripted, fixture-sourced report
could leave the desktop app with nothing marking it as a demo. That is exactly the
artifact the `demo` flag exists to prevent.

The fix put the banner and the rule in `research_engine.bundle`, the host-agnostic export
home, and routed both hosts through `stamp_demo_md`. These tests pin the parts that can
silently drift back: that the rule is one implementation, that both hosts apply it, and
that the bundle stays unstamped on both.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

from research_engine import bundle


def test_stamp_is_applied_only_for_demo_sessions():
    body = "# Report\n\nA finding [1].\n"
    assert bundle.stamp_demo_md(body, demo=False) == body
    stamped = bundle.stamp_demo_md(body, demo=True)
    assert stamped.endswith(body)
    assert stamped.startswith(bundle.DEMO_STAMP_MD)
    assert "DEMO — NOT REAL RESEARCH" in stamped


def test_server_demo_constant_is_the_shared_one():
    """`app.api.v1.research._DEMO_STAMP` must be the shared object, not a copy.

    A copied string would pass a text comparison today and drift the first time either
    side is edited, which is the failure this issue was.
    """
    from app.api.v1 import research

    assert research._DEMO_STAMP is bundle.DEMO_STAMP_MD


def _calls_in(source: str, func_name: str) -> set[str]:
    """Dotted names actually *called* inside `func_name`, via AST.

    Deliberately not a substring search. The first version of this test grepped the
    source for "stamp_demo_md" and passed with the call deleted, because the explanatory
    comment above it still contained the word — the same use-versus-mention trap the
    repo's CI greps have hit (AGENTS.md). A call node cannot be faked by prose.
    """
    tree = ast.parse(textwrap.dedent(source))
    target = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name == func_name
        ),
        None,
    )
    assert target is not None, f"{func_name} not found"
    names = set()
    for node in ast.walk(target):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute):
                base = f.value
                if isinstance(base, ast.Name):
                    names.add(f"{base.id}.{f.attr}")
                names.add(f.attr)
            elif isinstance(f, ast.Name):
                names.add(f.id)
    return names


def test_both_hosts_route_markdown_export_through_the_shared_rule():
    """Source-level parity check, asserted on call nodes.

    Checked against each host's `.md` export rather than by rendering, because rendering
    the desktop route needs a live sidecar app and this must stay a fast unit test. The
    thing that regressed was a missing *call*, and that is what this detects.
    """
    from app.api.v1 import research as server

    assert "stamp_demo_md" in _calls_in(inspect.getsource(server._report_or_404), "_report_or_404")

    # The desktop's `.md` export no longer has a body of its own to inspect: it delegates
    # to the server's route (plan phase 7), so the rule cannot be missing from one host
    # without being missing from both. Asserted by identity, which is stronger than the
    # source check this used to make — a second implementation could have called
    # `stamp_demo_md` and still drifted in some other way.
    import tempfile

    from app.services.delegation import canonical_owner
    from desktop.sidecar import create_sidecar_app
    from tests.workflow.test_one_canonical_owner import _endpoints

    desktop = _endpoints(create_sidecar_app(data_dir=tempfile.mkdtemp(), token="stamp", fake=True))
    owner = canonical_owner(desktop["GET /research/{session_id}/export.md"])
    assert owner is server.export_markdown, (
        "the desktop .md export is no longer the server's, so the demo-stamp rule has two "
        "homes again"
    )


def test_bundle_is_never_stamped_on_either_host():
    """The deliberate asymmetry, pinned.

    `report_hash` is checked against the `draft_hash` recorded at approval, so prepending
    prose to the report body inside a bundle would break the approval chain and make every
    demo bundle fail verification for a reason unrelated to its integrity. The bundle
    carries `demo` as a hash-covered field instead.
    """
    from app.api.v1 import research as server

    assert "stamp_demo" in inspect.getsource(server._report_or_404), (
        "the bundle's opt-out parameter is gone"
    )

    import desktop.sidecar as sidecar

    src = inspect.getsource(sidecar)
    export_bundle = src[src.index("    async def export_bundle_json") :]
    export_bundle = export_bundle[: export_bundle.index("\n    @api.")]
    assert "stamp_demo_md" not in _calls_in(export_bundle, "export_bundle_json"), (
        "desktop bundle must not be prose-stamped"
    )
