"""
`desktop/sidecar.py` is a thin adapter, and a line count is how that stays true (plan
phase 11).

Phase 6 declined to physically move the run/session/project/corpus handlers into
`app/handlers/` — `test_one_canonical_owner` already proves single ownership by identity,
so the move would rename files without closing a gap (`internal/plans/13_
One_Runtime_Two_Hosts.md` §0.10). That decision means `sidecar.py` legitimately keeps code
no thin transport layer would: the desktop-only routes (`/desktop/keys/*`, `/local/start`,
`/local/stop`, the flat `/corpus/*` convenience routes), and the host implementations of
every port this plan built (`_DesktopCorpusLocator`, `get_checkpoint_deleter`,
`get_terminal_event_emitter`, `sidecar_run_config`). Revision 1's target of "~450 lines"
assumed the handler move would happen; it did not, so that number is not a ceiling this
file can honestly reach and is not used here.

What this file still guards: the file should never grow *without someone noticing*. Every
phase in this plan that delegated a route shrank `sidecar.py` — Phase 7 by ~700 lines
across the run, session, project and corpus surfaces combined. A ceiling that only ever
rises would let that trend reverse silently, one route at a time, the same way the
duplication this whole plan exists to remove first accumulated.

`CEILING` ratchets down as more delegates and is lowered in the same commit that shrinks
the file — never raised to make a growing file pass. Growing past it is not necessarily
wrong (a new desktop-only feature needs somewhere to live), but it must be a deliberate
edit to this number with a reason, not a side effect nobody reviewed.
"""

from __future__ import annotations

from pathlib import Path

SIDECAR = Path(__file__).resolve().parents[2] / "desktop" / "sidecar.py"

#: 2,876 lines as of the Windows shell-watchdog fix (`shell_alive`/`_win32_pid_alive`,
#: plus the sidecar finally calling `configure_logging` — both genuine desktop-only
#: code with no `app/api/v1/*` route to delegate to: process supervision and logging
#: bootstrap for a process that is not itself an HTTP handler). Was 2,850 (itself down
#: from 3,015 before plan phase 7 began delegating session routes). Small headroom above
#: the current count, not a target to grow into.
CEILING = 2900


def test_sidecar_has_not_grown_past_its_ratchet():
    lines = SIDECAR.read_text(encoding="utf-8").count("\n")
    assert lines <= CEILING, (
        f"desktop/sidecar.py is {lines} lines, over the {CEILING}-line ratchet. If this "
        "growth is a new route that should delegate to app/api/v1/*, delegate it instead "
        "of raising the ceiling. If it is a genuine new desktop-only feature, raise "
        "CEILING in this file, in the same commit, with a reason in the commit message."
    )


def test_the_ceiling_itself_has_not_gone_stale():
    """The other direction: a ceiling left high after the file shrank is a ceiling that
    stopped doing its job — the next 200 lines of drift would pass silently until this
    caught up. Same anti-rot shape as `DIVERGENT_BY_DESIGN`'s own tests: the number is
    allowed to be generous, not allowed to be forgotten."""
    lines = SIDECAR.read_text(encoding="utf-8").count("\n")
    slack = CEILING - lines
    assert slack < 200, (
        f"desktop/sidecar.py is {lines} lines but CEILING is {CEILING} — {slack} lines of "
        "slack. Lower CEILING to close the gap; a ceiling this loose stops catching growth."
    )
