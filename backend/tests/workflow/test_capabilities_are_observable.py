"""
A capability difference is behaviour a client can read, not a claim in a table (Phase 10).

Until now the two hosts' product-design differences lived in three places a running system
does not expose: `INTENTIONAL_SERVER_ONLY`/`INTENTIONAL_DESKTOP_ONLY` in the parity tests,
prose in the release notes, and `isDesktop` branches in the frontend. The last is the
problem — the client decides what the product can do by inspecting *which build it is*, so
every new capability difference is a new branch, and a branch is where two hosts drift.

Two rules, and they are different rules:

- **`KNOWN_DESKTOP_GAPS` stays empty.** It is a defect list. An entry there is a control
  that ships broken, and `AGENTS.md` is explicit that it must not become "a permanent
  dumping ground for parity problems".
- **A capability difference is a decision**, and the route for it answers `501` naming the
  capability — never `404`, never an empty result. "You asked wrong", "this host does not
  do that" and "there is nothing here" are three different statements, and only one of them
  is true.

The second is what makes this testable rather than declarative: the desktop's memory index
raises `CapabilityUnavailable("project_memory")`, so the difference is observable at the
point a client meets it.
"""

from __future__ import annotations

import tempfile

import httpx
import pytest

from app.schemas.capabilities import DESKTOP, SERVER, Capabilities


def _desktop_app():
    from desktop.sidecar import create_sidecar_app

    return create_sidecar_app(data_dir=tempfile.mkdtemp(), token="caps", fake=True)


# ── One shape, two answers ────────────────────────────────────────────────────────


def test_both_hosts_answer_with_the_same_shape():
    """A client reads one type. A host that answered a different shape would push the
    branch back into the client, which is the thing being removed."""
    assert set(SERVER.model_dump()) == set(DESKTOP.model_dump()) == set(Capabilities.model_fields)


@pytest.mark.parametrize("capability", sorted(Capabilities.model_fields))
def test_every_capability_is_stated_by_both_hosts(capability):
    """No capability may be absent from one host's answer — absence is how a client ends up
    inferring it from the build flag again."""
    assert capability in SERVER.model_dump()
    assert capability in DESKTOP.model_dump()


def test_the_two_hosts_actually_differ_somewhere():
    """A capabilities endpoint on which both hosts agree about everything would be an
    elaborate way of saying nothing."""
    differences = {
        field
        for field in Capabilities.model_fields
        if getattr(SERVER, field) != getattr(DESKTOP, field)
    }
    differences.discard("host")
    assert differences, "the hosts report identical capabilities — then why is there a table?"


def test_no_capability_describes_infrastructure():
    """Postgres vs SQLite, Celery vs asyncio, Redis vs an in-process bus: all real, all
    permanent, none of them a client's business. A capability is what a *person* can do."""
    forbidden = ("postgres", "sqlite", "redis", "celery", "asyncio", "docker", "pgvector")
    for field in Capabilities.model_fields:
        assert not any(word in field.lower() for word in forbidden), (
            f"{field} names infrastructure; capabilities describe what a person can do"
        )


# ── Observable, not merely declared ───────────────────────────────────────────────


async def test_the_desktop_serves_its_capabilities_behind_the_token():
    app = _desktop_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://d.invalid") as client:
        assert (await client.get("/api/v1/capabilities")).status_code == 401
        resp = await client.get("/api/v1/capabilities", headers={"Authorization": "Bearer caps"})
    assert resp.status_code == 200
    assert resp.json()["project_memory"] is False
    assert resp.json()["host"] == "desktop"


async def test_an_absent_capability_refuses_with_its_own_name():
    """The rule that makes the table honest. A `404` would say the route does not exist; an
    empty result would say this project has nothing indexed. Both are false."""
    from app.errors import CapabilityUnavailable
    from desktop.sidecar import UnavailableMemoryIndex

    with pytest.raises(CapabilityUnavailable) as raised:
        await UnavailableMemoryIndex().nearest(
            None, project_id=None, query_vector=[0.0], embedding_model="m", limit=1
        )
    assert raised.value.capability == "project_memory"
    assert raised.value.capability in Capabilities.model_fields


def test_every_capability_the_desktop_lacks_maps_to_a_declared_route_difference():
    """The two records must agree.

    `INTENTIONAL_SERVER_ONLY` says which routes the desktop does not serve;
    `Capabilities` says which things it cannot do. If a capability is false but no route
    difference mentions it, one of the two is out of date — and the one a client reads is
    the one that will be believed.
    """
    from tests.workflow.test_host_parity import INTENTIONAL_SERVER_ONLY

    reasons = " ".join(INTENTIONAL_SERVER_ONLY.values()).lower()
    for capability in ("project_memory", "project_chat"):
        assert getattr(DESKTOP, capability) is False
        # The reasons name these in prose ("project memory is pgvector-only").
        assert capability.replace("_", " ") in reasons, (
            f"{capability} is false on the desktop but no route difference explains it"
        )


def test_rate_limits_are_declared_absent_rather_than_stubbed():
    """Constraint 7, made a test.

    An earlier revision of the plan had a `RateLimiter` port with a desktop implementation
    that always returned "allowed". That is a security control which reads as present and
    enforces nothing. Saying `rate_limits: false` is the honest form, and a stub would make
    this assertion pass while the guarantee it implies stayed false.
    """
    assert DESKTOP.rate_limits is False
    assert SERVER.rate_limits is True

    import app.ports as ports

    assert not hasattr(ports, "RateLimiter"), (
        "a RateLimiter port exists again — the desktop does not rate-limit, and an "
        "interface it satisfies with a no-op says otherwise"
    )
