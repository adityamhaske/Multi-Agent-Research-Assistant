"""
Run-scoped engine configuration (docs/13 §4, docs/12 M6 step 1).

The agent package must not read `app.config` or the process environment. It is being
extracted into a standalone `research_engine` package that has to run inside a desktop
app with no Postgres, no Redis, and no `.env` file — see
docs/architecture/13_Local_First_Architecture.md §2 for the measured coupling this removes.

Everything the graph, the model factory, the retrievers, and the tools used to read
from `settings` now arrives as a `RunConfig`.

Two levels of installation, mirroring the emitter indirection in `events.py`:

- `set_process_default(cfg)` — one baseline per process, installed by the host
  (`app.runtime.install_process_default` for the API/worker/eval processes; the
  desktop build will install one built from local config + OS keychain).
- `set_run_config(cfg)` — a `ContextVar` override scoped to one run, so concurrent
  runs in the same worker process can carry different model routing or budgets
  (needed by docs/12 M8's per-session model picker).

A `ContextVar` is used rather than threading config through `AgentState` because
tools are invoked by LangGraph without access to state, and `retrievers.search()`
is called from inside a tool — so state-threading cannot reach the retriever chain.
This matches the two existing precedents in this package (`events._emitter` and
`llm_factory._user_keys`).

`get_run_config()` resolves override → process default → module defaults. The module
defaults deliberately mirror `app/config.py`'s own field defaults exactly, so a host
that forgets to install one degrades to today's out-of-the-box behaviour rather than
to something subtly different. `tests/test_engine_boundary.py` pins that equivalence.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Literal

# Agent roles that resolve to a model. Keep in sync with `_ROLE_CONFIG` in llm_factory.
ROLES: tuple[str, ...] = ("planner", "executor", "critic", "synthesizer", "chat")

# Mirrors the MODEL_* defaults in app/config.py.
DEFAULT_MODELS: Mapping[str, str] = {
    "planner": "google:gemini-2.5-pro",
    "executor": "google:gemini-2.5-flash",
    "critic": "google:gemini-2.5-flash",
    "synthesizer": "google:gemini-2.5-pro",
    "chat": "google:gemini-2.5-flash",
}


@dataclass(frozen=True)
class RunConfig:
    """Immutable engine configuration for one process or one run.

    Field defaults mirror app/config.py. Provider keys here are the *deployment's*
    keys; a user's own BYOK key is overlaid per-run by `llm_factory.set_user_keys`
    and takes precedence (docs/06).
    """

    llm_mode: Literal["real", "fake"] = "real"
    # Selects the *content* the scripted models produce, not whether they are scripted:
    # a demo run is `llm_mode="fake", demo=True` (docs/17 §6.1). Deliberately not a third
    # `llm_mode` value — every `llm_mode == "fake"` comparison in the engine gates a
    # no-network guard, and a missed one would send a demo run to a real provider. As a
    # separate flag the worst case is a demo showing test filler, never a surprise call.
    demo: bool = False
    models: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_MODELS))
    provider_keys: Mapping[str, str] = field(default_factory=dict)

    # Retrievers
    tavily_api_key: str = ""
    brave_api_key: str = ""

    # Airgapped corpus mode (docs/12 M10): evidence comes ONLY from the installed
    # Corpus port. `retrievers.search` delegates to it exclusively and `read_webpage`
    # refuses every non-corpus URL — no network call of any kind. A run with this set
    # and no corpus installed fails closed rather than silently degrading to the web.
    corpus_mode: bool = False

    # SSRF guard (docs/06). Strict on server, relaxed on desktop (to allow local Ollama).
    enforce_ssrf_guards: bool = True

    # Where a local Ollama server listens (docs/13 §6). Overridable so the desktop build
    # can point at a remote box on the LAN instead of the machine it runs on.
    ollama_base_url: str = "http://localhost:11434/v1"

    # Budgets (docs/04 §6). **0 means unlimited** for all three, the same convention the
    # rate limits use. They default to unlimited: a run must not be killed mid-flight by a
    # ceiling the operator never chose, and the dollar cap cannot serve as a backstop
    # anyway — `estimate_cost()` returns 0.0 for openrouter/custom, so it never fires
    # there. Cap spend at the provider; set these when a deployment wants its own stop.
    max_critic_loops: int = 2
    max_cost_per_session_usd: float = 0.0
    max_wallclock_seconds: int = 0
    # Cumulative input tokens across the whole session, critic loops and rework included.
    # Was a hardcoded 1_000_000 inside `graph._over_budget` with no way to raise it, which
    # killed a real run at 1,003,721 tokens — the only live guard was the untunable one.
    max_input_tokens: int = 0

    # How many research tasks may run at once (docs/12 M7). 1 restores the old strictly
    # sequential behaviour, which also makes budget overshoot impossible — see
    # `graph._BudgetGuard` on why concurrency can only bound overshoot, not eliminate it.
    max_parallel_tasks: int = 4

    # ── Customization surface (docs/07 §2, Phase 3) ────────────────────────────
    # Every default below reproduces today's behaviour exactly — turning this field
    # into a setting must never change what an account that has not touched Settings
    # gets. Where a default mirrors a value hardcoded elsewhere, the source of that
    # value is named so the two cannot silently drift apart.

    # Was `web_search`'s hardcoded default (`research_engine/tools.py`).
    retrieval_k: int = 5
    # 0 = unlimited/no floor, matching this codebase's existing "0 = unlimited"
    # convention (docs/04 §6) — today the critic enforces no minimum at all.
    min_sources_per_task: int = 0
    # Was `EvidenceChunk.snippet`'s Pydantic `max_length` (`research_engine/schemas.py`)
    # — that ceiling still applies; this truncates *before* it, so it can only ever
    # tighten the cap, never loosen the schema's own limit.
    snippet_max_chars: int = 500

    # Phase 4 fields: declared and threaded through both config paths now, consumed
    # by the plan/outline gate this phase does not yet build. An empty default means
    # "no seed topics, no outline template" — exactly today's unconstrained planner.
    outline_template: str | None = None
    topic_seeds: tuple[str, ...] = ()
    # Role → replacement prompt text. No consumer yet in this phase; declared so the
    # config path exists ahead of whichever future phase reads it, rather than adding
    # a fourth place this contract has to be threaded through later.
    prompt_overrides: Mapping[str, str] = field(default_factory=dict)

    def model_for(self, role: str) -> str:
        """The "provider:model" string routed to a role."""
        try:
            return self.models[role]
        except KeyError:
            raise ValueError(
                f"No model routed for role '{role}'. Known roles: {sorted(self.models)}"
            ) from None


_MODULE_DEFAULT = RunConfig()

# Process baseline, replaced by the host at startup.
_process_default: RunConfig = _MODULE_DEFAULT

# Per-run override; None means "use the process default".
_override: ContextVar[RunConfig | None] = ContextVar("engine_run_config", default=None)


def set_process_default(cfg: RunConfig) -> None:
    """Install the process-wide baseline config. Called once by the host at startup."""
    global _process_default
    _process_default = cfg


def reset_process_default() -> None:
    """Restore module defaults. For tests that must assert un-hosted behaviour."""
    global _process_default
    _process_default = _MODULE_DEFAULT


def set_run_config(cfg: RunConfig):
    """Install a config for the current context. Returns a token for `reset_run_config`."""
    return _override.set(cfg)


def reset_run_config(token) -> None:
    _override.reset(token)


def get_run_config() -> RunConfig:
    """The active config: run override, else process default, else module defaults."""
    return _override.get() or _process_default
