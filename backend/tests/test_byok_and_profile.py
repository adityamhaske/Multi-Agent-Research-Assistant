"""
BYOK key handling and profile/usage schema tests (docs/06 §1, docs/07).

The security-relevant invariants here: a user key is never stored or returned in
plaintext, one user's key never leaks into another's run, and an undecryptable
key degrades to the server key instead of crashing the pipeline.
"""

import pytest
from pydantic import ValidationError

from app.agent import llm_factory
from app.schemas.auth import ApiKeyRequest, ProfileUpdate, UsageWindow
from app.services import crypto

KEY = "AIzaSyEXAMPLEuserkey1234567890abcd"


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
