"""
What this host can do, as a thing a client can read.

Product-design differences between the two hosts have until now been recorded in three
places that a running system does not expose: `INTENTIONAL_SERVER_ONLY` and
`INTENTIONAL_DESKTOP_ONLY` in the parity tests, prose in the release notes, and
`isDesktop` branches in the frontend. The last of those is the problem — the client decides
what the product can do by inspecting *which build it is*, which means every new capability
difference is a new branch, and a branch is where the two hosts drift.

So the host says what it can do, and the client asks.

**A capability is not a gap.** `KNOWN_DESKTOP_GAPS` is a defect list and stays empty: an
entry there is a control that ships broken. A capability difference is a decision — project
memory is pgvector-backed, the desktop has no Postgres — and the route for it answers `501`
with `capability` naming which one, never a `404`. The difference between "you asked wrong"
and "this host does not do that" is the whole point.

Pure pydantic; both hosts import it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Capabilities(BaseModel):
    """One shape, two answers.

    Every field is a *product* capability, never an infrastructure detail. A client has no
    business knowing whether a host runs Postgres or SQLite, Celery or an event loop —
    those differences are real and permanent and none of them belong here. What belongs is
    what a person can and cannot do.
    """

    #: User accounts: registration, login, a profile, a password, per-account spend
    #: limits. The desktop is one local user behind a per-launch token and has none of it —
    #: which is why it hides Profile and Log out, and why "usage tracking and spending
    #: limits" has nothing to show. Its own field rather than inferred from `rate_limits`:
    #: rate limiting happens to be absent for the same underlying reason, but "this host
    #: does not throttle" and "this host has no accounts" are two claims, and a client that
    #: reads one to mean the other will be wrong the first time they come apart.
    accounts: bool

    #: Retrieval over previously approved reports in this project. pgvector-backed, so the
    #: desktop does not have it — stated in the v1.0.0 release notes and, until now, only
    #: discoverable by reading them.
    project_memory: bool

    #: Chat scoped to a whole project, citing every approved report in it. Sits on project
    #: memory, so it goes where that goes.
    project_chat: bool

    #: Server-rendered PDF export. The desktop prints through the WebView instead, so
    #: `export.pdf` answers 501 there by design and always has.
    server_pdf: bool

    #: Whether this host enforces request rate limits. **False on the desktop, and stated
    #: rather than implemented as a no-op**: a limiter whose implementation always returns
    #: "allowed" is a security control that reads as present and enforces nothing. One
    #: local user behind a per-launch token on a loopback socket is a different threat
    #: model, and saying so is honest where a stub would not be.
    rate_limits: bool

    #: Starting and stopping a local Ollama process. The desktop app can; a container
    #: cannot reach the host's process table, and should not.
    local_llm_control: bool

    #: Where a provider key is kept. Not a boolean, because both hosts store keys — the
    #: difference is where, and the settings screen has to say which.
    byok_storage: Literal["encrypted_column", "os_keychain"]

    #: Which host answered, for a support conversation. Deliberately last and deliberately
    #: not something the client should branch on: every decision above is named explicitly
    #: so that reading this field to infer a capability is always the wrong move.
    host: Literal["server", "desktop"] = Field(
        description="Identifies the host. Branch on the capabilities above, never on this."
    )


SERVER = Capabilities(
    accounts=True,
    project_memory=True,
    project_chat=True,
    server_pdf=True,
    rate_limits=True,
    local_llm_control=False,
    byok_storage="encrypted_column",
    host="server",
)

DESKTOP = Capabilities(
    accounts=False,
    project_memory=False,
    project_chat=False,
    server_pdf=False,
    rate_limits=False,
    local_llm_control=True,
    byok_storage="os_keychain",
    host="desktop",
)
