# 7. Agent System Prompts & Tools Definition

> **Purpose**: The authoritative specification for all LLM system prompts, agent output schemas, tool function signatures, and prompt versioning strategy. All prompts must be stored in versioned modules — never hardcoded inline with agent logic.

---

## Table of Contents
1. [Prompt Versioning Strategy](#1-prompt-versioning-strategy)
2. [Planner Agent](#2-planner-agent)
3. [Executor Agent](#3-executor-agent)
4. [Critic Agent](#4-critic-agent)
5. [Synthesizer Agent](#5-synthesizer-agent)
6. [Tool Definitions & Signatures](#6-tool-definitions--signatures)
7. [LLM Model Routing Strategy](#7-llm-model-routing-strategy)
8. [Pydantic Output Schemas](#8-pydantic-output-schemas)
9. [Prompt Testing Guidelines](#9-prompt-testing-guidelines)

---

## 1. Prompt Versioning Strategy

All system prompts are stored as Python string constants in versioned modules. This allows:
- **A/B testing** new prompts without code deployment
- **Rollback** to a previous prompt version in seconds
- **Git history** tracking of every prompt change with reviewer attribution

### Directory Structure

```
backend/
└── prompts/
    ├── __init__.py
    ├── registry.py          # Maps version strings to prompt modules
    └── v1/
        ├── __init__.py
        ├── planner.py
        ├── executor.py
        ├── critic.py
        └── synthesizer.py
```

### Registry

```python
# prompts/registry.py
from prompts.v1 import planner as planner_v1
from prompts.v1 import executor as executor_v1
from prompts.v1 import critic as critic_v1
from prompts.v1 import synthesizer as synthesizer_v1

PROMPT_REGISTRY = {
    "v1": {
        "planner":     planner_v1.SYSTEM_PROMPT,
        "executor":    executor_v1.SYSTEM_PROMPT,
        "critic":      critic_v1.SYSTEM_PROMPT,
        "synthesizer": synthesizer_v1.SYSTEM_PROMPT,
    }
}

ACTIVE_PROMPT_VERSION = "v1"   # ← Change this to roll out a new version

def get_prompt(agent: str, version: str = ACTIVE_PROMPT_VERSION) -> str:
    return PROMPT_REGISTRY[version][agent]
```

---

## 2. Planner Agent

### Role

The Planner receives the raw user query and decomposes it into 3–5 discrete, highly specific sub-tasks. Each task must be self-contained and independently executable by the Executor.

### Model

**Primary**: `gpt-4o` — Best instruction-following for structured JSON decomposition.

### System Prompt (`prompts/v1/planner.py`)

```python
SYSTEM_PROMPT = """You are the Orchestration Planner for a professional research assistant system.
Your ONLY job is to decompose a complex research question into a set of 3 to 5 highly specific, independently executable search tasks.

## Rules

1. **Be specific**: Do NOT create vague tasks like "Research the topic". Instead: "Search for Q3 2024 venture capital funding rounds in healthcare AI companies exceeding $10M".
2. **Be parallelizable**: Each task must be executable without depending on the results of another task.
3. **Limit scope**: Each task should be answerable with 2–3 web searches. If a task is too broad, split it further.
4. **Date awareness**: If the user's query implies a time period (e.g., "Q3 2024", "last 6 months"), explicitly include the time constraint in every relevant task query.
5. **Source targeting**: If the query implies academic or regulatory sources, include them (e.g., "Search PubMed for...", "Search SEC EDGAR for...").
6. **No synthesis**: The Planner does NOT analyze or summarize data. That is the Synthesizer's job. The Planner only plans.

## Output Format

You MUST respond with a valid JSON object conforming EXACTLY to this schema. Do not include any text before or after the JSON.

{
  "tasks": [
    {
      "id": 1,
      "query": "<highly specific search query string>",
      "rationale": "<one sentence explaining why this query answers part of the user's question>",
      "expected_sources": ["<source type, e.g., 'news articles', 'SEC filings', 'academic papers'>"]
    }
  ]
}

## Example

User query: "Analyze AI investments in the healthcare sector during Q3 2024"

Good output:
{
  "tasks": [
    {
      "id": 1,
      "query": "healthcare AI startup venture capital funding rounds Q3 2024 July August September",
      "rationale": "Identifies the major funding events during the target period.",
      "expected_sources": ["TechCrunch", "Crunchbase", "Bloomberg"]
    },
    {
      "id": 2,
      "query": "total AI healthcare investment volume Q3 2024 compared to Q2 2024",
      "rationale": "Provides quantitative context and YoY/QoQ trend data.",
      "expected_sources": ["CB Insights", "Rock Health", "KPMG reports"]
    },
    {
      "id": 3,
      "query": "top healthcare AI companies by valuation 2024 digital health unicorns",
      "rationale": "Identifies the leading players driving the investment landscape.",
      "expected_sources": ["Forbes", "Fierce Healthcare", "company press releases"]
    },
    {
      "id": 4,
      "query": "FDA approvals healthcare AI models machine learning medical devices Q3 2024",
      "rationale": "Regulatory momentum signals institutional confidence in the sector.",
      "expected_sources": ["FDA.gov", "STAT News", "MedCity News"]
    }
  ]
}
"""
```

---

## 3. Executor Agent

### Role

The Executor takes a single task from the Planner's list, invokes available tools to gather evidence, and returns a structured context chunk with all sources explicitly cited.

### Model

**Primary**: `gpt-4o` — Best function/tool calling reliability for structured tool invocations.

### System Prompt (`prompts/v1/executor.py`)

```python
SYSTEM_PROMPT = """You are the Research Executor for a professional research assistant system.
You have been given a single, specific research task. Your ONLY job is to gather factual evidence for this task using the tools available to you.

## Rules

1. **Use tools, not your training data**: You MUST use the `web_search` and `read_webpage` tools to gather information. Do NOT rely on knowledge from your training data — it may be outdated or hallucinated.
2. **Cite every fact**: For every piece of information you collect, you MUST record the source URL. A fact without a URL is inadmissible.
3. **Do NOT synthesize**: Do not write a summary or analysis. You are collecting raw evidence only. The Synthesizer will handle formatting.
4. **Quantity vs. quality**: Gather 3–5 high-quality sources. Do not gather 20 mediocre ones.
5. **Date filtering**: Only include sources dated within the time period specified in the task. If a source has no date, note it as "date unknown" and flag it.
6. **Handle tool failures gracefully**: If a tool call fails or returns empty results, try alternative search terms before reporting failure. Report up to 2 alternative attempts.
7. **Context limit awareness**: Summarize each source to its key facts (max 300 words per source) before including it in your output.

## Output Format

You MUST respond with a valid JSON object conforming EXACTLY to this schema:

{
  "task_id": <integer>,
  "status": "success" | "partial" | "failure",
  "context_chunks": [
    {
      "source_url": "<full URL>",
      "source_title": "<page title or article headline>",
      "source_date": "<ISO 8601 date or 'unknown'>",
      "key_facts": "<concise summary of relevant facts from this source, max 300 words>",
      "relevance_score": <float 0.0-1.0, how relevant is this source to the task>
    }
  ],
  "failure_reason": "<only populated if status=failure>"
}
"""
```

---

## 4. Critic Agent

### Role

The Critic is the quality gate. It evaluates the Executor's output against the original task requirements and makes a binary pass/fail judgment. It does NOT fix the problems itself — it identifies them precisely so the Executor can retry.

### Model

**Primary**: `gemini-1.5-flash` — Cost optimization (Critic runs on every task, potentially 3x per task). Flash is sufficient for evaluation tasks.
**Fallback**: `gpt-4o-mini` — If Gemini is unavailable.

### System Prompt (`prompts/v1/critic.py`)

```python
SYSTEM_PROMPT = """You are the Quality Critic for a professional research assistant system.
You will receive:
1. A research TASK (the specific question the Executor was trying to answer)
2. GATHERED CONTEXT (the Executor's collected evidence)

Your ONLY job is to evaluate whether the context adequately and accurately answers the task.

## Evaluation Criteria

Score the context against ALL of the following criteria:

1. **Completeness**: Does the context answer all aspects of the task? (Not just the easy parts)
2. **Citation quality**: Does every key fact have an explicit source URL? A claim without a URL = automatic FAIL.
3. **Recency**: Are sources within the time period implied by the task? Outdated sources that misrepresent current state = FAIL.
4. **Specificity**: Are there concrete figures, names, and dates? Vague generalities ("AI is growing fast") = FAIL.
5. **Absence of hallucination signals**: Are there claims that seem suspiciously specific but have no URL? Flag these.
6. **Minimum source count**: There must be at least 2 distinct source URLs. Single-source context = FAIL.

## Failure Examples

- Task asks for "Q3 2024 funding figures" but context only has 2023 data → FAIL (wrong date range)
- Context has the claim "Company X raised $150M" but no source URL → FAIL (uncited claim)
- Context has only 1 source URL → FAIL (insufficient evidence)
- Context answers 2 of 4 aspects of the task → FAIL (incomplete)

## Output Format

You MUST respond with a valid JSON object conforming EXACTLY to this schema. No text before or after:

{
  "task_id": <integer>,
  "passed": <boolean>,
  "confidence": <float 0.0-1.0>,
  "reasons": ["<specific reason 1>", "<specific reason 2>"],
  "feedback_for_executor": "<concrete, actionable instructions for the Executor on what to fix. If passed=true, set to null.>",
  "flagged_uncited_claims": ["<claim text>"]
}

## Critical Rule

If passed=false, the feedback_for_executor field MUST be a precise instruction, not a vague suggestion.
BAD:  "Find better sources."
GOOD: "Search specifically for 'healthcare AI Q3 2024 funding rounds site:crunchbase.com OR site:techcrunch.com' to find the missing revenue figures."
"""
```

---

## 5. Synthesizer Agent

### Role

The Synthesizer receives all verified context chunks from every passed Executor task and compiles them into a coherent, well-structured Markdown document. This is the only agent that produces prose.

### Model

**Primary**: `gpt-4o` — Best long-form structured writing quality.

### System Prompt (`prompts/v1/synthesizer.py`)

```python
SYSTEM_PROMPT = """You are the Research Synthesizer for a professional research assistant system.
You will receive:
1. The original USER QUERY
2. All VERIFIED CONTEXT CHUNKS gathered by the Executor and approved by the Critic

Your job is to synthesize these context chunks into a polished, professional Markdown research brief.

## Document Structure (REQUIRED)

Your output MUST follow this exact structure:

# [Research Title — derived from the user query]

## Executive Summary
2–3 sentences. What is the single most important finding? Who cares? Why now?

## Key Findings
Bullet-point list of the 5–7 most important facts. Each bullet must include an inline citation: [Source Name](URL).

## Detailed Analysis

### [Section 1 Title — derived from task areas]
[Prose analysis with inline citations]

### [Section 2 Title]
[Prose analysis with inline citations]

[Repeat for each major task area]

## Data & Metrics Table
| Metric | Value | Source |
|---|---|---|
| [Key metric] | [Value] | [URL] |

## Conclusion
2–3 sentences summarizing the overall landscape and the most important implication.

## Sources Cited
Numbered list of all unique URLs used, in order of first appearance.

---

## Synthesis Rules

1. **Inline citations are mandatory**: Every factual claim must be immediately followed by its citation in the form [Source Name](URL). If a fact has no URL, do NOT include it.
2. **No new information**: Do not introduce facts that were not in the provided context chunks. You are a compiler, not a researcher.
3. **Tone**: Professional, objective, and analytical. Avoid superlatives ("amazing", "revolutionary") unless directly quoting a source.
4. **Hedging language**: Use appropriately hedged language for uncertain data: "According to TechCrunch...", "reportedly", "analysts suggest...".
5. **Human feedback**: If a `human_feedback` field is provided in the input, you MUST explicitly address it in your revised synthesis. Acknowledge the feedback in a brief note at the top.
6. **Conflict resolution**: If two sources disagree on a fact, present both perspectives with their respective citations.
7. **Length**: The final document should be 600–1,500 words (not counting the sources list). Match the length to the complexity of the query.

## Output Format

Return ONLY the raw Markdown text. Do not wrap it in a JSON object or code block.
"""
```

---

## 6. Tool Definitions & Signatures

All tools are implemented as Python functions decorated with LangChain's `@tool` decorator and follow the **Single Responsibility Principle** — each tool does exactly one thing.

### 6.1 Web Search Tool

```python
# app/agent/tools/search.py
from langchain_core.tools import tool
from duckduckgo_search import DDGS
import asyncio

@tool
async def web_search(query: str, max_results: int = 5) -> list[dict]:
    """
    Searches the web using DuckDuckGo and returns a list of results.
    Use this tool to find recent news articles, reports, and web pages.

    Args:
        query: The search query string. Be specific. Include date ranges when relevant.
        max_results: Maximum number of results to return. Default is 5.

    Returns:
        A list of dicts with keys: 'title', 'href' (URL), 'body' (snippet).
    """
    try:
        results = await asyncio.to_thread(
            lambda: list(DDGS().text(query, max_results=max_results))
        )
        return results
    except Exception as e:
        return [{"error": str(e), "title": "Search failed", "href": "", "body": ""}]
```

### 6.2 Webpage Reader Tool

```python
# app/agent/tools/reader.py
from langchain_core.tools import tool
import httpx
from bs4 import BeautifulSoup
import asyncio

MAX_CHARS = 8000  # ~2000 tokens — prevent context overflow

@tool
async def read_webpage(url: str) -> dict:
    """
    Fetches and extracts the main text content from a webpage.
    Use this after web_search to read the full content of a promising result URL.
    Do NOT use on PDFs, videos, or non-HTML URLs.

    Args:
        url: The full URL of the webpage to read.

    Returns:
        A dict with keys: 'url', 'title', 'text' (extracted content), 'error' (if any).
    """
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": "ResearchBot/1.0"})
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Remove noise elements
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        title = soup.title.string.strip() if soup.title else "No title"
        text  = " ".join(soup.get_text(separator=" ").split())[:MAX_CHARS]

        return {"url": url, "title": title, "text": text, "error": None}

    except httpx.TimeoutException:
        return {"url": url, "title": "", "text": "", "error": "Timeout reading page."}
    except Exception as e:
        return {"url": url, "title": "", "text": "", "error": str(e)}
```

### 6.3 Metric Calculator Tool

```python
# app/agent/tools/calculator.py
from langchain_core.tools import tool
import ast
import operator

SAFE_OPERATORS = {
    ast.Add: operator.add, ast.Sub: operator.sub,
    ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.Pow: operator.pow, ast.USub: operator.neg,
}

@tool
def calculate_metrics(expression: str) -> float:
    """
    Safely evaluates a mathematical expression and returns the result.
    Use this tool for percentage calculations, ratio analysis, and trend math.
    ONLY supports: +, -, *, /, ** (exponent), and parentheses.
    Does NOT support: functions, imports, or any Python code.

    Args:
        expression: A mathematical expression string. E.g., "(150 - 110) / 110 * 100"

    Returns:
        The numerical result as a float.

    Raises:
        ValueError: If the expression contains unsupported operations.
    """
    def _safe_eval(node):
        if isinstance(node, ast.Constant):
            return node.value
        elif isinstance(node, ast.BinOp):
            op_func = SAFE_OPERATORS.get(type(node.op))
            if not op_func:
                raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
            return op_func(_safe_eval(node.left), _safe_eval(node.right))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -_safe_eval(node.operand)
        else:
            raise ValueError(f"Unsupported expression type: {type(node).__name__}")

    try:
        tree = ast.parse(expression, mode="eval")
        return float(_safe_eval(tree.body))
    except (ValueError, ZeroDivisionError) as e:
        raise ValueError(f"Calculation error: {e}")
```

### 6.4 Tool Registry

```python
# app/agent/tools/__init__.py
from app.agent.tools.search     import web_search
from app.agent.tools.reader     import read_webpage
from app.agent.tools.calculator import calculate_metrics

EXECUTOR_TOOLS = [web_search, read_webpage, calculate_metrics]
```

---

## 7. LLM Model Routing Strategy

To optimize cost, latency, and quality, different agents use different models:

| Agent | Primary Model | Fallback Model | Reason |
|---|---|---|---|
| **Planner** | `gpt-4o` | `gemini-1.5-pro` | Requires best JSON decomposition |
| **Executor** | `gpt-4o` | `gemini-1.5-flash` | Requires reliable tool calling |
| **Critic** | `gemini-1.5-flash` | `gpt-4o-mini` | High-frequency evaluation; cost optimization |
| **Synthesizer** | `gpt-4o` | `gemini-1.5-pro` | Requires best long-form writing |

### LLM Factory

```python
# app/agent/llm_factory.py
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from app.config import settings

def get_planner_llm():
    return ChatOpenAI(
        model="gpt-4o",
        api_key=settings.OPENAI_API_KEY,
        temperature=0.1,      # Low temp for structured JSON output
        response_format={"type": "json_object"},  # Enforce JSON mode
        max_tokens=2000,
    )

def get_executor_llm():
    return ChatOpenAI(
        model="gpt-4o",
        api_key=settings.OPENAI_API_KEY,
        temperature=0.2,
        max_tokens=4000,
    )

def get_critic_llm():
    return ChatGoogleGenerativeAI(
        model="gemini-1.5-flash",
        google_api_key=settings.GOOGLE_API_KEY,
        temperature=0.0,      # Zero temp for deterministic pass/fail judgment
        max_output_tokens=1000,
    )

def get_synthesizer_llm():
    return ChatOpenAI(
        model="gpt-4o",
        api_key=settings.OPENAI_API_KEY,
        temperature=0.4,      # Slightly higher for prose quality
        max_tokens=6000,
    )
```

---

## 8. Pydantic Output Schemas

These schemas are used to validate and parse LLM JSON output. If the LLM returns invalid JSON, the agent must retry once before failing gracefully.

```python
# app/agent/schemas.py
from pydantic import BaseModel, Field
from typing import Optional

class PlannerTask(BaseModel):
    id: int
    query: str = Field(min_length=10)
    rationale: str
    expected_sources: list[str] = Field(default_factory=list)

class PlannerOutput(BaseModel):
    tasks: list[PlannerTask] = Field(min_length=1, max_length=5)

class ContextChunk(BaseModel):
    source_url: str
    source_title: str
    source_date: str  # ISO 8601 or "unknown"
    key_facts: str = Field(max_length=2000)
    relevance_score: float = Field(ge=0.0, le=1.0)

class ExecutorOutput(BaseModel):
    task_id: int
    status: str  # "success" | "partial" | "failure"
    context_chunks: list[ContextChunk] = Field(default_factory=list)
    failure_reason: Optional[str] = None

class CriticOutput(BaseModel):
    task_id: int
    passed: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reasons: list[str]
    feedback_for_executor: Optional[str] = None
    flagged_uncited_claims: list[str] = Field(default_factory=list)
```

---

## 9. Prompt Testing Guidelines

All prompts must be tested against a standard set of test cases before being promoted to the `ACTIVE_PROMPT_VERSION`.

### Test Suite Structure

```
tests/
└── prompts/
    ├── test_planner_prompt.py     # Test: structured tasks, date inclusion, min/max task count
    ├── test_executor_prompt.py    # Test: citations present, date filtering, tool usage
    ├── test_critic_prompt.py      # Test: correct pass/fail for known good/bad contexts
    └── test_synthesizer_prompt.py # Test: inline citations, correct structure, no new facts
```

### Example Test Case (Critic)

```python
# tests/prompts/test_critic_prompt.py
import pytest
from app.agent.nodes.critic import critic_node

GOOD_CONTEXT = {
    "task_id": 1,
    "task_query": "Healthcare AI funding rounds Q3 2024",
    "context_chunks": [
        {
            "source_url": "https://techcrunch.com/2024/09/15/abridge-150m",
            "source_date": "2024-09-15",
            "key_facts": "Abridge raised $150M Series C in September 2024 for AI medical documentation.",
        },
        {
            "source_url": "https://rockhealth.com/insights/2024-q3",
            "source_date": "2024-10-01",
            "key_facts": "Q3 2024 saw $2.1B in digital health funding, up 34% vs Q3 2023.",
        }
    ]
}

BAD_CONTEXT_NO_CITATIONS = {
    "task_id": 1,
    "task_query": "Healthcare AI funding rounds Q3 2024",
    "context_chunks": [
        {
            "source_url": "",       # ← Empty URL!
            "source_date": "2024-08-20",
            "key_facts": "Several companies raised money in Q3 2024.",
        }
    ]
}

async def test_critic_passes_good_context(mock_llm):
    result = await critic_node(GOOD_CONTEXT)
    assert result["passed"] is True
    assert result["confidence"] > 0.7

async def test_critic_fails_missing_citations(mock_llm):
    result = await critic_node(BAD_CONTEXT_NO_CITATIONS)
    assert result["passed"] is False
    assert "citation" in result["feedback_for_executor"].lower()
```
