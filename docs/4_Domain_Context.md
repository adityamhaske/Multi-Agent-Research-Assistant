# 4. Domain Context & Business Value

> **Purpose**: Ensures every engineering decision is grounded in the business problem being solved, the users being served, and the domain-specific risks that must be mitigated. Read this before making any architectural trade-off.

---

## Table of Contents
1. [The Business Problem — What We Are Solving](#1-the-business-problem--what-we-are-solving)
2. [Market Opportunity](#2-market-opportunity)
3. [Target User Personas](#3-target-user-personas)
4. [User Journey Mapping](#4-user-journey-mapping)
5. [Critical Domain Risks & Mitigations](#5-critical-domain-risks--mitigations)
6. [Success Metrics & KPIs](#6-success-metrics--kpis)
7. [Competitive Landscape](#7-competitive-landscape)
8. [Key Terminology for Developers](#8-key-terminology-for-developers)
9. [Scope Boundaries (What This System Is NOT)](#9-scope-boundaries-what-this-system-is-not)

---

## 1. The Business Problem — What We Are Solving

### The Research Tax

Financial analysts, market researchers, strategic consultants, and product managers currently spend **60–80% of their working time** on low-value data-gathering tasks:

| Task | Time Spent | Value Created |
|---|---|---|
| Opening and reading 30–50 web tabs | 45 min | Low — raw data, not insight |
| Verifying and cross-referencing facts | 60 min | Medium — quality control |
| Compiling notes into a coherent document | 30 min | Low — formatting, not thinking |
| Fact-checking the compiled document | 20 min | High — but tedious |
| **Actual strategic analysis** | **25 min** | **Very High** |

**Total time: ~3 hours per research task. High-value work: ~25 minutes (14%).**

### The Inversion Goal

```
BEFORE:  [████████████░░░] 80% data work, 20% analysis
AFTER:   [░░░████████████] 20% review/approve, 80% analysis
```

This system eliminates the research tax by automating data gathering, verification, and synthesis while keeping the human expert in the loop for the decisions that matter.

### The Core Value Proposition

> **"Turn a 3-hour research task into a 5-minute review."**

The system autonomously:
1. Decomposes the research question into structured sub-tasks
2. Searches the web, reads sources, and extracts relevant facts
3. Self-critiques for hallucinations and missing data
4. Synthesizes a structured Markdown brief with citations
5. Pauses for human review before finalization

The human expert only performs high-value work: reviewing the synthesized output, adding strategic context, and approving the final document.

---

## 2. Market Opportunity

### Serviceable Market

The system addresses anyone who does recurring structured research for professional output:

| Segment | Size (US) | Research Frequency | Willingness to Pay |
|---|---|---|---|
| Financial Analysts | 300,000 | Daily | High ($50-200/mo) |
| Strategy Consultants | 150,000 | 3x/week | High ($100-300/mo) |
| Product Managers | 2,000,000 | Weekly | Medium ($20-50/mo) |
| Academic Researchers | 500,000 | Weekly | Low ($10-20/mo) |
| Journalists | 200,000 | Daily | Medium ($20-50/mo) |

### Why Now

Three recent technology shifts make this product viable for the first time:
1. **LLM accuracy** (2024+): GPT-4o and Claude 3.5 Sonnet are good enough to produce citation-quality summaries without major hallucinations.
2. **Tool calling**: LLMs can now reliably invoke structured Python tools, enabling true multi-step automation.
3. **LangGraph**: Mature graph-based orchestration with first-class support for HITL interrupts and persistent checkpointing.

---

## 3. Target User Personas

### Persona 1: The Financial Analyst (Primary Power User)

```
Name:       Alex Chen
Role:       Buy-side Equity Research Analyst, 4 years experience
Firm:       Mid-sized hedge fund ($500M AUM)
Goal:       Produce a 10-page investment brief on a healthcare AI company
Time:       Has 4 hours before the investment committee meeting

Pain points:
  - Manually reading 40+ SEC filings, news articles, and analyst reports
  - Fear of missing a critical data point that would change the thesis
  - Having to re-do research when new data comes out

Quality bar:
  - Zero hallucinations (a wrong fact can cost the fund millions)
  - Every claim needs a citation with source URL and date
  - Output must be structured: executive summary, market analysis, risks, valuation

Acceptable latency: Will wait 5 minutes for a perfect 15-page brief
Preferred export: PDF with clickable citations
```

### Persona 2: The Product Manager (Secondary User)

```
Name:       Sarah Johnson
Role:       Senior PM at B2B SaaS company
Team:       3 reports, ships quarterly product roadmap
Goal:       Understand competitive moves in the AI writing assistant market

Pain points:
  - Has 30 browser tabs open at all times
  - Needs structured output (bullet points, not walls of text)
  - Reports need to be shareable with executives who don't like ambiguity

Quality bar:
  - Structured output over dense prose
  - Key takeaways up front (executive summary is critical)
  - Recent data only (last 3 months)

Acceptable latency: 2 minutes max; wants quick wins
Preferred export: DOCX to paste into the internal wiki
```

### Persona 3: The Academic Researcher (Tertiary User)

```
Name:       Dr. Priya Patel
Role:       Postdoctoral researcher, bioinformatics
Institution: University research lab
Goal:       Literature review on CRISPR delivery mechanisms for a grant application

Pain points:
  - PubMed and Google Scholar searches return 500 results — needs curation
  - Needs to check that cited papers actually support the claims

Quality bar:
  - Academic paper citations (DOI format)
  - Conservative tone — hedging language required ("suggests", "indicates")

Acceptable latency: 10 minutes for a thorough review
Note: This persona requires adding academic search tools (future milestone)
```

---

## 4. User Journey Mapping

### Happy Path (Financial Analyst)

```
1. NEED        Alex identifies: "I need to research NovaBiotech's market position"
               ↓
2. INPUT       Opens dashboard → types 150-word research query → selects "Comprehensive"
               ↓
3. LAUNCH      Clicks "Start Research" → sees "Research started, est. 3-4 min"
               ↓
4. MONITOR     Watches Brain Monitor: Planner creates 4 tasks
               Executor searches: PubMed, TechCrunch, SEC EDGAR
               Critic rejects Task 2 (missing revenue data) → Executor retries
               Critic passes all 4 tasks → Synthesizer compiles draft
               ↓
5. REVIEW      HITL Gate fires → Split-screen: Draft | Approval Panel
               Alex reads 8-page draft, sees 14 sources, 0 unverified claims
               Notices: "Missing European market data"
               Clicks "Reject & Rework" → types "Add EMEA healthcare AI market data"
               ↓
6. REWORK      Agent loops back → Executor searches EMEA data → Draft re-synthesized
               HITL Gate fires again → Alex reviews updated draft
               Satisfied → Clicks "Approve & Finalize"
               ↓
7. OUTPUT      Final PDF generated with clickable citations
               Analytics bar: "3m 47s | 16 sources | $0.11 | 1 rework"
               Alex spent: 5 minutes reviewing, saved ~2.5 hours of research
```

---

## 5. Critical Domain Risks & Mitigations

These are the highest-stakes failure modes. Every engineering decision must be weighed against these risks.

### Risk 1: Hallucination — The Most Dangerous Failure

**What it is**: The LLM fabricates a statistic, company name, funding round, or citation that sounds plausible but is false.

**Why it's catastrophic**: Alex's hedge fund acts on the research brief. A hallucinated revenue figure leads to a bad investment decision worth millions.

**Mitigations (all required, defense-in-depth)**:

| Layer | Mitigation | Implementation |
|---|---|---|
| **Executor** | Only report facts with a source URL | Prompt: "For every fact, include the source URL. If you cannot find a URL, do not include the fact." |
| **Critic** | Verify each fact has a supporting citation | Prompt: "For each claim in the context, is there an explicit source URL? If any claim lacks a citation, set `passed=false`." |
| **Synthesizer** | Inline citations in output | Every claim in the final draft is formatted as `[Source](url)` |
| **HITL Gate** | Human reviews before finalization | Non-negotiable. The user must see and approve the draft. |
| **UI** | Display confidence signals | Show "0 unsupported claims" or "3 claims without sources" in the HITL panel |

### Risk 2: Runaway Costs — Financial Exposure

**What it is**: An agent loop spirals due to a bad prompt, burning thousands of API tokens per session.

**Why it's dangerous**: At scale (1,000 sessions), a single broken prompt template could cost hundreds of dollars per hour.

**Mitigations**:
- Hard `critic_loop_count` cap of 3 per task (not just the LangGraph recursion_limit)
- Per-session budget cap of $0.50 USD (configurable)
- Real-time cost monitoring dashboard alert at $100/day
- Celery task hard timeout of 11 minutes (SIGKILL)

### Risk 3: Context Window Overflow

**What it is**: The Executor retrieves 50 web pages, each 10,000 tokens. The total context exceeds the LLM's limit (128K tokens for Claude 3.5 Sonnet).

**Why it matters**: The LLM silently truncates context, potentially dropping crucial data. The Synthesizer produces a brief based on incomplete information.

**Mitigations**:
- Executor summarizes each retrieved document to a max of 500 tokens before appending to state
- Critic is given both the full task AND a token budget to enforce
- State tracks `total_tokens_input`; if approaching 80K, executor stops retrieving new sources

### Risk 4: Stale or Outdated Information

**What it is**: The web search tool returns news articles from 2022 when the user asked about "Q4 2024 AI trends."

**Mitigations**:
- Tavily / DuckDuckGo search configured with `date_range="past_year"` by default
- Executor prompt explicitly states: "Only include sources dated within the last 12 months. Discard any source older than the user's query context implies."
- Each `ContextChunk` stores `retrieved_at` timestamp for auditability

---

## 6. Success Metrics & KPIs

### Product Metrics (Measure Weekly)

| Metric | Target (Month 1) | Target (Month 6) |
|---|---|---|
| Average research task duration | < 5 minutes | < 3 minutes |
| User approval rate on first draft | > 60% | > 80% |
| Hallucination report rate | < 2% of sessions | < 0.5% |
| Average cost per session | < $0.15 | < $0.10 |
| Sessions completed successfully | > 90% | > 98% |
| User rework rate | < 40% | < 20% |

### Engineering Reliability Metrics

| Metric | Target |
|---|---|
| API uptime | > 99.5% |
| Agent pipeline p99 latency | < 10 minutes |
| Concurrent sessions supported | 1,000+ |
| Cost per session (compute+LLM) | < $0.20 |
| Mean time to recover (MTTR) on failure | < 5 minutes |

---

## 7. Competitive Landscape

| Competitor | Strengths | Weaknesses vs. This System |
|---|---|---|
| **Perplexity Pro** | Great search, fast | No multi-step agent loop; no HITL; no structured output |
| **ChatGPT + Canvas** | Familiar UX, GPT-4o | No persistent state; no self-critique loop; manual research |
| **Elicit** | Academic focus | Limited to academic papers; no web search; no HITL |
| **Grok (xAI)** | Real-time X data | No structured research pipeline; no cost tracking |
| **This System** | Full pipeline, HITL, cost tracking, multi-source | Currently in development |

**Sustainable Differentiators**:
1. **Self-correcting Critic loop** — no competitor has automated quality assurance
2. **Human-in-the-Loop gate** — legally and professionally safer for high-stakes decisions
3. **Full cost transparency** — users see exactly what they spent per research task
4. **Export flexibility** — PDF, DOCX, and Markdown outputs

---

## 8. Key Terminology for Developers

| Term | Definition | System Implication |
|---|---|---|
| **Hallucination** | LLM generates a plausible but factually incorrect statement | Mitigated by Critic agent + citation requirement; monitored via user feedback |
| **Context Window** | The maximum token limit an LLM can process in one call | Executor must chunk and summarize; tracked in `AgentState.total_tokens_input` |
| **HITL (Human-in-the-Loop)** | An architectural pattern that pauses automation for human review | Implemented via LangGraph `interrupt_before` hook; surfaces in the UI as the Approval Gate |
| **Tool Calling / Function Calling** | LLM outputs structured JSON that triggers a Python function | Implemented via LangChain's `@tool` decorator; tools have narrow, single-responsibility scopes |
| **Recursion Limit** | The maximum number of times the Executor-Critic loop is allowed to run | Hard-coded to 3 in `AgentState.critic_loop_count`; enforced in `route_after_critic()` |
| **Checkpointer** | Persistent storage of the LangGraph state at each node | Allows HITL gate to pause and resume; stored in Redis; backed up to Postgres |
| **RAG (Retrieval-Augmented Generation)** | Grounding LLM responses in retrieved external data rather than training data | The Executor + Tavily search is the RAG pipeline; prevents hallucination of "known facts" |
| **Agentic Loop** | The autonomous cycle of Plan → Execute → Critique → Revise | The core value of the system; bounded by circuit breakers to prevent runaway costs |
| **Session** | One complete research lifecycle: query → plan → execute → review → finalize | Tracked in Postgres `sessions` table; identified by UUID |
| **Parallelizable Tasks** | Sub-tasks that don't depend on each other's output and can run concurrently | Identified by Planner; future optimization to run multiple Executors in parallel |

---

## 9. Scope Boundaries (What This System Is NOT)

These are explicitly out of scope to prevent scope creep and maintain focus:

| Out of Scope | Reason |
|---|---|
| **Real-time data feeds** (stock prices, live news) | Requires data licensing; different architecture (streaming ingestion vs. pull-based search) |
| **Internal document indexing** (PDFs, Notion, Confluence) | Requires vector database (Pinecone/Weaviate), RAG pipeline, and permission management — Milestone 5+ |
| **Report scheduling / recurring research** | Requires cron-job infrastructure and notification system — future feature |
| **Multi-user collaboration on a session** | Requires operational transformation or CRDTs — future feature |
| **Mobile app** | Responsive web is sufficient for MVP; native app is a future investment |
| **Autonomous financial advice** | Legal liability; this system synthesizes research, it does NOT make investment recommendations |
