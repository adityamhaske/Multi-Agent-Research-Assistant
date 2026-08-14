"""
Host adapter: build the engine's RunConfig from server settings (docs/13 §4).

`research_engine` deliberately does not import `app.config` — this module is the seam.
Server-side processes (API, Celery worker, eval harness) install one process
default at startup; the desktop host (docs/12 M9) will supply its own builder
reading local JSON + the OS keychain, and `research_engine` will not know the difference.

Keep this module thin: it maps settings fields to RunConfig fields and nothing else.
"""

from __future__ import annotations

from app.config import Settings, settings
from research_engine.runconfig import RunConfig, set_process_default


def run_config_from_settings(s: Settings | None = None) -> RunConfig:
    """Map environment-derived settings onto the engine's config object."""
    s = s or settings
    return RunConfig(
        llm_mode=s.llm_mode,
        models={
            "planner": s.model_planner,
            "executor": s.model_executor,
            "critic": s.model_critic,
            "synthesizer": s.model_synthesizer,
            "chat": s.model_chat,
        },
        provider_keys={
            "google": s.google_api_key,
            "anthropic": s.anthropic_api_key,
            "openai": s.openai_api_key,
            "openrouter": s.openrouter_api_key,
            "custom": s.custom_api_key,
            "custom_base_url": s.custom_base_url,
        },
        tavily_api_key=s.tavily_api_key,
        brave_api_key=s.brave_api_key,
        enforce_ssrf_guards=s.is_production,
        ollama_base_url=s.ollama_base_url,
        max_critic_loops=s.max_critic_loops,
        max_cost_per_session_usd=s.max_cost_per_session_usd,
        max_wallclock_seconds=s.max_wallclock_seconds,
        max_parallel_tasks=s.max_parallel_tasks,
    )


def install_process_default(s: Settings | None = None) -> RunConfig:
    """Install the settings-derived config as this process's engine baseline."""
    cfg = run_config_from_settings(s)
    set_process_default(cfg)
    return cfg
