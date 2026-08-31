"""
Symmetric encryption for user-supplied provider API keys (docs/06 §1).

BYOK keys are secrets belonging to the user, not to us: they are encrypted at
rest with Fernet (AES-128-CBC + HMAC) and only ever decrypted inside the worker
for the duration of that user's own pipeline run. They are never returned by any
endpoint, never logged, and never sent to the browser — the UI only ever sees a
non-reversible hint like "…aB3d".

The Fernet key is derived with HKDF-SHA256 from `ENCRYPTION_KEY` when set, else
from `JWT_SECRET_KEY`, so self-hosters get working encryption with no extra
setup. Deriving via a distinct `info` label keeps the key domain-separated from
JWT signing even when both come from the same secret.

Rotating the source secret makes existing ciphertexts undecryptable by design —
users re-enter their key (we surface that as "key needs re-entry", never a crash).
"""

from __future__ import annotations

import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import settings

_HKDF_INFO = b"mara.user-api-key.v1"


def _fernet() -> Fernet:
    secret = (getattr(settings, "encryption_key", "") or settings.jwt_secret_key).encode("utf-8")
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,  # secret is already high-entropy (>=32 chars, enforced at startup)
        info=_HKDF_INFO,
    ).derive(secret)
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt(plaintext: str) -> str:
    """Encrypt a secret for storage. Returns urlsafe base64 ciphertext."""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str) -> str | None:
    """Decrypt a stored secret. Returns None if it can't be decrypted (e.g. the
    signing secret was rotated) so callers degrade instead of raising."""
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        return None


def user_provider_keys(user) -> dict[str, str]:
    """`{provider: key}` for this user's stored BYOK key, `{}` if there is none to use.

    The one home for a dict three call sites (`chat.py`, `threads.py`,
    `pipeline_runner.py`) used to build by hand from the same three columns. A provider
    is required — a ciphertext with no declared provider is not addressable by anything
    that reads this dict, so it degrades the same as no key stored at all. Adds
    `{provider}_base_url` when the user pointed the key at a custom endpoint, the same
    convention `llm_factory.api_key_for` expects.
    """
    if not (user.api_key_encrypted and user.api_key_provider):
        return {}
    plaintext = decrypt(user.api_key_encrypted)
    if not plaintext:
        return {}
    keys = {user.api_key_provider: plaintext}
    if user.api_key_base_url:
        keys[f"{user.api_key_provider}_base_url"] = user.api_key_base_url
    return keys


def hint(plaintext: str) -> str:
    """A safe, non-reversible display hint for a secret — the last 4 chars only."""
    tail = plaintext.strip()[-4:]
    return f"…{tail}" if tail else "…"
