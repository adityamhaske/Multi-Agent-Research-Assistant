# 3. UI/UX Guidelines

> **Purpose**: Defines the complete React frontend architecture, component specifications, design system, interaction patterns, and accessibility standards. Every frontend decision must trace back to one of the three core principles below.

---

## Table of Contents
1. [Core Design Principles](#1-core-design-principles)
2. [Design System & Tokens](#2-design-system--tokens)
3. [Application Layout & Routing](#3-application-layout--routing)
4. [Component Specifications](#4-component-specifications)
   - [Input Dashboard](#41-input-dashboard)
   - [Live Brain Monitor (Execution View)](#42-live-brain-monitor-execution-view)
   - [HITL Approval Gate](#43-hitl-approval-gate)
   - [Export & Output View](#44-export--output-view)
5. [State Management Architecture](#5-state-management-architecture)
6. [Real-Time SSE Integration](#6-real-time-sse-integration)
7. [Accessibility Requirements](#7-accessibility-requirements)
8. [Error & Loading States](#8-error--loading-states)

---

## 1. Core Design Principles

### 1.1 Transparency — Never Leave the User in the Dark

The user must **always** know what the system is doing. A blank spinner is an unacceptable UX.

- **Requirement**: The "Live Brain Monitor" component must be visible and updating within 500ms of research starting.
- **Requirement**: Every agent state transition must emit a human-readable log line to the UI.
- **Implementation**: Stream `AgentLog` events via SSE; parse and render them in real time.

### 1.2 Control — The Human Is Always in Charge

The system is an assistant, not an authority. The HITL gate is the highest-priority UI element.

- **Requirement**: The HITL Approval Gate must render within 200ms of the `HITL_READY` SSE event.
- **Requirement**: The user must be able to provide free-text feedback to the agent on rework.
- **Requirement**: Approval/rejection actions must be confirmed by a loading state + success toast.

### 1.3 Efficiency — Respect the User's Cognitive Load

- **Requirement**: Don't show all raw data. Summarize and highlight key facts.
- **Requirement**: Export should be one click, not buried in menus.
- **Requirement**: The cost display must always be visible in the output view.

---

## 2. Design System & Tokens

### 2.1 Color Palette (Dark Mode Primary)

```css
/* globals.css */
:root {
  /* Background layers */
  --color-bg-base:      #0f1117;   /* Page background */
  --color-bg-surface:   #1a1d27;   /* Card/panel backgrounds */
  --color-bg-elevated:  #252836;   /* Modals, dropdowns */
  --color-bg-hover:     #2e3248;   /* Interactive hover state */

  /* Brand / Accent */
  --color-accent-primary:   #6c63ff;  /* Primary CTAs, active indicators */
  --color-accent-secondary: #a78bfa;  /* Secondary highlights */
  --color-accent-glow:      rgba(108, 99, 255, 0.2);  /* Glow effects */

  /* Agent Status Colors */
  --color-agent-planner:    #38bdf8;  /* Sky blue — planning phase */
  --color-agent-executor:   #fb923c;  /* Orange — active execution */
  --color-agent-critic:     #f472b6;  /* Pink — critique phase */
  --color-agent-synthesizer:#4ade80;  /* Green — synthesis complete */
  --color-agent-hitl:       #facc15;  /* Yellow — awaiting human */

  /* Semantic */
  --color-success:   #22c55e;
  --color-warning:   #f59e0b;
  --color-error:     #ef4444;
  --color-info:      #3b82f6;

  /* Text */
  --color-text-primary:   #f1f5f9;
  --color-text-secondary: #94a3b8;
  --color-text-muted:     #475569;

  /* Borders */
  --color-border:         rgba(255,255,255,0.08);
  --color-border-accent:  rgba(108, 99, 255, 0.4);
}
```

### 2.2 Typography

```css
/* Use Google Fonts — Inter for body, JetBrains Mono for terminal logs */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
  --font-sans: 'Inter', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', 'Fira Code', monospace;

  --text-xs:   0.75rem;   /* 12px — metadata, badges */
  --text-sm:   0.875rem;  /* 14px — secondary labels */
  --text-base: 1rem;      /* 16px — body text */
  --text-lg:   1.125rem;  /* 18px — panel titles */
  --text-xl:   1.25rem;   /* 20px — section headers */
  --text-2xl:  1.5rem;    /* 24px — page titles */
}
```

### 2.3 Spacing & Radius

```css
:root {
  --radius-sm:  4px;
  --radius-md:  8px;
  --radius-lg:  12px;
  --radius-xl:  16px;
  --radius-full: 9999px;

  --space-1: 4px;   --space-2: 8px;   --space-3: 12px;
  --space-4: 16px;  --space-6: 24px;  --space-8: 32px;
}
```

---

## 3. Application Layout & Routing

### 3.1 Next.js Route Structure

```
app/
├── layout.tsx              # Root layout: ThemeProvider, ToastProvider
├── page.tsx                # Redirect → /dashboard
├── (auth)/
│   ├── login/page.tsx      # Login page
│   └── register/page.tsx   # Register page
├── dashboard/
│   ├── page.tsx            # Main Input Dashboard
│   └── layout.tsx          # Dashboard shell with sidebar
└── session/
    └── [sessionId]/
        ├── page.tsx        # Execution View + HITL Gate router
        └── loading.tsx     # Suspense skeleton
```

### 3.2 Page Routing Logic

```typescript
// app/session/[sessionId]/page.tsx
"use client";
import { useSessionStatus } from "@/hooks/useSessionStatus";
import { BrainMonitor } from "@/components/BrainMonitor";
import { HITLApprovalGate } from "@/components/HITLApprovalGate";
import { ExportView } from "@/components/ExportView";

export default function SessionPage({ params }: { params: { sessionId: string } }) {
  const { status, data } = useSessionStatus(params.sessionId);

  if (status === "RUNNING" || status === "PENDING") return <BrainMonitor sessionId={params.sessionId} />;
  if (status === "AWAITING_APPROVAL") return <HITLApprovalGate sessionId={params.sessionId} draft={data.draft} />;
  if (status === "COMPLETED") return <ExportView session={data} />;
  if (status === "FAILED") return <ErrorView error={data.error} />;

  return <BrainMonitor sessionId={params.sessionId} />;
}
```

---

## 4. Component Specifications

### 4.1 Input Dashboard

**Route**: `/dashboard`  
**Purpose**: Entry point for research requests.

#### Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  🔬 Research Assistant                     [History] [Profile]  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   What do you want to research?                                 │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ Analyze the competitive landscape of AI coding assistants  │ │
│  │ in Q4 2024 — focus on GitHub Copilot, Cursor, and Tabnine.│ │
│  │                                                            │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  Research Depth                Sources                          │
│  ○ Fast  ● Balanced  ○ Comprehensive   [🌐 Web] [📚 Academic]  │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │             🚀  Start Research                             │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  Recent Sessions                                                │
│  ├─ ✅ AI healthcare investments Q3 2024    2h ago  $0.14      │
│  ├─ 🔄 Fintech regulatory landscape 2025   5m ago  Running    │
│  └─ ❌ Quantum computing market size        1d ago  Failed     │
└─────────────────────────────────────────────────────────────────┘
```

#### Component Props & Behavior

```typescript
// components/InputDashboard/QueryForm.tsx
interface QueryFormState {
  query: string;          // Min 10, Max 2000 chars
  depth: "fast" | "balanced" | "comprehensive";
  sources: ("web" | "academic" | "internal")[];
}

// Validation rules:
// - Submit button disabled until query.length >= 10
// - Show character count (e.g., "47 / 2000")
// - Animate submit button on hover (scale + glow)
// - On submit: POST /api/v1/research/start → redirect to /session/[id]
```

#### Micro-animations

- **Textarea**: Border glow `rgba(108,99,255,0.5)` on focus with 200ms transition
- **Submit button**: Scale 1.02 on hover, brief loading spinner on click
- **Recent sessions**: Fade-in with 50ms stagger per row on page load

---

### 4.2 Live Brain Monitor (Execution View)

**Route**: `/session/[sessionId]` when `status ∈ {PENDING, RUNNING}`  
**Purpose**: Expose the full agent execution graph in real time.

#### Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│ 🔬 Researching: "Analyze AI investments in healthcare Q3 2024"       │
│ Session: a3f8b9c2-...  ● Running   Elapsed: 01:23   Cost: $0.03     │
├───────────────────────┬──────────────────────────────────────────────┤
│  RESEARCH PLAN        │  AGENT BRAIN — LIVE FEED                     │
│                       │                                              │
│  ✅ Task 1: Search    │  [17:04:01] 🧠 Planner created 4 tasks      │
│     Q3 AI reports     │  [17:04:03] 🕵️ Executor: searching web...   │
│                       │  [17:04:08] 🕵️ Found: techcrunch.com/...    │
│  🔄 Task 2: Extract   │  [17:04:09] 🕵️ Reading: techcrunch.com/...  │
│     funding rounds    │  [17:04:11] ⚖️ Critic: evaluating context   │
│                       │  [17:04:14] ⚖️ PASS — sufficient data found │
│  ⏳ Task 3: Analyze   │  [17:04:15] 🕵️ Executor: searching for...   │
│     competitor data   │  [17:04:20] ⚖️ FAIL — missing Q3 figures    │
│                       │  [17:04:20] 🔄 Retrying (loop 1/3)...       │
│  ⏳ Task 4: Synthesize│  [17:04:25] 🕵️ Executor: retry search...    │
│                       │  [17:04:31] ⚖️ PASS — Q3 data found         │
│                       │  [17:04:32] 📝 Synthesizer: compiling draft │
├───────────────────────┴──────────────────────────────────────────────┤
│  ████████████████████░░░░░░░░░░  60% complete                        │
└──────────────────────────────────────────────────────────────────────┘
```

#### Key Implementation Details

```typescript
// components/BrainMonitor/AgentLogFeed.tsx
interface AgentLog {
  timestamp: string;
  agent_name: "planner" | "executor" | "critic" | "synthesizer" | "system";
  action: string;
  result?: Record<string, unknown>;
}

// Rendering rules:
// 1. Auto-scroll to bottom on new log entry (smooth scroll)
// 2. Each agent name has a distinct color from the design system
// 3. Log entries fade in with a 100ms animation
// 4. Max 500 visible log lines (virtual scrolling for performance)
// 5. "Task passed" entries get a green checkmark pulse animation
// 6. "Retrying" entries get an orange background flash
```

#### Plan Panel State Mapping

| Task Status | Visual | Description |
|---|---|---|
| `pending` | ⏳ (gray) | Not yet started |
| `running` | 🔄 (spinning, orange) | Executor active |
| `passed` | ✅ (green, animated checkmark) | Critic approved |
| `failed_retrying` | 🔁 (yellow) | Critic rejected, retrying |
| `failed_final` | ❌ (red) | Max retries hit, proceeded with best data |

---

### 4.3 HITL Approval Gate

**Route**: `/session/[sessionId]` when `status === "AWAITING_APPROVAL"`  
**Purpose**: The most critical UI component. Human reviews the draft and decides.

#### Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  ⚠️  Research Complete — Your Review Required                       │
│  The AI has synthesized a draft. Please review before finalizing.   │
├────────────────────────────────┬────────────────────────────────────┤
│  DRAFT REPORT                  │  YOUR DECISION                     │
│  (Scrollable markdown viewer)  │                                    │
│                                │  Quality Signals                   │
│  ## AI Investments in          │  ✅ 12 sources cited               │
│  Healthcare Q3 2024            │  ✅ 0 unsupported claims detected  │
│                                │  ⚠️  3 low-confidence sections     │
│  ### Executive Summary         │                                    │
│  AI investment in healthcare   │  ─────────────────────────────     │
│  grew 34% YoY in Q3 2024...    │                                    │
│                                │  ┌──────────────────────────────┐  │
│  ### Key Funding Rounds        │  │   ✅  Approve & Finalize      │  │
│  - Abridge: $150M Series C     │  └──────────────────────────────┘  │
│  - Hippocratic AI: $53M        │                                    │
│  - Nabla: $24M Series C        │  ┌──────────────────────────────┐  │
│                                │  │   🔄  Reject & Rework        │  │
│  ### Market Trends             │  └──────────────────────────────┘  │
│  ...                           │                                    │
│                                │  Feedback for rework (optional):   │
│                                │  ┌──────────────────────────────┐  │
│                                │  │ e.g., "Add more data on      │  │
│                                │  │ European AI health startups" │  │
│                                │  └──────────────────────────────┘  │
└────────────────────────────────┴────────────────────────────────────┘
```

#### Approval Interaction Flow

```typescript
// components/HITLApprovalGate/ApprovalPanel.tsx
async function handleApprove() {
  setIsLoading(true);
  await fetch(`/api/v1/research/${sessionId}/approve`, {
    method: "POST",
    body: JSON.stringify({ approved: true, feedback: "" }),
  });
  // Redirect to export view
  router.push(`/session/${sessionId}`);
}

async function handleRework() {
  if (!feedback.trim()) {
    setFeedbackError("Please provide feedback so the agent knows what to fix.");
    return;
  }
  setIsLoading(true);
  await fetch(`/api/v1/research/${sessionId}/approve`, {
    method: "POST",
    body: JSON.stringify({ approved: false, feedback }),
  });
  // Redirect back to Brain Monitor (agent is running again)
  router.push(`/session/${sessionId}`);
}
```

#### Critical UX Rules for HITL Gate

1. **Never auto-approve**: No timeouts, no default approvals. The user MUST click.
2. **Show quality signals**: Display citation count, confidence indicators to help user decide.
3. **Rework feedback is required**: If "Reject & Rework" is clicked without feedback, show a validation error.
4. **Markdown preview must be scrollable independently** from the right panel.
5. **Loading state**: Show spinner on both buttons while the API call is in flight; disable both.

---

### 4.4 Export & Output View

**Route**: `/session/[sessionId]` when `status === "COMPLETED"`  
**Purpose**: Display the final report with analytics and export options.

#### Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  ✅ Research Complete                                               │
│                                                                     │
│  [📄 Export as PDF]  [📝 Export as DOCX]  [📋 Copy Markdown]       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  FINAL REPORT (Full Markdown Render)                                │
│  ─────────────────────────────────────────────────────             │
│  ## AI Investments in Healthcare Q3 2024                           │
│  ...                                                                │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│  ANALYTICS BAR                                                      │
│  ⏱ Time: 2m 34s   📎 Sources: 12   💰 Cost: $0.09   🔄 Loops: 1  │
└─────────────────────────────────────────────────────────────────────┘
```

#### Analytics Bar Data Points

| Metric | Source | Display |
|---|---|---|
| Time elapsed | `session.elapsed_seconds` | "2m 34s" |
| Sources cited | Count of unique URLs in `raw_context` | "12 sources" |
| Compute cost | `session.total_cost_usd` | "$0.09" |
| Critic loops | Max `critic_loop_count` across all tasks | "1 revision" |
| Estimated time saved | `elapsed_seconds * 10` (heuristic) | "~25 min saved" |

---

## 5. State Management Architecture

### 5.1 Zustand Store Definition

```typescript
// store/useResearchStore.ts
import { create } from "zustand";

interface ResearchStore {
  // Active session
  activeSessionId: string | null;
  sessionStatus: SessionStatus | null;

  // Agent logs (populated via SSE)
  agentLogs: AgentLog[];
  addLog: (log: AgentLog) => void;
  clearLogs: () => void;

  // HITL state
  hitlDraft: string | null;
  setHitlDraft: (draft: string) => void;

  // Actions
  startSession: (sessionId: string) => void;
  endSession: () => void;
}

export const useResearchStore = create<ResearchStore>((set) => ({
  activeSessionId: null,
  sessionStatus: null,
  agentLogs: [],
  hitlDraft: null,

  addLog: (log) => set((state) => ({
    agentLogs: [...state.agentLogs.slice(-499), log], // Keep last 500
  })),

  clearLogs: () => set({ agentLogs: [] }),
  setHitlDraft: (draft) => set({ hitlDraft: draft }),
  startSession: (sessionId) => set({ activeSessionId: sessionId, agentLogs: [] }),
  endSession: () => set({ activeSessionId: null, sessionStatus: null }),
}));
```

### 5.2 TanStack Query Usage

```typescript
// hooks/useSessionStatus.ts
import { useQuery } from "@tanstack/react-query";

export function useSessionStatus(sessionId: string) {
  return useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => fetch(`/api/v1/research/${sessionId}/status`).then(r => r.json()),
    refetchInterval: (data) => {
      // Stop polling once in a terminal state
      if (["COMPLETED", "FAILED"].includes(data?.status)) return false;
      return 5000; // Poll every 5s as fallback (SSE is primary)
    },
    staleTime: 0,
  });
}
```

---

## 6. Real-Time SSE Integration

### 6.1 Custom SSE Hook

```typescript
// hooks/useAgentStream.ts
import { useEffect } from "react";
import { useResearchStore } from "@/store/useResearchStore";

export function useAgentStream(sessionId: string | null) {
  const { addLog, setHitlDraft } = useResearchStore();

  useEffect(() => {
    if (!sessionId) return;

    const es = new EventSource(`/api/v1/research/${sessionId}/stream`, {
      withCredentials: true,  // Include auth cookie
    });

    es.onmessage = (event) => {
      const payload = JSON.parse(event.data);

      switch (payload.type) {
        case "agent_log":
          addLog(payload.log);
          break;
        case "HITL_READY":
          setHitlDraft(payload.draft);
          // TanStack Query will re-fetch and route to HITL gate
          break;
        case "COMPLETED":
        case "FAILED":
          es.close();
          break;
      }
    };

    es.onerror = () => {
      console.error("SSE connection lost for session:", sessionId);
      es.close();
    };

    return () => es.close();
  }, [sessionId, addLog, setHitlDraft]);
}
```

---

## 7. Accessibility Requirements

- **All interactive elements** must have descriptive `aria-label` attributes.
- **Focus management**: When HITL gate opens, focus must move to the first action button.
- **Color is not the only indicator**: Status icons (✅ ❌ 🔄) supplement colors for colorblind users.
- **Keyboard navigation**: Tab order must flow logically: query box → depth selector → source toggles → submit button.
- **Reduced motion**: Respect `prefers-reduced-motion` — disable non-essential animations.

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

---

## 8. Error & Loading States

### 8.1 Required States for Every Async Component

Every data-fetching component **must** implement all four states:

```typescript
// Pattern template for all async components
function ResearchComponent({ sessionId }: Props) {
  const { data, isLoading, isError, error } = useSessionStatus(sessionId);

  if (isLoading) return <SessionSkeleton />;      // Never show blank screen
  if (isError)   return <ErrorCard message={error.message} retry={refetch} />;
  if (!data)     return <EmptyState />;           // Explicit empty state
  return <SessionContent data={data} />;          // Happy path
}
```

### 8.2 Toast Notification System

```typescript
// Use react-hot-toast for all transient notifications
import toast from "react-hot-toast";

// Success
toast.success("Research session started! Estimated time: 2–4 minutes.");

// Error
toast.error("Failed to start research. Please check your inputs and try again.");

// Cost warning (when > $0.40 spent)
toast("⚠️ High compute cost detected: $0.42. Budget limit: $0.50.", {
  icon: "💰",
  duration: 6000,
});
```

### 8.3 Network Disconnect Recovery

If the SSE stream disconnects mid-session (network issue), implement exponential backoff reconnection:

```typescript
function reconnectSSE(sessionId: string, attempt: number = 0) {
  const delay = Math.min(1000 * Math.pow(2, attempt), 30000); // Max 30s
  setTimeout(() => {
    // Re-establish SSE connection
    createSSEConnection(sessionId, attempt + 1);
  }, delay);
}
```
