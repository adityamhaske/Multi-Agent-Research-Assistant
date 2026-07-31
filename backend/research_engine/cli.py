"""
`research-engine` — a reference local host (docs/12 M6 step 4, its Definition of Done).

Runs the full pipeline on a bare machine: no Docker, no Postgres, no Redis, no login, no
server. State lives in one SQLite file, so the review gate works the way it should —
the run pauses, the process exits, and a later `--approve` resumes *from the checkpoint*
rather than re-running research you already paid for.

    research-engine "why do LLMs hallucinate?" --fake
    research-engine --approve <session-id>            # finalize the draft
    research-engine --reject <session-id> -f "cite more primary sources"

This is also the shape the desktop sidecar (docs/12 M9) will wrap: same engine, same
ports, same two local adapters — a Tauri shell instead of a terminal.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import uuid
from pathlib import Path

from research_engine.local import (
    InProcessEventSink,
    SqliteCache,
    default_data_dir,
    load_env_file,
    run_config_from_env,
)
from research_engine.runner import RunOutcome, resume, run

# ── Output ─────────────────────────────────────────────────────────────────────────

_AGENT_MARK = {
    "planner": "◆",
    "executor": "▸",
    "critic": "✓",
    "synthesizer": "■",
}


def _print_event(event: dict) -> None:
    agent = event.get("agent") or "-"
    message = event.get("message") or ""
    print(f"  {_AGENT_MARK.get(agent, '·')} {agent:<12} {message}", file=sys.stderr)


_SOURCES_HEADING_RE = re.compile(
    r"^#{1,6}\s*(sources|references|citations|bibliography)\b", re.I | re.M
)


def _print_outcome(outcome: RunOutcome, session_id: str) -> None:
    report = outcome.report or "(no report produced)"
    print()
    print(report)

    # The synthesizer already ends its report with a numbered source list, so only add a
    # panel when it didn't — otherwise every run prints "Sources" twice.
    if outcome.sources and not _SOURCES_HEADING_RE.search(report):
        print()
        print("## Sources")
        for source in outcome.sources:
            print(f"[{source.get('index')}] {source.get('title') or '(untitled)'}")
            print(f"    {source.get('url')}")

    print()
    print(
        f"— {outcome.status} · {len(outcome.sources)} sources · "
        f"${outcome.cost_usd:.4f} · {outcome.tokens_input + outcome.tokens_output} tokens"
        + (f" · {outcome.elapsed_seconds}s" if outcome.elapsed_seconds is not None else "")
    )

    if outcome.status == "awaiting_approval":
        print()
        print("Paused at the review gate. Nothing is final until you approve it:")
        print(f"  research-engine --approve {session_id}")
        print(f'  research-engine --reject {session_id} -f "what to fix"')
    elif outcome.status == "failed":
        print(f"\nFailed: {outcome.error}", file=sys.stderr)


# ── Run ────────────────────────────────────────────────────────────────────────────


async def _drive(args: argparse.Namespace) -> tuple[RunOutcome, str]:
    """Open the local checkpointer and cache, then run or resume.

    Returns the outcome *and* the session id, because a fresh run mints a random one and
    the caller has to print it — that id is the only way back to a paused draft.
    """
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    data_dir = Path(args.data_dir) if args.data_dir else default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    load_env_file()

    # The config carries the provider keys, so there is no separate `provider_keys` here —
    # that port exists for the server, where a *user's* BYOK key overrides the
    # deployment's. On a laptop there is only one set of keys.
    ports = {
        "event_sink": InProcessEventSink(on_event=None if args.quiet else _print_event),
        "cache": SqliteCache(data_dir / "cache.sqlite"),
        "run_config": run_config_from_env(fake=args.fake),
    }

    async with AsyncSqliteSaver.from_conn_string(str(data_dir / "checkpoints.sqlite")) as saver:
        await saver.setup()

        if args.approve or args.reject:
            session_id = args.approve or args.reject
            outcome = await resume(
                checkpointer=saver,
                session_id=session_id,
                approved=bool(args.approve),
                feedback=args.feedback,
                **ports,
            )
            return outcome, session_id

        session_id = args.session_id or f"local-{uuid.uuid4().hex[:12]}"
        outcome = await run(
            checkpointer=saver,
            session_id=session_id,
            user_id="local",
            query=args.query,
            depth=args.depth,
            **ports,
        )
        # Approving in the same process still resumes from the checkpoint — the graph
        # re-enters at the gate, it does not replan.
        if args.yes and outcome.status == "awaiting_approval":
            outcome = await resume(
                checkpointer=saver, session_id=session_id, approved=True, **ports
            )
        return outcome, session_id


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="research-engine",
        description="Run the research pipeline locally — no server, no Docker, no login.",
    )
    parser.add_argument("query", nargs="?", help="the research question")
    parser.add_argument(
        "--depth", default="balanced", choices=["fast", "balanced", "comprehensive"]
    )
    parser.add_argument(
        "--fake",
        action="store_true",
        help="scripted models and fixture sources — no API key, no network",
    )
    parser.add_argument("--approve", metavar="SESSION_ID", help="finalize a paused draft")
    parser.add_argument("--reject", metavar="SESSION_ID", help="send a paused draft back")
    parser.add_argument("-f", "--feedback", help="feedback to accompany --reject")
    parser.add_argument(
        "--yes", action="store_true", help="approve immediately (skips the gate; for demos)"
    )
    parser.add_argument("--session-id", help="use a specific session id instead of a random one")
    parser.add_argument(
        "--data-dir", help=f"where to keep local state (default: {default_data_dir()})"
    )
    parser.add_argument("--json", action="store_true", help="emit the outcome as JSON")
    parser.add_argument("--quiet", action="store_true", help="don't stream progress to stderr")

    args = parser.parse_args(argv)
    if not (args.query or args.approve or args.reject):
        parser.error("give a query, or --approve/--reject a session id")
    if args.reject and not args.feedback:
        parser.error("--reject needs -f/--feedback saying what to fix")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        outcome, session_id = asyncio.run(_drive(args))
    except KeyboardInterrupt:  # pragma: no cover - interactive
        print("\ninterrupted", file=sys.stderr)
        return 130
    except ValueError as e:
        # Model factory and config errors already carry actionable messages; a traceback
        # would bury them.
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.json:
        payload = {
            "status": outcome.status,
            "report": outcome.report,
            "sources": outcome.sources,
            "cost_usd": outcome.cost_usd,
            "tokens_input": outcome.tokens_input,
            "tokens_output": outcome.tokens_output,
            "rework_count": outcome.rework_count,
            "elapsed_seconds": outcome.elapsed_seconds,
            "error": outcome.error,
        }
        print(json.dumps(payload, indent=2))
    else:
        _print_outcome(outcome, session_id)

    return 1 if outcome.status == "failed" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
