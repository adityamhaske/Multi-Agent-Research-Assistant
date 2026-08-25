"""
Provider credential health probe (docs/07 §2, Phase 2a: "Test API / custom / OpenRouter
connections on save — red/yellow/green").

Mirrors `local_llm.probe`'s contract exactly: never raises, always returns a Verdict a
user can act on. Amber ("degraded") is load-bearing — "the server answered but the key
was rejected" and "nothing answered at all" have completely different fixes (wrong key
vs. no network / wrong URL / provider outage), and collapsing them into one red state is
what makes a status light useless.

Each provider's probe is its cheapest authenticated call: a model list where the
provider offers one (also doubles as `model_count` for the UI), a key-info endpoint
where it doesn't (OpenRouter — its `/models` is public and unauthenticated, so it would
return 200 for a garbage key). None of these spend a token.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import httpx
import structlog

from research_engine.llm_factory import map_local_host

logger = structlog.get_logger()

# A probe must never make the settings page feel slow to use.
_PROBE_TIMEOUT_SECONDS = 6.0

VerdictState = Literal["ok", "degraded", "failed"]


@dataclass
class Verdict:
    state: VerdictState
    reason: str
    checked_at: str  # ISO-8601, so the UI can say "checked N minutes ago"
    model_count: int | None = None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _ok(reason: str, model_count: int | None = None) -> Verdict:
    return Verdict(state="ok", reason=reason, checked_at=_now_iso(), model_count=model_count)


def _degraded(reason: str) -> Verdict:
    return Verdict(state="degraded", reason=reason, checked_at=_now_iso())


def _failed(reason: str) -> Verdict:
    return Verdict(state="failed", reason=reason, checked_at=_now_iso())


def failed_verdict(reason: str) -> Verdict:
    """Public constructor for a `failed` Verdict raised by a caller, not this probe —
    e.g. a stored key that fails to decrypt before any network call is even attempted.
    Keeps every caller building the same shape rather than reaching into `_now_iso`.
    """
    return _failed(reason)


@dataclass
class _ProbeRequest:
    url: str
    headers: dict[str, str]
    # Extracts a model count from a 200 body, when this provider's endpoint carries one.
    count_of: Callable[[dict], int] | None = None


def _google_request(key: str) -> _ProbeRequest:
    # The Generative Language API authenticates via a query parameter, not a header.
    return _ProbeRequest(
        url=f"https://generativelanguage.googleapis.com/v1beta/models?key={key}",
        headers={},
        count_of=lambda body: len(body.get("models", [])),
    )


def _anthropic_request(key: str) -> _ProbeRequest:
    return _ProbeRequest(
        url="https://api.anthropic.com/v1/models",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
        count_of=lambda body: len(body.get("data", [])),
    )


def _openai_request(key: str) -> _ProbeRequest:
    return _ProbeRequest(
        url="https://api.openai.com/v1/models",
        headers={"Authorization": f"Bearer {key}"},
        count_of=lambda body: len(body.get("data", [])),
    )


def _openrouter_request(key: str) -> _ProbeRequest:
    # /models is OpenRouter's public catalog — no auth required, so it 200s for any
    # string. /auth/key describes the caller's own key and 401s when it is invalid,
    # which is the actual thing this probe needs to test.
    return _ProbeRequest(
        url="https://openrouter.ai/api/v1/auth/key",
        headers={"Authorization": f"Bearer {key}"},
        count_of=None,
    )


def _custom_request(key: str, base_url: str) -> _ProbeRequest:
    # Custom endpoints are OpenAI-wire-protocol-compatible (research_engine.llm_factory
    # treats them the same way), so /models is the OpenAI-shaped convention to try.
    dial = map_local_host(base_url)
    return _ProbeRequest(
        url=f"{dial.rstrip('/')}/models",
        headers={"Authorization": f"Bearer {key}"},
        count_of=lambda body: len(body.get("data", [])),
    )


_BUILDERS: dict[str, Callable[[str, str | None], _ProbeRequest]] = {
    "google": lambda key, base_url: _google_request(key),
    "anthropic": lambda key, base_url: _anthropic_request(key),
    "openai": lambda key, base_url: _openai_request(key),
    "openrouter": lambda key, base_url: _openrouter_request(key),
    "custom": lambda key, base_url: _custom_request(key, base_url or ""),
}


async def probe(provider: str, key: str, base_url: str | None = None) -> Verdict:
    """Test whether `key` (and, for `custom`, `base_url`) actually authenticates
    against `provider`. Never raises — every failure mode becomes a Verdict a user can
    act on, mirroring `local_llm.probe`.
    """
    if not key:
        return _degraded("No key to test.")

    builder = _BUILDERS.get(provider)
    if builder is None:
        return _failed(f"Unknown provider '{provider}'.")
    if provider == "custom" and not base_url:
        return _degraded("A base URL is required to test a custom endpoint.")

    req = builder(key, base_url)

    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_SECONDS) as client:
            resp = await client.get(req.url, headers=req.headers)
    except Exception as exc:  # noqa: BLE001 — every transport failure means "no response"
        logger.info("provider_health_probe_failed", provider=provider, error=str(exc))
        return _failed(f"No response from {provider}: {exc}")

    if resp.status_code in (401, 403):
        return _degraded(f"{provider} answered, but rejected this key (HTTP {resp.status_code}).")
    if resp.status_code == 429:
        return _degraded(f"{provider} answered, but this key is rate-limited or out of quota.")
    if 500 <= resp.status_code < 600:
        return _degraded(
            f"{provider} answered with a server error (HTTP {resp.status_code}) — try again shortly."
        )
    if resp.status_code != 200:
        return _degraded(f"{provider} answered with HTTP {resp.status_code}.")

    if req.count_of is None:
        return _ok("Connected.")
    try:
        count = req.count_of(resp.json())
    except Exception:  # noqa: BLE001 — an unparseable body still means "connected"
        return _ok("Connected.")
    return _ok(f"Connected · {count} models", model_count=count)
