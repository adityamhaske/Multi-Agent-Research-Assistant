"""
LLM factory: creates configured LLM instances for each agent role.

Using Google Gemini for all agents:
- gemini-1.5-pro  → Planner, Executor, Synthesizer (high quality, reasoning)
- gemini-1.5-flash → Critic (fast, cheap for frequent evaluation)

Both are free-tier friendly via Google AI Studio API key.
"""

from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import settings


def get_planner_llm() -> ChatGoogleGenerativeAI:
    """Gemini 1.5 Pro — best structured planning and JSON decomposition."""
    return ChatGoogleGenerativeAI(
        model="gemini-1.5-pro",
        google_api_key=settings.google_api_key,
        temperature=0.1,
        max_output_tokens=2000,
    )


def get_executor_llm() -> ChatGoogleGenerativeAI:
    """Gemini 1.5 Pro — reliable tool-calling and structured outputs."""
    return ChatGoogleGenerativeAI(
        model="gemini-1.5-pro",
        google_api_key=settings.google_api_key,
        temperature=0.2,
        max_output_tokens=4000,
    )


def get_critic_llm() -> ChatGoogleGenerativeAI:
    """Gemini 1.5 Flash — fast, cheap for high-frequency evaluation calls."""
    return ChatGoogleGenerativeAI(
        model="gemini-1.5-flash",
        google_api_key=settings.google_api_key,
        temperature=0.0,
        max_output_tokens=1000,
    )


def get_synthesizer_llm() -> ChatGoogleGenerativeAI:
    """Gemini 1.5 Pro — long-form, high-quality prose generation."""
    return ChatGoogleGenerativeAI(
        model="gemini-1.5-pro",
        google_api_key=settings.google_api_key,
        temperature=0.4,
        max_output_tokens=6000,
    )
