"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import ChatPanel, { ChatMessage } from "@/components/ChatPanel";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

// ─── Types ────────────────────────────────────────────────────────────────────
type SessionStatus = "PENDING" | "RUNNING" | "AWAITING_APPROVAL" | "COMPLETED" | "FAILED";

interface AgentLog {
  agent_name: "planner" | "executor" | "critic" | "synthesizer" | "system";
  action: string;
  result?: Record<string, unknown> | null;
  timestamp?: string;
}

interface SessionData {
  session_id: string;
  status: SessionStatus;
  prompt: string;
  total_cost_usd: number;
  elapsed_seconds?: number;
  draft_report?: string;
  final_report?: string;
  error_message?: string;
}

const AGENT_META: Record<string, { icon: string; color: string }> = {
  planner:     { icon: "🧠", color: "#38bdf8" },
  executor:    { icon: "🕵️", color: "#fb923c" },
  critic:      { icon: "⚖️", color: "#f472b6" },
  synthesizer: { icon: "📝", color: "#4ade80" },
  system:      { icon: "⚙️", color: "#94a3b8" },
};

const STATUS_CONFIG: Record<SessionStatus, { label: string; cls: string }> = {
  PENDING:           { label: "⏳ Pending",         cls: "badge-pending" },
  RUNNING:           { label: "🔄 Running",         cls: "badge-running" },
  AWAITING_APPROVAL: { label: "🚦 Review Required", cls: "badge-awaiting" },
  COMPLETED:         { label: "✅ Completed",       cls: "badge-completed" },
  FAILED:            { label: "❌ Failed",          cls: "badge-failed" },
};

const PIPELINE_STEPS = ["Planner", "Executor", "Critic", "Synthesizer", "Synthesis"];

import { use } from "react";

// ─── Page ─────────────────────────────────────────────────────────────────────
export default function SessionPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = use(params);
  const router = useRouter();

  const [status, setStatus] = useState<SessionStatus>("PENDING");
  const [sessionData, setSessionData] = useState<SessionData | null>(null);
  const [logs, setLogs] = useState<AgentLog[]>([]);
  const [elapsed, setElapsed] = useState(0);
  const [feedback, setFeedback] = useState("");
  const [feedbackError, setFeedbackError] = useState("");
  const [isApproving, setIsApproving] = useState(false);
  const [isReworking, setIsReworking] = useState(false);
  const [toast, setToast] = useState<{ msg: string; type: "success" | "error" } | null>(null);

  // Chat state
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [isChatLoading, setIsChatLoading] = useState(false);

  const logEndRef = useRef<HTMLDivElement>(null);
  const esRef = useRef<EventSource | null>(null);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const startTimeRef = useRef(Date.now());

  const getToken = () =>
    typeof window !== "undefined" ? localStorage.getItem("access_token") : null;

  // ─── Auth guard ─────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!getToken()) { router.replace("/login"); }
  }, [router]);

  // ─── Fetch status ────────────────────────────────────────────────────────────
  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/research/${sessionId}/status`, {
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      if (res.status === 401) { router.replace("/login"); return null; }
      if (res.ok) {
        const data: SessionData = await res.json();
        setSessionData(data);
        setStatus(data.status);
        return data.status;
      }
    } catch { /* ignore */ }
    return null;
  }, [sessionId, router]);

  // ─── Elapsed timer ───────────────────────────────────────────────────────────
  useEffect(() => {
    timerRef.current = setInterval(
      () => setElapsed(Math.floor((Date.now() - startTimeRef.current) / 1000)),
      1000,
    );
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, []);

  // ─── SSE stream ──────────────────────────────────────────────────────────────
  useEffect(() => {
    fetchStatus();
    const connect = () => {
      esRef.current?.close();
      const es = new EventSource(`${API_BASE}/research/${sessionId}/stream`);
      esRef.current = es;

      es.onmessage = async (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (payload.type === "agent_log") {
            setLogs((prev) => [...prev.slice(-499), payload.data as AgentLog]);
          } else if (payload.type === "HITL_READY") {
            setStatus("AWAITING_APPROVAL");
            await fetchStatus();
            if (timerRef.current) clearInterval(timerRef.current);
          } else if (payload.type === "COMPLETED") {
            setStatus("COMPLETED");
            await fetchStatus();
            if (timerRef.current) clearInterval(timerRef.current);
            es.close();
          } else if (payload.type === "FAILED") {
            setStatus("FAILED");
            await fetchStatus();
            if (timerRef.current) clearInterval(timerRef.current);
            es.close();
          }
        } catch { /* non-JSON message */ }
      };
      es.onerror = () => fetchStatus();
    };
    connect();
    return () => esRef.current?.close();
  }, [sessionId, fetchStatus]);

  // ─── Auto-scroll logs ────────────────────────────────────────────────────────
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  // ─── Fetch chat history ──────────────────────────────────────────────────────
  const fetchChatHistory = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/research/${sessionId}/chat`, {
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      if (res.ok) {
        const data = await res.json();
        setChatMessages(data);
      }
    } catch { /* ignore */ }
  }, [sessionId]);

  useEffect(() => {
    if (status === "COMPLETED") {
      fetchChatHistory();
    }
  }, [status, fetchChatHistory]);

  // ─── Send Chat Message ───────────────────────────────────────────────────────
  const handleSendMessage = async (msg: string) => {
    setIsChatLoading(true);
    
    // Optimistic UI update
    const tempId = Date.now().toString();
    setChatMessages(prev => [...prev, { id: tempId, role: 'user', content: msg, created_at: new Date().toISOString() }]);

    try {
      const res = await fetch(`${API_BASE}/research/${sessionId}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}` },
        body: JSON.stringify({ message: msg }),
      });

      if (!res.ok || !res.body) throw new Error("Failed to send message");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      
      let aiContent = "";
      setChatMessages(prev => [...prev, { id: "temp-ai", role: 'assistant', content: "", created_at: new Date().toISOString() }]);

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        
        const chunk = decoder.decode(value);
        const lines = chunk.split("\n\n");
        
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const data = JSON.parse(line.slice(6));
              if (data.type === "chunk") {
                aiContent += data.text;
                setChatMessages(prev => {
                  const newMsgs = [...prev];
                  newMsgs[newMsgs.length - 1].content = aiContent;
                  return newMsgs;
                });
              } else if (data.type === "done") {
                setChatMessages(prev => {
                  const newMsgs = [...prev];
                  newMsgs[newMsgs.length - 1].id = data.message_id;
                  return newMsgs;
                });
              }
            } catch { /* ignore parse error */ }
          }
        }
      }
    } catch {
      showToast("Failed to send message", "error");
      // Remove temp messages on error
      setChatMessages(prev => prev.filter(m => m.id !== tempId && m.id !== "temp-ai"));
    } finally {
      setIsChatLoading(false);
    }
  };

  // ─── Toast ───────────────────────────────────────────────────────────────────
  const showToast = (msg: string, type: "success" | "error") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 3500);
  };

  // ─── HITL actions ────────────────────────────────────────────────────────────
  const handleApprove = async () => {
    setIsApproving(true);
    try {
      const res = await fetch(`${API_BASE}/research/${sessionId}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}` },
        body: JSON.stringify({ approved: true, feedback: null }),
      });
      if (!res.ok) throw new Error();
      setStatus("RUNNING");
      setLogs([]);
      showToast("✅ Approved! Generating final report…", "success");
      startTimeRef.current = Date.now();
      const es = new EventSource(`${API_BASE}/research/${sessionId}/stream`);
      esRef.current?.close();
      esRef.current = es;
    } catch {
      showToast("Approval failed. Please try again.", "error");
    } finally {
      setIsApproving(false);
    }
  };

  const handleRework = async () => {
    if (!feedback.trim()) {
      setFeedbackError("Please provide feedback so the agent knows what to improve.");
      return;
    }
    setFeedbackError("");
    setIsReworking(true);
    try {
      const res = await fetch(`${API_BASE}/research/${sessionId}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}` },
        body: JSON.stringify({ approved: false, feedback: feedback.trim() }),
      });
      if (!res.ok) throw new Error();
      setStatus("RUNNING");
      setLogs([]);
      setFeedback("");
      showToast("🔄 Rework started. Agent is revising the draft…", "success");
      startTimeRef.current = Date.now();
      const es = new EventSource(`${API_BASE}/research/${sessionId}/stream`);
      esRef.current?.close();
      esRef.current = es;
    } catch {
      showToast("Rework request failed. Please try again.", "error");
    } finally {
      setIsReworking(false);
    }
  };

  const fmt = (s: number) => (s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`);

  const sc = STATUS_CONFIG[status] || STATUS_CONFIG.PENDING;

  return (
    <div
      className="min-h-screen flex flex-col"
      style={{ background: "var(--color-bg-base)" }}
    >
      {/* Toast */}
      {toast && (
        <div
          className="fixed top-4 right-4 z-50 px-5 py-3 rounded-xl text-sm font-medium shadow-lg animate-slide-up"
          style={
            toast.type === "success"
              ? { background: "rgba(74,222,128,0.15)", border: "1px solid rgba(74,222,128,0.4)", color: "#4ade80" }
              : { background: "rgba(248,113,113,0.15)", border: "1px solid rgba(248,113,113,0.4)", color: "#f87171" }
          }
        >
          {toast.msg}
        </div>
      )}

      {/* ─── Header ─── */}
      <header
        className="sticky top-0 z-10 backdrop-blur-sm"
        style={{ background: "rgba(26,29,39,0.75)", borderBottom: "1px solid var(--color-border)" }}
      >
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <button
            onClick={() => router.push("/dashboard")}
            className="text-sm transition-colors"
            style={{ color: "#64748b" }}
            onMouseEnter={(e) => ((e.target as HTMLElement).style.color = "#f1f5f9")}
            onMouseLeave={(e) => ((e.target as HTMLElement).style.color = "#64748b")}
          >
            ← Back to Dashboard
          </button>
          <div className="flex items-center gap-5 text-sm">
            <span style={{ color: "#64748b" }}>⏱ {fmt(elapsed)}</span>
            {sessionData && sessionData.total_cost_usd > 0 && (
              <span style={{ color: "#64748b" }}>💰 ${sessionData.total_cost_usd.toFixed(4)}</span>
            )}
            <span className={sc.cls}>{sc.label}</span>
          </div>
        </div>
      </header>

      {/* Query banner */}
      {sessionData && (
        <div
          className="px-6 py-3"
          style={{ borderBottom: "1px solid var(--color-border)", background: "rgba(37,40,54,0.4)" }}
        >
          <div className="max-w-7xl mx-auto">
            <p className="text-sm truncate" style={{ color: "#94a3b8" }}>
              <span style={{ color: "#475569", marginRight: "0.5rem" }}>🔬 Researching:</span>
              {sessionData.prompt}
            </p>
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════════════
          PENDING / RUNNING — Brain Monitor
      ══════════════════════════════════════════════ */}
      {(status === "PENDING" || status === "RUNNING") && (
        <div className="flex-1 max-w-7xl mx-auto w-full px-6 py-6 flex gap-5 min-h-0">
          {/* Pipeline sidebar */}
          <div className="w-52 shrink-0">
            <div className="card h-full">
              <h3 className="text-xs font-semibold uppercase tracking-wider mb-4" style={{ color: "#64748b" }}>
                Pipeline
              </h3>
              <div className="space-y-3">
                {PIPELINE_STEPS.map((step) => {
                  const active = logs.some((l) => l.agent_name === step.toLowerCase());
                  return (
                    <div key={step} className="flex items-center gap-2.5 text-sm transition-colors">
                      <span
                        className="w-2 h-2 rounded-full shrink-0"
                        style={{
                          background: active ? "var(--color-accent-primary)" : "#334155",
                          boxShadow: active ? "0 0 6px var(--color-accent-primary)" : "none",
                        }}
                      />
                      <span style={{ color: active ? "#f1f5f9" : "#475569" }}>{step}</span>
                    </div>
                  );
                })}
              </div>

              {/* Running indicator */}
              {status === "RUNNING" && (
                <div
                  className="mt-6 rounded-lg px-3 py-2.5 text-xs flex items-center gap-2"
                  style={{ background: "rgba(251,146,60,0.1)", border: "1px solid rgba(251,146,60,0.2)", color: "#fb923c" }}
                >
                  <span className="w-1.5 h-1.5 rounded-full bg-orange-400 animate-pulse" />
                  Agents running…
                </div>
              )}
            </div>
          </div>

          {/* Live log feed */}
          <div className="flex-1 card flex flex-col min-h-0">
            <h3 className="text-xs font-semibold uppercase tracking-wider mb-4 shrink-0" style={{ color: "#64748b" }}>
              🧠 Agent Brain — Live Feed
            </h3>
            <div
              className="flex-1 overflow-y-auto font-mono text-xs space-y-1.5 min-h-0"
              style={{ maxHeight: "calc(100vh - 280px)" }}
            >
              {logs.length === 0 && (
                <div className="animate-pulse" style={{ color: "#334155" }}>
                  Waiting for agent to start…
                </div>
              )}
              {logs.map((log, i) => {
                const meta = AGENT_META[log.agent_name] || AGENT_META.system;
                return (
                  <div key={i} className="flex gap-2.5 leading-relaxed animate-fade-in">
                    <span className="shrink-0 tabular-nums" style={{ color: "#334155" }}>
                      {log.timestamp
                        ? new Date(log.timestamp).toLocaleTimeString()
                        : "--:--:--"}
                    </span>
                    <span className="shrink-0 font-medium" style={{ color: meta.color }}>
                      {meta.icon} {log.agent_name}
                    </span>
                    <span className="break-all" style={{ color: "#cbd5e1" }}>
                      {log.action}
                    </span>
                  </div>
                );
              })}
              <div ref={logEndRef} />
            </div>
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════════════
          AWAITING_APPROVAL — Human-in-the-Loop Gate
      ══════════════════════════════════════════════ */}
      {status === "AWAITING_APPROVAL" && sessionData?.draft_report && (
        <div className="flex-1 max-w-7xl mx-auto w-full px-6 py-6 flex gap-5 min-h-0">
          {/* Draft report */}
          <div
            className="flex-1 card overflow-y-auto"
            style={{ maxHeight: "calc(100vh - 200px)" }}
          >
            <div
              className="flex items-center gap-2 mb-5 pb-4"
              style={{ borderBottom: "1px solid var(--color-border)" }}
            >
              <span style={{ fontSize: "1.25rem" }}>📋</span>
              <h2 className="font-semibold" style={{ color: "#f1f5f9" }}>Draft Report</h2>
              <span className="badge-awaiting ml-2">Needs Review</span>
            </div>
            <div
              className="prose max-w-none"
              style={{
                color: "#cbd5e1",
                lineHeight: 1.8,
              }}
            >
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {sessionData.draft_report}
              </ReactMarkdown>
            </div>
          </div>

          {/* Decision panel */}
          <div className="w-72 shrink-0 space-y-4">
            {/* Approve card */}
            <div className="card">
              <div className="flex items-center gap-3 mb-4">
                <span style={{ fontSize: "1.5rem" }}>🚦</span>
                <div>
                  <h3 className="font-semibold" style={{ color: "#f1f5f9" }}>
                    Your Review Required
                  </h3>
                  <p className="text-xs mt-0.5" style={{ color: "#64748b" }}>
                    The AI has compiled its draft.
                  </p>
                </div>
              </div>

              <div className="space-y-1.5 mb-5 text-sm">
                <div className="flex items-center gap-2" style={{ color: "#4ade80" }}>
                  <span>✅</span><span>Draft compiled</span>
                </div>
                <div className="flex items-center gap-2" style={{ color: "#64748b" }}>
                  <span>💰</span>
                  <span>Cost so far: ${sessionData?.total_cost_usd?.toFixed(4) ?? "0.0000"}</span>
                </div>
              </div>

              <button
                id="approve-btn"
                onClick={handleApprove}
                disabled={isApproving || isReworking}
                className="btn-primary w-full mb-3"
              >
                {isApproving
                  ? <><span className="spinner" /> Finalizing…</>
                  : "✅ Approve & Finalize"}
              </button>
            </div>

            {/* Rework card */}
            <div className="card">
              <label
                htmlFor="feedback-box"
                className="block text-xs font-semibold uppercase tracking-wider mb-2"
                style={{ color: "#64748b" }}
              >
                Rework Feedback
              </label>
              <textarea
                id="feedback-box"
                value={feedback}
                onChange={(e) => { setFeedback(e.target.value); setFeedbackError(""); }}
                placeholder='e.g., "Add more data on the European market" or "Make the tone more formal"'
                rows={4}
                maxLength={1000}
                className="textarea-base"
                style={{ fontSize: "0.8125rem" }}
              />
              {feedbackError && (
                <p className="text-xs mt-1" style={{ color: "#f87171" }}>{feedbackError}</p>
              )}
              <button
                id="submit-rework-btn"
                onClick={handleRework}
                disabled={isApproving || isReworking}
                className="btn-danger w-full mt-3"
              >
                {isReworking
                  ? <><span className="spinner" style={{ borderTopColor: "#f87171", borderColor: "rgba(248,113,113,0.25)" }} /> Sending…</>
                  : "🔄 Reject & Rework"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════════════
          COMPLETED — Export View & Chat
      ══════════════════════════════════════════════ */}
      {status === "COMPLETED" && sessionData?.final_report && (
        <div className="flex-1 max-w-[1600px] mx-auto w-full px-6 py-6 flex gap-6 min-h-0">
          
          {/* Left panel: Report */}
          <div className="flex-1 flex flex-col min-w-0">
            {/* Metrics bar */}
            <div className="card-elevated flex flex-wrap items-center gap-6 mb-6 shrink-0">
              <Metric icon="✅" label="Status" value="Completed" />
              {sessionData.elapsed_seconds && (
                <Metric icon="⏱" label="Duration" value={fmt(Math.round(sessionData.elapsed_seconds))} />
              )}
              <Metric icon="💰" label="Cost" value={`$${sessionData.total_cost_usd.toFixed(4)}`} />
              <div className="ml-auto flex gap-2">
                <button
                  id="copy-markdown-btn"
                  onClick={() => {
                    navigator.clipboard.writeText(sessionData.final_report!);
                    showToast("📋 Copied to clipboard!", "success");
                  }}
                  className="btn-secondary"
                  style={{ padding: "0.5rem 1rem", fontSize: "0.875rem" }}
                >
                  📋 Copy
                </button>
                <button
                  className="btn-primary"
                  style={{ padding: "0.5rem 1rem", fontSize: "0.875rem" }}
                  onClick={() => {
                    const blob = new Blob([sessionData.final_report!], { type: "text/markdown" });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement("a");
                    a.href = url;
                    a.download = `research-report-${sessionId.slice(0, 8)}.md`;
                    a.click();
                    URL.revokeObjectURL(url);
                  }}
                >
                  📄 Download .md
                </button>
              </div>
            </div>

            {/* Final report */}
            <div
              className="card flex-1 overflow-y-auto"
              style={{ maxHeight: "calc(100vh - 220px)" }}
            >
              <div
                className="prose max-w-none"
                style={{ color: "#cbd5e1", lineHeight: 1.8 }}
              >
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {sessionData.final_report}
                </ReactMarkdown>
              </div>
            </div>
          </div>

          {/* Right panel: Chat */}
          <div className="w-[450px] shrink-0 rounded-xl overflow-hidden shadow-lg border border-[rgba(255,255,255,0.08)]" style={{ maxHeight: "calc(100vh - 140px)" }}>
            <ChatPanel 
              messages={chatMessages} 
              onSendMessage={handleSendMessage} 
              isLoading={isChatLoading} 
            />
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════════════
          FAILED
      ══════════════════════════════════════════════ */}
      {status === "FAILED" && (
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="card text-center max-w-md animate-fade-in">
            <div style={{ fontSize: "3rem", marginBottom: "1rem" }}>🚨</div>
            <h2
              className="text-xl font-semibold mb-2"
              style={{ color: "#f87171" }}
            >
              Research Failed
            </h2>
            <p className="text-sm mb-1" style={{ color: "#64748b" }}>
              {sessionData?.error_message || "An unexpected error occurred during the research pipeline."}
            </p>
            <button
              onClick={() => router.push("/dashboard")}
              className="btn-primary mt-6 mx-auto"
              style={{ display: "inline-flex" }}
            >
              ← Try Again
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Sub-components ────────────────────────────────────────────────────────────
function Metric({ icon, label, value }: { icon: string; label: string; value: string }) {
  return (
    <div className="flex items-center gap-2.5">
      <span style={{ fontSize: "1.125rem" }}>{icon}</span>
      <div>
        <p className="text-xs" style={{ color: "#64748b" }}>{label}</p>
        <p className="text-sm font-semibold" style={{ color: "#f1f5f9" }}>{value}</p>
      </div>
    </div>
  );
}
