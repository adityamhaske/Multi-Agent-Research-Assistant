"""
Model catalog (docs/13 §6, docs/12 M8).

Replaces the flat `PRICE_TABLE` + `_ANTHROPIC_NO_SAMPLING` tuple that used to live in
`llm_factory`. One entry per model, carrying everything three different consumers need:

- **cost accounting** — price per 1M input/output tokens,
- **request construction** — whether the model accepts sampling parameters, whether it
  supports tool calling and structured output,
- **the UI** — display name and context window for the per-role model picker.

Adding a model should be a catalog entry and nothing else. That is the test: if enabling a
model requires editing `llm_factory`, this file is missing a field.

## Prices are never estimated

`input_per_mtok` / `output_per_mtok` of `None` means "this deployment must supply the
price", not "free". `llm_factory.validate_pricing()` refuses to boot on a routed model with
no price, which is deliberate: a wrong price silently corrupts the budget guard, and the
budget guard is what stops a runaway session from draining a user's key.

Anthropic figures below are first-party list prices, verified against the Anthropic API
reference. Google figures carry over from the previous price table. OpenAI and OpenRouter
are intentionally unpriced — fill them from the provider's own pricing page for your
deployment. Ollama is genuinely zero: inference runs on the user's own hardware.
"""

from __future__ import annotations

from dataclasses import dataclass

# Agent roles, re-exported for convenience alongside the presets below.
from research_engine.runconfig import ROLES  # noqa: F401


@dataclass(frozen=True)
class ModelSpec:
    """One routable model."""

    provider: str
    model_id: str
    display_name: str

    # Pricing, $ per 1M tokens. None = this deployment must supply it (see module docstring).
    input_per_mtok: float | None
    output_per_mtok: float | None

    # None where the provider's published limit could not be verified — the UI shows
    # "unknown" rather than a number nobody checked.
    context_window: int | None = None
    max_output_tokens: int | None = None

    supports_tools: bool = True
    supports_structured_output: bool = True

    # False when the provider rejects temperature/top_p/top_k. The factory omits them
    # rather than taking a 400.
    sampling_params_supported: bool = True

    notes: str = ""

    @property
    def route(self) -> str:
        """The "provider:model" string used in MODEL_* routing and RunConfig."""
        return f"{self.provider}:{self.model_id}"

    @property
    def priced(self) -> bool:
        return self.input_per_mtok is not None and self.output_per_mtok is not None


def _spec(*args, **kwargs) -> ModelSpec:
    return ModelSpec(*args, **kwargs)


# ── Anthropic ─────────────────────────────────────────────────────────────────────
#
# Sampling: Opus 4.7 and later, plus Sonnet 5 and Fable 5, reject temperature/top_p/top_k.
# Opus 4.6, Sonnet 4.6, and Haiku 4.5 still accept them. Sonnet 5 rejects only *non-default*
# values — treated the same here, since omitting the parameter is always valid and the
# alternative is encoding a per-parameter default table for no behavioural gain.
#
# `claude-opus-5` was missing from both the old price table and the old no-sampling tuple,
# so routing any role to it failed twice over: `validate_pricing()` refused to boot, and had
# it booted, every request would have sent a temperature and taken a 400 (docs/12 M8).

_ANTHROPIC = [
    _spec(
        "anthropic",
        "claude-opus-5",
        "Claude Opus 5",
        input_per_mtok=5.00,
        output_per_mtok=25.00,
        context_window=1_000_000,
        max_output_tokens=128_000,
        sampling_params_supported=False,
        notes="Thinking is on by default; raw reasoning is never returned.",
    ),
    _spec(
        "anthropic",
        "claude-opus-4-8",
        "Claude Opus 4.8",
        input_per_mtok=5.00,
        output_per_mtok=25.00,
        context_window=1_000_000,
        max_output_tokens=128_000,
        sampling_params_supported=False,
    ),
    _spec(
        "anthropic",
        "claude-opus-4-7",
        "Claude Opus 4.7",
        input_per_mtok=5.00,
        output_per_mtok=25.00,
        context_window=1_000_000,
        max_output_tokens=128_000,
        sampling_params_supported=False,
    ),
    _spec(
        "anthropic",
        "claude-opus-4-6",
        "Claude Opus 4.6",
        input_per_mtok=5.00,
        output_per_mtok=25.00,
        context_window=1_000_000,
        max_output_tokens=128_000,
        sampling_params_supported=True,
    ),
    _spec(
        "anthropic",
        "claude-sonnet-5",
        "Claude Sonnet 5",
        # Standard list price. An introductory $2/$10 runs through 2026-08-31; the higher
        # standard rate is kept deliberately so the budget guard never under-estimates.
        input_per_mtok=3.00,
        output_per_mtok=15.00,
        context_window=1_000_000,
        max_output_tokens=128_000,
        sampling_params_supported=False,
    ),
    _spec(
        "anthropic",
        "claude-sonnet-4-6",
        "Claude Sonnet 4.6",
        input_per_mtok=3.00,
        output_per_mtok=15.00,
        context_window=1_000_000,
        max_output_tokens=128_000,
        sampling_params_supported=True,
    ),
    _spec(
        "anthropic",
        "claude-haiku-4-5",
        "Claude Haiku 4.5",
        input_per_mtok=1.00,
        output_per_mtok=5.00,
        context_window=200_000,
        max_output_tokens=64_000,
        sampling_params_supported=True,
    ),
    _spec(
        "anthropic",
        "claude-fable-5",
        "Claude Fable 5",
        input_per_mtok=10.00,
        output_per_mtok=50.00,
        context_window=1_000_000,
        max_output_tokens=128_000,
        sampling_params_supported=False,
        notes="Highest-capability tier; thinking always on. Requires 30-day data retention.",
    ),
]

# ── Google ────────────────────────────────────────────────────────────────────────

_GOOGLE = [
    _spec(
        "google",
        "gemini-2.5-pro",
        "Gemini 2.5 Pro",
        input_per_mtok=1.25,
        output_per_mtok=5.00,
    ),
    _spec(
        "google",
        "gemini-2.5-flash",
        "Gemini 2.5 Flash",
        input_per_mtok=0.075,
        output_per_mtok=0.30,
    ),
    # Legacy, kept priced so an older MODEL_* config still boots.
    _spec(
        "google",
        "gemini-1.5-pro",
        "Gemini 1.5 Pro",
        input_per_mtok=1.25,
        output_per_mtok=5.00,
    ),
    _spec(
        "google",
        "gemini-1.5-flash",
        "Gemini 1.5 Flash",
        input_per_mtok=0.075,
        output_per_mtok=0.30,
    ),
]

# ── Ollama (local) ────────────────────────────────────────────────────────────────
#
# Zero cost is a fact here, not a placeholder: the tokens are generated on the user's own
# machine. Structured-output support is weaker than a hosted model's, which the pipeline
# already tolerates — the critic fails closed and the executor has a no-tools wrap-up
# retry, so a model that fumbles JSON degrades the run instead of breaking it.

_OLLAMA = [
    _spec(
        "ollama",
        "llama3.3",
        "Llama 3.3 (local)",
        input_per_mtok=0.0,
        output_per_mtok=0.0,
        notes="Runs locally via Ollama. No API key, no network egress for inference.",
    ),
    _spec(
        "ollama",
        "qwen2.5",
        "Qwen 2.5 (local)",
        input_per_mtok=0.0,
        output_per_mtok=0.0,
        notes="Runs locally via Ollama.",
    ),
    _spec(
        "ollama",
        "mistral-nemo",
        "Mistral Nemo (local)",
        input_per_mtok=0.0,
        output_per_mtok=0.0,
        notes="Runs locally via Ollama.",
    ),
]

CATALOG: dict[str, ModelSpec] = {spec.model_id: spec for spec in (*_ANTHROPIC, *_GOOGLE, *_OLLAMA)}

# Providers the factory can build a client for. OpenAI and OpenRouter are routable but
# deliberately carry no catalog entries: their model lists change constantly and their
# prices are not ours to guess. Route to them explicitly and register the model with
# `register()` (below) so pricing is a conscious act.
KNOWN_PROVIDERS = ("anthropic", "google", "openai", "openrouter", "ollama")


def register(spec: ModelSpec) -> None:
    """Add or override a catalog entry at runtime.

    The escape hatch for a model this file doesn't ship — a new release, a fine-tune, or
    an OpenRouter/OpenAI route whose price the operator knows and we don't.
    """
    CATALOG[spec.model_id] = spec


def get(model_id: str) -> ModelSpec | None:
    return CATALOG.get(model_id)


def by_provider(provider: str) -> list[ModelSpec]:
    return [s for s in CATALOG.values() if s.provider == provider]


def providers() -> list[str]:
    return sorted({s.provider for s in CATALOG.values()})


# ── Presets ───────────────────────────────────────────────────────────────────────
#
# Role specialization is a *quality* argument, not just a flexibility toggle: the executor
# runs many tool-calling rounds and wants breadth and speed, while the synthesizer writes
# the artifact the user reads and wants the strongest model. Presets encode that, so the
# common case is one click and the per-role drawer stays for people who want it.

PRESETS: dict[str, dict[str, dict[str, str]]] = {
    "anthropic": {
        "fast": {r: "anthropic:claude-haiku-4-5" for r in ROLES},
        "balanced": {
            "planner": "anthropic:claude-sonnet-5",
            "executor": "anthropic:claude-haiku-4-5",
            "critic": "anthropic:claude-haiku-4-5",
            "synthesizer": "anthropic:claude-sonnet-5",
            "chat": "anthropic:claude-haiku-4-5",
        },
        "best": {
            "planner": "anthropic:claude-opus-5",
            "executor": "anthropic:claude-sonnet-5",
            "critic": "anthropic:claude-sonnet-5",
            "synthesizer": "anthropic:claude-opus-5",
            "chat": "anthropic:claude-sonnet-5",
        },
    },
    "google": {
        "fast": {r: "google:gemini-2.5-flash" for r in ROLES},
        "balanced": {
            "planner": "google:gemini-2.5-pro",
            "executor": "google:gemini-2.5-flash",
            "critic": "google:gemini-2.5-flash",
            "synthesizer": "google:gemini-2.5-pro",
            "chat": "google:gemini-2.5-flash",
        },
        "best": {r: "google:gemini-2.5-pro" for r in ROLES},
    },
    "ollama": {
        # One local model for every role — a laptop runs one at a time anyway, and
        # swapping models mid-run would just thrash the weights cache.
        "fast": {r: "ollama:qwen2.5" for r in ROLES},
        "balanced": {r: "ollama:llama3.3" for r in ROLES},
        "best": {r: "ollama:llama3.3" for r in ROLES},
    },
}

PRESET_NAMES = ("fast", "balanced", "best")


def preset(provider: str, name: str) -> dict[str, str] | None:
    """Role → route mapping for a named preset, or None if the pair is unknown."""
    return (PRESETS.get(provider) or {}).get(name)
