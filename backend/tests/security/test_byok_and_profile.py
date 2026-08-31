"""
BYOK key handling and profile/usage schema tests (docs/06 §1, docs/07).

The security-relevant invariants here: a user key is never stored or returned in
plaintext, one user's key never leaks into another's run, and an undecryptable
key degrades to the server key instead of crashing the pipeline.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.schemas.auth import ApiKeyLabelRequest, ApiKeyRequest, ProfileUpdate, UsageWindow
from app.services import crypto
from research_engine import llm_factory

KEY = "AIzaSyEXAMPLEuserkey1234567890abcd"
CUSTOM_KEY = "sk-example-custom-endpoint-key-0001"
PASSWORD = "Str0ng-P@ssw0rd-For-Tests!"

# No `pytestmark = pytest.mark.asyncio` here: pyproject.toml sets `asyncio_mode =
# "auto"`, so the marker is unnecessary — and this file, unlike test_auth_rate_limit.py,
# mixes sync schema tests with the async route tests below, where an unconditional
# module-level marker would misapply to every sync `def test_...` and warn.


# ── Encryption ───────────────────────────────────────────────────────────────


def test_encrypt_does_not_store_plaintext():
    ciphertext = crypto.encrypt(KEY)
    assert KEY not in ciphertext
    assert ciphertext != KEY


def test_encrypt_roundtrips():
    assert crypto.decrypt(crypto.encrypt(KEY)) == KEY


def test_encrypt_is_non_deterministic():
    # Fernet embeds a timestamp+IV, so two encryptions of the same key differ —
    # stored ciphertexts can't be correlated across users.
    assert crypto.encrypt(KEY) != crypto.encrypt(KEY)


def test_decrypt_returns_none_on_garbage():
    # A rotated signing secret must degrade, not raise, inside the worker.
    assert crypto.decrypt("not-a-valid-token") is None


def test_hint_reveals_only_last_four_chars():
    h = crypto.hint(KEY)
    assert h == "…abcd"
    assert KEY[:-4] not in h


# ── Per-user key resolution ──────────────────────────────────────────────────


def test_user_key_overrides_server_key_then_resets():
    before = llm_factory.api_key_for("google")
    token = llm_factory.set_user_keys({"google": "user-key"})
    try:
        assert llm_factory.api_key_for("google") == "user-key"
    finally:
        llm_factory.reset_user_keys(token)
    assert llm_factory.api_key_for("google") == before


def test_user_key_does_not_leak_across_providers():
    token = llm_factory.set_user_keys({"google": "user-key"})
    try:
        # A Google BYOK key must not be handed to Anthropic.
        assert llm_factory.api_key_for("anthropic") != "user-key"
    finally:
        llm_factory.reset_user_keys(token)


def test_build_raises_actionable_error_without_any_key():
    token = llm_factory.set_user_keys({})
    try:
        with pytest.raises(ValueError, match="No API key available"):
            llm_factory._build("anthropic", "claude-opus-4-8", "planner")
    finally:
        llm_factory.reset_user_keys(token)


def test_user_provider_keys_builds_the_dict_from_an_encrypted_column():
    """The shape three call sites used to build by hand: `{provider: key}`, plus a
    `{provider}_base_url` entry when the user pointed the key at a custom endpoint."""
    from app.models.user import User

    user = User(api_key_encrypted=crypto.encrypt(KEY), api_key_provider="google")
    assert crypto.user_provider_keys(user) == {"google": KEY}


def test_user_provider_keys_includes_the_base_url_when_set():
    from app.models.user import User

    user = User(
        api_key_encrypted=crypto.encrypt(CUSTOM_KEY),
        api_key_provider="custom",
        api_key_base_url="https://example.invalid/v1",
    )
    assert crypto.user_provider_keys(user) == {
        "custom": CUSTOM_KEY,
        "custom_base_url": "https://example.invalid/v1",
    }


def test_user_provider_keys_is_empty_with_no_key_stored():
    from app.models.user import User

    assert crypto.user_provider_keys(User()) == {}


def test_user_provider_keys_is_empty_when_provider_is_unset():
    """A ciphertext with no declared provider is not a usable key — nothing would
    consume `{None: key}`, so this must degrade the same as no key at all."""
    from app.models.user import User

    user = User(api_key_encrypted=crypto.encrypt(KEY), api_key_provider=None)
    assert crypto.user_provider_keys(user) == {}


def test_user_provider_keys_degrades_on_a_key_that_will_not_decrypt():
    """Same degrade-don't-crash rule `decrypt()` documents, carried through the dict
    builder: a rotated signing secret must not turn a chat request into a 500."""
    from app.models.user import User

    user = User(api_key_encrypted="not-a-valid-fernet-token", api_key_provider="google")
    assert crypto.user_provider_keys(user) == {}


def test_chat_and_threads_no_longer_restate_the_key_builder():
    """Three modules built this exact dict by hand — `crypto.py`, `chat.py`,
    `threads.py` — and `pipeline_runner.py` a fourth time inline. `user_provider_keys`
    is the one home; a route module keeping its own copy is the bug this guards."""
    from app.api.v1 import chat, threads

    assert not hasattr(chat, "_user_provider_keys"), (
        "chat.py has its own key-dict builder again instead of calling crypto.user_provider_keys"
    )
    assert not hasattr(threads, "_user_keys"), (
        "threads.py has its own key-dict builder again instead of calling crypto.user_provider_keys"
    )


# ── Profile validation ───────────────────────────────────────────────────────


def test_api_key_request_rejects_unknown_provider():
    with pytest.raises(ValidationError):
        ApiKeyRequest(provider="hackerprovider", api_key=KEY)


def test_profile_rejects_javascript_avatar_url():
    # avatar_url is rendered in an <img>; a javascript:/data: URL must not persist.
    with pytest.raises(ValidationError):
        ProfileUpdate(avatar_url="javascript:alert(1)")


def test_profile_accepts_https_avatar_and_blank_clears():
    assert ProfileUpdate(avatar_url="https://example.com/a.png").avatar_url is not None
    assert ProfileUpdate(avatar_url="").avatar_url is None


def test_profile_rejects_negative_token_limit():
    with pytest.raises(ValidationError):
        ProfileUpdate(monthly_token_limit=-5)


def test_usage_window_defaults_to_zero():
    w = UsageWindow()
    assert (w.tokens_total, w.cost_usd, w.sessions) == (0, 0.0, 0)


# ── Password change ──────────────────────────────────────────────────────────


def test_password_change_requires_min_length():
    from app.schemas.auth import PasswordChangeRequest

    with pytest.raises(ValidationError):
        PasswordChangeRequest(current_password="whatever", new_password="short")


def test_password_change_accepts_a_strong_new_password():
    from app.schemas.auth import PasswordChangeRequest

    req = PasswordChangeRequest(
        current_password="old-correct-horse-battery",
        new_password="new-correct-horse-battery",
    )
    assert req.new_password != req.current_password


def test_password_policy_rejects_common_choices():
    from app.services.passwords import WeakPassword, validate_password

    with pytest.raises(WeakPassword):
        validate_password("password123")


def test_auth_service_exposes_public_revoke_all():
    # The password-change flow signs out other devices; that entry point must be
    # public API, not a private helper that could be renamed out from under it.
    from app.services import auth_service

    assert callable(auth_service.revoke_all_for_user)


# ── Connection nickname (rename) ─────────────────────────────────────────────
#
# `PATCH /me/api-key/label` route-level behaviour, driven through the real app the
# way test_auth_rate_limit.py does, not through the schema alone — the guard that
# matters ("nothing to rename yet") lives in the route, not in ApiKeyLabelRequest.


def test_label_request_blank_clears_to_none():
    assert ApiKeyLabelRequest(label="  ").label is None
    assert ApiKeyLabelRequest(label="OmniRoute").label == "OmniRoute"


def test_label_request_rejects_overlong_label():
    with pytest.raises(ValidationError):
        ApiKeyLabelRequest(label="x" * 61)


@pytest.fixture
async def client(db):  # noqa: ARG001 - ordering dependency, see test_auth_rate_limit.py
    from app.main import app

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def _registered_client(client: AsyncClient) -> AsyncClient:
    """A client authenticated as a fresh user.

    Registration is deliberately neutral (no account-enumeration signal) and does not
    set a session cookie — login is a separate call, same as a real sign-up flow.

    A distinct `x-forwarded-for` per call, the same device test_auth_rate_limit.py
    uses (`_fresh_ip`) — without it every registration in this module shares one
    IP and the suite trips its own `REGISTER_IP` cap (issue #51) well before five
    tests have run.
    """
    ip = f"203.0.113.{uuid.uuid4().int % 254 + 1}-{uuid.uuid4().hex[:8]}"
    email = f"{uuid.uuid4().hex}@example.com"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD},
        headers={"x-forwarded-for": ip},
    )
    assert resp.status_code == 201, resp.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return client


async def _save_custom_key(client: AsyncClient) -> None:
    # provider="custom" with no base_url makes provider_health.probe return early
    # (`"A base URL is required"`) without an outbound request — the label routes
    # under test never touch it, but PUT /me/api-key always probes on save.
    resp = await client.put(
        "/api/v1/auth/me/api-key",
        json={"provider": "custom", "api_key": CUSTOM_KEY},
    )
    assert resp.status_code == 200, resp.text


async def test_rename_requires_an_active_key(client: AsyncClient):
    await _registered_client(client)
    resp = await client.patch("/api/v1/auth/me/api-key/label", json={"label": "OmniRoute"})
    assert resp.status_code == 404
    assert "connection" in resp.json()["detail"].lower()


async def test_rename_sets_the_label_without_touching_the_key(client: AsyncClient):
    await _registered_client(client)
    await _save_custom_key(client)

    resp = await client.patch("/api/v1/auth/me/api-key/label", json={"label": "OmniRoute"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["api_key_label"] == "OmniRoute"
    # Renaming must not disturb what it did not touch.
    assert body["api_key_provider"] == "custom"
    assert body["api_key_hint"] is not None

    me = await client.get("/api/v1/auth/me")
    assert me.json()["api_key_label"] == "OmniRoute"


async def test_rename_blank_reverts_to_the_catalog_label(client: AsyncClient):
    await _registered_client(client)
    await _save_custom_key(client)
    await client.patch("/api/v1/auth/me/api-key/label", json={"label": "OmniRoute"})

    resp = await client.patch("/api/v1/auth/me/api-key/label", json={"label": "  "})
    assert resp.status_code == 200
    assert resp.json()["api_key_label"] is None


async def test_replacing_the_key_preserves_the_label(client: AsyncClient):
    """A nickname describes which gateway this is, not which token is on file — a
    key rotation must not silently blank a name the user already chose."""
    await _registered_client(client)
    await _save_custom_key(client)
    await client.patch("/api/v1/auth/me/api-key/label", json={"label": "OmniRoute"})

    resp = await client.put(
        "/api/v1/auth/me/api-key",
        json={"provider": "custom", "api_key": CUSTOM_KEY + "-rotated"},
    )
    assert resp.status_code == 200
    assert resp.json()["api_key_label"] == "OmniRoute"


async def test_deleting_the_key_clears_the_label(client: AsyncClient):
    await _registered_client(client)
    await _save_custom_key(client)
    await client.patch("/api/v1/auth/me/api-key/label", json={"label": "OmniRoute"})

    resp = await client.delete("/api/v1/auth/me/api-key")
    assert resp.status_code == 200
    assert resp.json()["api_key_label"] is None

    # And the row is now clean, so renaming again is refused for the same reason a
    # never-configured account is refused.
    again = await client.patch("/api/v1/auth/me/api-key/label", json={"label": "New"})
    assert again.status_code == 404
