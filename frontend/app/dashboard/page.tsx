"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ThemeToggle } from "@/components/ThemeToggle";

// ─── Types ────────────────────────────────────────────────────────────────────
type ResearchDepth = "fast" | "balanced" | "comprehensive";
type RecentSession = {
  id: string;
  prompt: string;
  status: string;
  total_cost_usd: number;
  created_at: string;
};

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export default function DashboardPage() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [depth, setDepth] = useState<ResearchDepth>("balanced");
  const [sources, setSources] = useState<string[]>(["web"]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sessions, setSessions] = useState<RecentSession[]>([]);
  const [userEmail, setUserEmail] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // ─── Auth guard ────────────────────────────────────────────────────────────
  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (!token) {
      router.replace("/login");
      return;
    }
    // Fetch current user info
    fetch(`${API_BASE}/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => {
        if (r.status === 401) { localStorage.removeItem("access_token"); router.replace("/login"); return; }
        return r.json();
      })
      .then((data) => data && setUserEmail(data.email))
      .catch(() => {});

    fetchSessions(token);
    textareaRef.current?.focus();
  }, [router]);

  const fetchSessions = async (token: string) => {
    try {
      const res = await fetch(`${API_BASE}/research/?limit=5`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setSessions(data.sessions || []);
      }
    } catch { /* silent */ }
  };

  const handleLogout = () => {
    localStorage.removeItem("access_token");
    router.replace("/login");
  };

  const handleSourceToggle = (source: string) => {
    setSources((prev) =>
      prev.includes(source) ? prev.filter((s) => s !== source) : [...prev, source]
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim().length < 10) {
      setError("Please enter at least 10 characters for your research query.");
      return;
    }
    setIsLoading(true);
    setError(null);

    try {
      const token = localStorage.getItem("access_token");
      const res = await fetch(`${API_BASE}/research/start`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ query: query.trim(), depth, sources }),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to start research session.");
      }

      const data = await res.json();
      router.push(`/session/${data.session_id}`);
    } catch (err: any) {
      setError(err.message || "Something went wrong. Please try again.");
      setIsLoading(false);
    }
  };

  const depthMeta: Record<ResearchDepth, { icon: string; desc: string }> = {
    fast:          { icon: "⚡", desc: "~1 min" },
    balanced:      { icon: "⚖️", desc: "~3 min" },
    comprehensive: { icon: "🔬", desc: "~8 min" },
  };

  const statusBadge = (status: string) => {
    const cls: Record<string, string> = {
      COMPLETED: "badge-completed", RUNNING: "badge-running",
      PENDING: "badge-pending", FAILED: "badge-failed",
      AWAITING_APPROVAL: "badge-awaiting",
    };
    const icons: Record<string, string> = {
      COMPLETED: "✅", RUNNING: "🔄", PENDING: "⏳",
      FAILED: "❌", AWAITING_APPROVAL: "🚦",
    };
    return (
      <span className={cls[status] || "badge-pending"}>
        {icons[status] || "⏳"} {status.replace(/_/g, " ")}
      </span>
    );
  };

  return (
    <div className="min-h-screen" style={{ background: "var(--color-bg-base)" }}>
      {/* Ambient background gradient */}
      <div
        aria-hidden
        className="fixed inset-0 pointer-events-none"
        style={{
          background:
            "radial-gradient(ellipse 80% 50% at 50% -20%, rgba(108,99,255,0.12) 0%, transparent 60%)",
        }}
      />

      {/* ─── Header ─── */}
      <header
        className="sticky top-0 z-10 backdrop-blur-sm"
        style={{
          background: "rgba(26,29,39,0.75)",
          borderBottom: "1px solid var(--color-border)",
        }}
      >
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div
              className="w-8 h-8 rounded-lg flex items-center justify-center text-base"
              style={{ background: "rgba(108,99,255,0.15)", border: "1px solid rgba(108,99,255,0.3)" }}
            >
              🔬
            </div>
            <span className="font-bold text-lg text-gradient">Research Assistant</span>
          </div>

          <div className="flex items-center gap-6">
            {userEmail && (
              <span className="text-xs text-slate-500 hidden sm:block">{userEmail}</span>
            )}
            <ThemeToggle />
            <Link
              href="/history"
              className="text-sm font-medium text-[#a78bfa] hover:text-[#c4b5fd] transition-colors"
            >
              View History
            </Link>
            <button
              id="logout-btn"
              onClick={handleLogout}
              className="text-sm text-slate-400 hover:text-slate-200 transition-colors"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      {/* ─── Main ─── */}
      <main className="max-w-5xl mx-auto px-6 py-12 relative">
        {/* Hero text */}
        <div className="text-center mb-10 animate-fade-in">
          <h2 className="text-4xl font-bold text-gradient mb-3">
            What do you want to research?
          </h2>
          <p className="text-slate-400 text-lg max-w-2xl mx-auto">
            Multi-agent AI pipeline — Planner → Executor → Critic → Synthesizer.
            Turn hours of research into minutes.
          </p>
        </div>

        {/* Query form */}
        <form
          onSubmit={handleSubmit}
          className="card mb-8 animate-slide-up"
        >
          {/* Textarea */}
          <div className="mb-5">
            <label htmlFor="research-query" className="sr-only">Research query</label>
            <textarea
              ref={textareaRef}
              id="research-query"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g., Analyze the competitive landscape of AI coding assistants in Q4 2024 — focus on GitHub Copilot, Cursor, and Tabnine..."
              rows={4}
              maxLength={2000}
              className="textarea-base"
              aria-describedby="char-count"
            />
            <div
              id="char-count"
              className="flex justify-between mt-2 text-xs"
              style={{ color: "#64748b" }}
            >
              <span style={{ color: query.length > 0 && query.length < 10 ? "#f87171" : "#64748b" }}>
                {query.length > 0 && query.length < 10 ? "⚠️ Minimum 10 characters" : ""}
              </span>
              <span>{query.length} / 2000</span>
            </div>
          </div>

          {/* Controls row */}
          <div className="flex flex-wrap gap-6 mb-6">
            {/* Research Depth */}
            <div>
              <p
                className="text-xs font-semibold mb-2 uppercase tracking-wider"
                style={{ color: "#64748b" }}
              >
                Research Depth
              </p>
              <div className="flex gap-2" role="group" aria-label="Research depth">
                {(Object.keys(depthMeta) as ResearchDepth[]).map((d) => (
                  <button
                    key={d}
                    type="button"
                    id={`depth-${d}`}
                    onClick={() => setDepth(d)}
                    aria-pressed={depth === d}
                    style={{
                      padding: "0.5rem 1rem",
                      borderRadius: "0.5rem",
                      fontSize: "0.875rem",
                      fontWeight: 500,
                      cursor: "pointer",
                      transition: "all 0.2s",
                      background:
                        depth === d
                          ? "rgba(108,99,255,0.2)"
                          : "var(--color-bg-elevated)",
                      color:
                        depth === d ? "#a78bfa" : "#94a3b8",
                      border: depth === d
                        ? "1px solid rgba(108,99,255,0.5)"
                        : "1px solid var(--color-border)",
                    }}
                  >
                    {depthMeta[d].icon} {d} <span style={{ color: "#64748b", fontSize: "0.75rem" }}>{depthMeta[d].desc}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Sources */}
            <div>
              <p
                className="text-xs font-semibold mb-2 uppercase tracking-wider"
                style={{ color: "#64748b" }}
              >
                Sources
              </p>
              <div className="flex gap-2" role="group" aria-label="Data sources">
                {[{ id: "web", label: "🌐 Web" }, { id: "academic", label: "📚 Academic" }].map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    id={`source-${s.id}`}
                    onClick={() => handleSourceToggle(s.id)}
                    aria-pressed={sources.includes(s.id)}
                    style={{
                      padding: "0.5rem 1rem",
                      borderRadius: "0.5rem",
                      fontSize: "0.875rem",
                      fontWeight: 500,
                      cursor: "pointer",
                      transition: "all 0.2s",
                      background: sources.includes(s.id)
                        ? "rgba(108,99,255,0.2)"
                        : "var(--color-bg-elevated)",
                      color: sources.includes(s.id) ? "#a78bfa" : "#94a3b8",
                      border: sources.includes(s.id)
                        ? "1px solid rgba(108,99,255,0.5)"
                        : "1px solid var(--color-border)",
                    }}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Error */}
          {error && (
            <div
              className="rounded-lg px-4 py-3 text-sm mb-4 animate-fade-in"
              style={{
                background: "rgba(248,113,113,0.1)",
                border: "1px solid rgba(248,113,113,0.3)",
                color: "#f87171",
              }}
            >
              ⚠️ {error}
            </div>
          )}

          {/* Submit */}
          <button
            id="start-research-btn"
            type="submit"
            disabled={isLoading || query.trim().length < 10}
            className="btn-primary w-full"
            style={{ paddingTop: "1rem", paddingBottom: "1rem", fontSize: "1rem" }}
          >
            {isLoading ? (
              <><span className="spinner" style={{ borderTopColor: "white" }} /> Starting research...</>
            ) : (
              "🚀 Start Research"
            )}
          </button>
        </form>

        {/* Recent Sessions */}
        {sessions.length > 0 && (
          <div className="animate-fade-in">
            <h3
              className="text-xs font-semibold uppercase tracking-widest mb-4"
              style={{ color: "#64748b" }}
            >
              Recent Sessions
            </h3>
            <div className="space-y-2">
              {sessions.map((s) => (
                <button
                  key={s.id}
                  onClick={() => router.push(`/session/${s.id}`)}
                  className="card-elevated w-full text-left flex items-center justify-between transition-all duration-200"
                  style={{ cursor: "pointer" }}
                  onMouseEnter={(e) =>
                    ((e.currentTarget as HTMLElement).style.background = "var(--color-bg-hover)")
                  }
                  onMouseLeave={(e) =>
                    ((e.currentTarget as HTMLElement).style.background = "var(--color-bg-elevated)")
                  }
                >
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-slate-200 truncate">{s.prompt}</p>
                    <p className="text-xs mt-0.5" style={{ color: "#64748b" }}>
                      {new Date(s.created_at).toLocaleString()}
                    </p>
                  </div>
                  <div className="flex items-center gap-3 ml-4 shrink-0">
                    {statusBadge(s.status)}
                    {s.total_cost_usd > 0 && (
                      <span className="text-xs" style={{ color: "#64748b" }}>
                        ${s.total_cost_usd.toFixed(3)}
                      </span>
                    )}
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
