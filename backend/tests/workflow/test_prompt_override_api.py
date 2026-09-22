"""
Saving a replacement prompt over the real routes, on both hosts.

The schema tests next door pin what `UserPreferences` accepts. This pins what the *routes*
do with it — which is a separate question on this codebase, because until PR-5 the desktop
did not validate preferences at all. It read `body["preferences"]` and merged it, so a
preference the server refused with a 422 was stored on the desktop without complaint.

For `retrieval_k` that gap was harmless. For `prompt_overrides` it sits directly on the
boundary PR-4 drew, so both hosts now validate through the same model and merge through the
same function. These tests drive the desktop's real routes, which need no Postgres; the
server-side equivalent uses the shared client fixture and skips where no database is
reachable, the same as every other server route test here.

Nothing consumes an override yet. What is asserted is storage, refusal, and reset.
"""

from __future__ import annotations

import httpx
import pytest

from app.schemas.auth import MAX_PROMPT_OVERRIDE_CHARS
from desktop.sidecar import create_sidecar_app

TOKEN = "test-prompt-override-token"
VALID = "You are a meticulous planner. Prefer primary sources over summaries."


@pytest.fixture
async def desktop(tmp_path):
    app = create_sidecar_app(data_dir=tmp_path, token=TOKEN, fake=True)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9") as c:
            yield c


AUTH = {"Authorization": f"Bearer {TOKEN}"}


async def _patch(client, overrides):
    return await client.patch(
        "/api/v1/auth/me", headers=AUTH, json={"preferences": {"prompt_overrides": overrides}}
    )


async def _stored(client):
    resp = await client.get("/api/v1/auth/me", headers=AUTH)
    assert resp.status_code == 200, resp.text
    return (resp.json().get("preferences") or {}).get("prompt_overrides")


# ── Persistence ───────────────────────────────────────────────────────────────────


async def test_an_override_round_trips(desktop):
    assert (await _patch(desktop, {"planner": VALID})).status_code == 200
    assert await _stored(desktop) == {"planner": VALID}


async def test_setting_a_second_role_keeps_the_first(desktop):
    """The merge, over the real route: preferences arrive a section at a time."""
    await _patch(desktop, {"planner": VALID})
    await _patch(desktop, {"critic": "Grade strictly."})
    assert await _stored(desktop) == {"planner": VALID, "critic": "Grade strictly."}


async def test_null_resets_one_role_and_leaves_the_rest(desktop):
    await _patch(desktop, {"planner": VALID, "critic": "Grade strictly."})
    assert (await _patch(desktop, {"critic": None})).status_code == 200
    assert await _stored(desktop) == {"planner": VALID}


async def test_resetting_the_last_override_leaves_nothing_behind(desktop):
    await _patch(desktop, {"planner": VALID})
    await _patch(desktop, {"planner": None})
    assert await _stored(desktop) in (None, {})


async def test_an_unrelated_preference_does_not_disturb_the_overrides(desktop):
    await _patch(desktop, {"planner": VALID})
    resp = await desktop.patch(
        "/api/v1/auth/me", headers=AUTH, json={"preferences": {"retrieval_k": 9}}
    )
    assert resp.status_code == 200, resp.text
    assert await _stored(desktop) == {"planner": VALID}


# ── Refusals, on the host that used to accept anything ────────────────────────────


@pytest.mark.parametrize(
    ("overrides", "because"),
    [
        ({"critic": ""}, "empty string"),
        ({"critic": "   "}, "whitespace only"),
        ({"critic": 42}, "non-string"),
        ({"critic": ["a"]}, "non-string"),
        ({"researcher": VALID}, "unknown role"),
        ({"critic.citation_verify": VALID}, "a purpose, not a role"),
        ({"critic": "x" * (MAX_PROMPT_OVERRIDE_CHARS + 1)}, "over the length limit"),
    ],
)
async def test_the_desktop_refuses_what_the_server_refuses(desktop, overrides, because):
    """Before PR-5 every one of these was stored here without complaint."""
    resp = await _patch(desktop, overrides)
    assert resp.status_code == 422, f"{because}: got {resp.status_code}"
    assert await _stored(desktop) is None, f"{because}: a refused value was still stored"


async def test_a_refusal_leaves_an_existing_override_untouched(desktop):
    """A rejected request must not be a partial write."""
    await _patch(desktop, {"planner": VALID})
    assert (await _patch(desktop, {"planner": ""})).status_code == 422
    assert await _stored(desktop) == {"planner": VALID}


async def test_exactly_the_maximum_is_accepted_over_the_route(desktop):
    text = "x" * MAX_PROMPT_OVERRIDE_CHARS
    assert (await _patch(desktop, {"synthesizer": text})).status_code == 200
    assert (await _stored(desktop))["synthesizer"] == text


async def test_the_desktop_still_validates_the_preferences_that_predate_this_field(desktop):
    """The gap this closes was never specific to prompt overrides — `retrieval_k` has an
    `le=20` bound the server enforced and this host did not."""
    resp = await desktop.patch(
        "/api/v1/auth/me", headers=AUTH, json={"preferences": {"retrieval_k": 99}}
    )
    assert resp.status_code == 422, resp.text


async def test_an_absent_field_changes_nothing(desktop):
    """Requirement 18: an account that never opens the editor is unaffected."""
    resp = await desktop.patch(
        "/api/v1/auth/me", headers=AUTH, json={"preferences": {"density": "compact"}}
    )
    assert resp.status_code == 200, resp.text
    assert await _stored(desktop) is None


# ── The compatibility change, tested rather than assumed ──────────────────────────
#
# Routing the desktop PATCH through `UserPreferences` was a deliberate compatibility change,
# not a side effect of adding a field. This host previously merged whatever JSON arrived, so
# *every* preference — not just the new one — was stored unvalidated while the server refused
# the same body with a 422. Two hosts, one contract, and only one of them enforcing it.
#
# The tests below pin both halves of that change: the values that were valid before are still
# accepted, and the values the server has always refused are now refused here too. They exist
# so the behaviour change is a decision somebody can read, and so a regression in either
# direction fails loudly.


PREEXISTING_VALID = [
    ("retrieval_k", 1),
    ("retrieval_k", 20),
    ("min_sources_per_task", 0),
    ("min_sources_per_task", 20),
    ("snippet_max_chars", 100),
    ("snippet_max_chars", 500),
    ("density", "comfortable"),
    ("density", "compact"),
    ("tavily_api_key", "tvly-" + "x" * 190),
    ("brave_api_key", "brave-key"),
]

#: Bodies this host used to store silently and the server has always rejected. The bound
#: each one crosses is the one already declared on `UserPreferences`; nothing new was added
#: to those fields by PR-5.
PREEXISTING_NOW_REFUSED = [
    ("retrieval_k", 0, "below ge=1"),
    ("retrieval_k", 21, "above le=20"),
    ("retrieval_k", "nine", "not an int"),
    ("min_sources_per_task", -1, "below ge=0"),
    ("min_sources_per_task", 21, "above le=20"),
    ("snippet_max_chars", 99, "below ge=100"),
    ("snippet_max_chars", 501, "above le=500"),
    ("density", "roomy", "not in the Literal"),
    ("tavily_api_key", "x" * 201, "over max_length=200"),
    ("brave_api_key", "x" * 201, "over max_length=200"),
]


@pytest.mark.parametrize(("field", "value"), PREEXISTING_VALID)
async def test_a_previously_valid_preference_is_still_accepted(desktop, field, value):
    """The compatibility half: nothing a working client sent before is refused now."""
    resp = await desktop.patch(
        "/api/v1/auth/me", headers=AUTH, json={"preferences": {field: value}}
    )
    assert resp.status_code == 200, resp.text
    stored = (resp.json().get("preferences") or {}).get(field)
    assert stored == value


@pytest.mark.parametrize(("field", "value", "because"), PREEXISTING_NOW_REFUSED)
async def test_a_previously_unvalidated_preference_is_now_refused(desktop, field, value, because):
    """**Intentional behaviour change.** Each of these was stored by this host before PR-5
    and refused by the server. The desktop now answers the same way."""
    resp = await desktop.patch(
        "/api/v1/auth/me", headers=AUTH, json={"preferences": {field: value}}
    )
    assert resp.status_code == 422, f"{field}={value!r} ({because}): got {resp.status_code}"
    me = await desktop.get("/api/v1/auth/me", headers=AUTH)
    assert (me.json().get("preferences") or {}).get(field) is None, (
        f"{field} was stored despite the refusal"
    )


async def test_an_unknown_preference_key_is_now_refused_on_the_desktop_too(desktop):
    """`extra="forbid"` has always been on the model; this host simply never ran it."""
    resp = await desktop.patch(
        "/api/v1/auth/me", headers=AUTH, json={"preferences": {"not_a_preference": 1}}
    )
    assert resp.status_code == 422, resp.text


async def test_a_refused_body_does_not_disturb_preferences_already_stored(desktop):
    """A rejected request is not a partial write, for the pre-existing fields either."""
    ok = await desktop.patch(
        "/api/v1/auth/me", headers=AUTH, json={"preferences": {"retrieval_k": 9}}
    )
    assert ok.status_code == 200
    bad = await desktop.patch(
        "/api/v1/auth/me", headers=AUTH, json={"preferences": {"retrieval_k": 999}}
    )
    assert bad.status_code == 422
    me = await desktop.get("/api/v1/auth/me", headers=AUTH)
    assert me.json()["preferences"]["retrieval_k"] == 9


async def test_profile_fields_still_update_alongside_preferences(desktop):
    """The route does more than preferences; validating the body must not break the rest."""
    resp = await desktop.patch(
        "/api/v1/auth/me",
        headers=AUTH,
        json={"display_name": "Local Researcher", "preferences": {"retrieval_k": 7}},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["display_name"] == "Local Researcher"
    assert resp.json()["preferences"]["retrieval_k"] == 7


async def test_a_request_with_no_preferences_key_is_unaffected(desktop):
    """Requirement 18: the path that never mentions preferences behaves exactly as before."""
    resp = await desktop.patch("/api/v1/auth/me", headers=AUTH, json={"display_name": "Solo"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["display_name"] == "Solo"
