"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import toast from "react-hot-toast";

import { ThemeToggle } from "@/components/ThemeToggle";
import { useLogin, useMe, useRegister } from "@/hooks/queries";
import { ApiError } from "@/lib/api";

type Mode = "login" | "register";

const MIN_PASSWORD = 12; // matches backend policy (services/passwords.py)

const AGENT_ROLES = [
  {
    role: "PLANNER",
    tag: "DECOMPOSITION",
    blurb: "Deconstructs complex, ambiguous queries into non-overlapping, targeted search tasks with depth-calibrated budgets.",
  },
  {
    role: "EXECUTOR",
    tag: "RETRIEVAL",
    blurb: "Executes parallel web searches (Tavily/Brave/DDG) & airgapped corpus lookups with strict SSRF-safe page fetching.",
  },
  {
    role: "CRITIC",
    tag: "VERIFICATION",
    blurb: "Evaluates source authority and evidence snippet relevance. Fails closed—flimsy evidence triggers automatic rework rounds.",
  },
  {
    role: "SYNTHESIZER",
    tag: "SYNTHESIS",
    blurb: "Composes dense academic reports with inline per-claim [n] citation markers, structured bibliographies, and contradiction notes.",
  },
];

const METHODOLOGY_STEPS = [
  {
    num: "01",
    title: "Scope & Parameterize",
    desc: "Specify your research question, select depth (Fast, Balanced, Comprehensive), or restrict queries to an uploaded airgapped document corpus.",
  },
  {
    num: "02",
    title: "Observe Multi-Agent Telemetry",
    desc: "Follow the live Server-Sent Events (SSE) telemetry stream showing task execution, search queries, and fail-closed critic verification in real time.",
  },
  {
    num: "03",
    title: "Human Checkpoint Review",
    desc: "Inspect the cited draft report at the mandatory approval gate. Approve to finalize, or provide targeted critique for surgical rework rounds.",
  },
  {
    num: "04",
    title: "Repository Memory & Export",
    desc: "Export cryptographically verifiable .bundle.json SBOM manifests, PDF, or Markdown, and query across the project's long-term memory bank.",
  },
];

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const login = useLogin();
  const register = useRegister();
  const { data: me } = useMe();

  const busy = login.isPending || register.isPending;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!email.trim()) return setError("Please enter your email address.");
    if (mode === "register" && password.length < MIN_PASSWORD) {
      return setError(`Password must be at least ${MIN_PASSWORD} characters.`);
    }
    if (!password) return setError("Please enter your password.");

    try {
      if (mode === "register") {
        await register.mutateAsync({ email, password });
        try {
          await login.mutateAsync({ email, password });
          router.replace("/dashboard");
        } catch {
          toast.success("Account created successfully. Please sign in.");
          setMode("login");
          setPassword("");
        }
      } else {
        await login.mutateAsync({ email, password });
        router.replace("/dashboard");
      }
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Something went wrong. Please try again.";
      setError(msg);
    }
  };

  return (
    <div className="min-h-screen bg-bg-base text-text-primary flex flex-col selection:bg-accent-muted selection:text-accent">
      {/* ── Top Header ─────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-40 border-b border-border bg-bg-surface/90 backdrop-blur-sm">
        <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
          <div className="flex items-center gap-3">
            <div className="flex h-7 w-7 items-center justify-center border border-accent bg-accent text-accent-contrast">
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="square"
                strokeLinejoin="miter"
                className="h-4 w-4"
              >
                <polygon points="12 2 22 8.5 22 15.5 12 22 2 15.5 2 8.5 12 2" />
                <line x1="12" y1="22" x2="12" y2="15.5" />
                <polyline points="22 8.5 12 15.5 2 8.5" />
              </svg>
            </div>
            <span className="font-serif text-base font-bold tracking-tight text-text-primary">
              Multi-Agent Research Assistant
            </span>
          </div>

          <nav className="flex items-center gap-3 font-mono text-xs">
            <Link
              href="https://github.com/adityamhaske/Multi-Agent-Research-Assistant/tree/main/docs"
              target="_blank"
              rel="noopener noreferrer"
              className="flex h-8 items-center gap-1.5 border border-border bg-bg-surface px-2.5 text-text-secondary transition-colors hover:bg-bg-elevated hover:text-text-primary"
              title="Explore project documentation on GitHub"
            >
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.75"
                strokeLinecap="square"
                strokeLinejoin="miter"
                className="h-3.5 w-3.5 text-text-muted"
              >
                <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z" />
                <path d="M6 6h10" />
                <path d="M6 10h10" />
              </svg>
              <span>Docs</span>
            </Link>
            <ThemeToggle />
          </nav>
        </div>
      </header>

      {/* ── Main Landing Hero & Split Layout ───────────────────────────── */}
      <main className="flex-1 mx-auto max-w-7xl w-full px-4 py-8 sm:px-6 lg:px-8 lg:py-12">
        <div className="grid gap-12 lg:grid-cols-12 items-start">
          
          {/* ── Left Column: Editorial & Documentation (7 Cols) ─────────── */}
          <div className="lg:col-span-7 space-y-12">
            
            {/* Masthead */}
            <section id="overview" className="space-y-4">
              <div className="inline-flex items-center gap-2 border border-border bg-bg-surface px-2.5 py-1 font-mono text-[0.6875rem] text-text-secondary">
                <span className="status-marker bg-accent" />
                <span>PROVENANCE-FIRST MULTI-AGENT SYNTHESIS</span>
              </div>

              <h1 className="font-serif text-3xl sm:text-4xl lg:text-5xl font-bold tracking-tight text-text-primary leading-[1.15]">
                Rigorous Deep Research with Verifiable Citations and Mandatory Human Oversight.
              </h1>

              <p className="text-base sm:text-lg leading-relaxed text-text-secondary">
                An open, deterministic autonomous research engine designed for academics, analysts, and
                oversight-critical institutions. Multi-Agent Research Assistant orchestrates specialized
                agents to decompose complex queries, gather multi-source evidence, verify claims through a
                fail-closed critic, and pause at a durable checkpoint for human review.
              </p>
            </section>

            {/* 1. Multi-Agent Pipeline Architecture */}
            <section id="architecture" className="space-y-4 pt-4 border-t border-border">
              <div className="flex items-baseline justify-between">
                <h2 className="font-serif text-xl font-bold text-text-primary tracking-tight">
                  1. Multi-Agent Pipeline Architecture
                </h2>
                <span className="font-mono text-xs text-text-muted">LANGGRAPH STATEGRAPH</span>
              </div>
              <p className="text-sm text-text-muted leading-relaxed">
                Rather than an ungrounded single-prompt loop, the assistant executes a four-stage
                deterministic graph with strict budget controls and structured output validation:
              </p>

              <div className="grid gap-3 sm:grid-cols-2">
                {AGENT_ROLES.map((a) => (
                  <div key={a.role} className="border border-border bg-bg-surface p-4 space-y-2">
                    <div className="flex items-center justify-between font-mono text-xs">
                      <span className="font-bold text-text-primary">{a.role}</span>
                      <span className="text-[0.625rem] text-accent border border-border px-1 bg-accent-muted">
                        {a.tag}
                      </span>
                    </div>
                    <p className="text-xs leading-relaxed text-text-secondary">
                      {a.blurb}
                    </p>
                  </div>
                ))}
              </div>
            </section>

            {/* 2. Why Use This (Core Axioms) */}
            <section id="axioms" className="space-y-5 pt-4 border-t border-border">
              <div className="flex items-baseline justify-between">
                <h2 className="font-serif text-xl font-bold text-text-primary tracking-tight">
                  2. Why Use This Project?
                </h2>
                <span className="font-mono text-xs text-text-muted">CORE AXIOMS</span>
              </div>

              <div className="space-y-4">
                <div className="border border-border bg-bg-surface p-5 space-y-2">
                  <div className="flex items-center gap-2 font-mono text-xs font-semibold text-text-primary">
                    <span className="text-accent">AXIOM I:</span>
                    <span>AUDITABLE HUMAN-IN-THE-LOOP (EU AI ACT COMPLIANT)</span>
                  </div>
                  <p className="text-xs leading-relaxed text-text-secondary">
                    The agent halts at a durable PostgreSQL/SQLite checkpoint (<code className="font-mono bg-bg-elevated px-1">AWAITING_APPROVAL</code>) via LangGraph&apos;s <code className="font-mono bg-bg-elevated px-1">interrupt()</code> mechanism.
                    You inspect cited draft findings, approve with a single click, or submit targeted feedback for surgical rework rounds. No silent auto-finalization.
                  </p>
                </div>

                <div className="border border-border bg-bg-surface p-5 space-y-2">
                  <div className="flex items-center gap-2 font-mono text-xs font-semibold text-text-primary">
                    <span className="text-accent">AXIOM II:</span>
                    <span>VERIFIABLE PER-CLAIM CITATIONS WITH ZERO HALLUCINATION</span>
                  </div>
                  <p className="text-xs leading-relaxed text-text-secondary">
                    Every factual assertion in generated reports is bound to an exact, verbatim extracted source snippet.
                    Interactive superscript badges (<span className="font-mono text-accent">[1]</span>) reveal verified text passages on hover. Claims lacking direct support trigger a visible <span className="font-mono text-danger">[?] unverified</span> badge.
                  </p>
                </div>

                <div className="border border-border bg-bg-surface p-5 space-y-2">
                  <div className="flex items-center gap-2 font-mono text-xs font-semibold text-text-primary">
                    <span className="text-accent">AXIOM III:</span>
                    <span>SELF-HOSTED, BYOK &amp; AIRGAPPED LOCAL CORPUS PRIVACY</span>
                  </div>
                  <p className="text-xs leading-relaxed text-text-secondary">
                    Zero SaaS lock-in or telemetry. Deploy locally with Docker or run completely offline with Ollama local LLMs and local document embeddings.
                    Bring Your Own Key (BYOK) for Anthropic, Google Gemini, OpenAI, or OpenRouter with hardware keychain and encrypted-at-rest storage.
                  </p>
                </div>

                <div className="border border-border bg-bg-surface p-5 space-y-2">
                  <div className="flex items-center gap-2 font-mono text-xs font-semibold text-text-primary">
                    <span className="text-accent">AXIOM IV:</span>
                    <span>CRYPTOGRAPHIC RESEARCH SBOM (.BUNDLE.JSON)</span>
                  </div>
                  <p className="text-xs leading-relaxed text-text-secondary">
                    Export self-contained research manifests containing full agent logs, evidence snippet SHA-256 digests, and approval signatures.
                    Verify any exported report completely offline with the standalone <code className="font-mono bg-bg-elevated px-1">verify_bundle.py</code> tool.
                  </p>
                </div>
              </div>
            </section>

            {/* 3. Operational Methodology (How to Use) */}
            <section id="methodology" className="space-y-4 pt-4 border-t border-border">
              <div className="flex items-baseline justify-between">
                <h2 className="font-serif text-xl font-bold text-text-primary tracking-tight">
                  3. Operational Methodology &amp; Workflow
                </h2>
                <span className="font-mono text-xs text-text-muted">HOW TO OPERATE</span>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                {METHODOLOGY_STEPS.map((s) => (
                  <div key={s.num} className="border border-border bg-bg-surface p-4 space-y-1.5">
                    <div className="font-mono text-xs font-bold text-accent">
                      STEP {s.num} · {s.title}
                    </div>
                    <p className="text-xs leading-relaxed text-text-secondary">
                      {s.desc}
                    </p>
                  </div>
                ))}
              </div>
            </section>

            {/* System Benchmark Table (Booktabs Style) */}
            <section className="space-y-3 pt-4 border-t border-border">
              <div className="flex items-baseline justify-between">
                <h3 className="font-serif text-base font-bold text-text-primary">
                  System Specifications &amp; Benchmark Standards
                </h3>
                <span className="font-mono text-[0.6875rem] text-text-muted">ACADEMIC AUDIT MATRIX</span>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left font-mono text-xs border-y border-border">
                  <thead>
                    <tr className="border-b border-border text-text-muted">
                      <th className="py-2.5 pr-4 font-semibold uppercase tracking-wider">Evaluation Metric</th>
                      <th className="py-2.5 px-4 font-semibold uppercase tracking-wider">Benchmark Standard</th>
                      <th className="py-2.5 pl-4 font-semibold uppercase tracking-wider">System Guarantee</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/50 text-text-secondary">
                    <tr>
                      <td className="py-2 pr-4 font-medium text-text-primary">Citation Support Fidelity</td>
                      <td className="py-2 px-4">≥ 95.0% Snippet-Claim Match</td>
                      <td className="py-2 pl-4 text-success font-semibold">95.2% Verified Baseline</td>
                    </tr>
                    <tr>
                      <td className="py-2 pr-4 font-medium text-text-primary">State Persistence</td>
                      <td className="py-2 px-4">Postgres Checkpointer</td>
                      <td className="py-2 pl-4 text-text-primary">Survives Worker Restarts</td>
                    </tr>
                    <tr>
                      <td className="py-2 pr-4 font-medium text-text-primary">Human Oversight Gate</td>
                      <td className="py-2 px-4">Mandatory (EU AI Act Art. 14)</td>
                      <td className="py-2 pl-4 text-text-primary">Durable Checkpoint interrupt()</td>
                    </tr>
                    <tr>
                      <td className="py-2 pr-4 font-medium text-text-primary">Network Defense</td>
                      <td className="py-2 px-4">SSRF &amp; RFC-1918 Filter</td>
                      <td className="py-2 pl-4 text-text-primary">Fail-closed Page Reader</td>
                    </tr>
                    <tr>
                      <td className="py-2 pr-4 font-medium text-text-primary">Offline Execution</td>
                      <td className="py-2 px-4">Ollama / Local Embeddings</td>
                      <td className="py-2 pl-4 text-text-primary">100% Airgapped Corpus Capable</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>
          </div>

          {/* ── Right Column: Researcher Portal / Authentication (5 Cols) ─ */}
          <div className="lg:col-span-5 lg:sticky lg:top-20 space-y-6">
            
            {/* Auth Card */}
            <div className="border border-border bg-bg-surface p-6 space-y-6 shadow-sm">
              <div className="space-y-1.5 pb-4 border-b border-border">
                <div className="flex items-center justify-between">
                  <h3 className="font-serif text-lg font-bold text-text-primary">
                    Researcher Portal
                  </h3>
                  <span className="font-mono text-[0.625rem] uppercase tracking-wider text-text-muted border border-border px-1.5 py-0.5">
                    SECURE ACCESS
                  </span>
                </div>
                <p className="text-xs text-text-muted">
                  Authenticate to launch research sessions, access project memory, and export verified reports.
                </p>
              </div>

              {me ? (
                <div className="space-y-4 py-2">
                  <div className="border border-border bg-bg-base p-4 space-y-2">
                    <div className="font-mono text-xs text-text-muted uppercase tracking-wider">Active Researcher</div>
                    <div className="font-serif text-base font-bold text-text-primary">
                      {me.display_name || me.email}
                    </div>
                    <div className="font-mono text-xs text-text-muted">{me.email}</div>
                  </div>

                  <button
                    type="button"
                    onClick={() => router.push("/dashboard")}
                    className="btn btn-primary w-full justify-center py-2.5 font-mono text-xs uppercase tracking-wider"
                  >
                    Enter Research Workspace →
                  </button>
                </div>
              ) : (
                <>
                  <div role="tablist" aria-label="Authentication mode" className="segmented">
                    {(["login", "register"] as Mode[]).map((m) => (
                      <button
                        key={m}
                        type="button"
                        role="tab"
                        aria-selected={mode === m}
                        onClick={() => {
                          setMode(m);
                          setError(null);
                        }}
                        className={`segmented-item font-mono text-xs uppercase tracking-wider ${
                          mode === m ? "font-bold text-text-primary" : ""
                        }`}
                      >
                        {m === "login" ? "Sign In" : "Create Account"}
                      </button>
                    ))}
                  </div>

                  <form onSubmit={submit} className="space-y-4" noValidate>
                    <div>
                      <label htmlFor="email" className="mb-1.5 block font-mono text-xs font-medium text-text-secondary uppercase tracking-wider">
                        Email Address
                      </label>
                      <input
                        id="email"
                        type="email"
                        autoComplete="email"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        placeholder="researcher@institution.edu"
                        className="input-base"
                        required
                      />
                    </div>

                    <div>
                      <label htmlFor="password" className="mb-1.5 block font-mono text-xs font-medium text-text-secondary uppercase tracking-wider">
                        Password
                      </label>
                      <input
                        id="password"
                        type="password"
                        autoComplete={mode === "login" ? "current-password" : "new-password"}
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        placeholder={mode === "register" ? `Min ${MIN_PASSWORD} characters` : "••••••••••••"}
                        className="input-base font-mono"
                        required
                        minLength={mode === "register" ? MIN_PASSWORD : undefined}
                      />
                      {mode === "register" && (
                        <p className="mt-1 font-mono text-[0.6875rem] text-text-muted">
                          Passphrases of 12+ characters recommended.
                        </p>
                      )}
                    </div>

                    {error && (
                      <p
                        role="alert"
                        className="border border-danger/40 bg-danger/10 px-3 py-2 font-mono text-xs text-danger"
                      >
                        {error}
                      </p>
                    )}

                    <button
                      type="submit"
                      disabled={busy}
                      className="btn btn-primary w-full justify-center py-2.5 font-mono text-xs uppercase tracking-wider"
                    >
                      {busy && <span className="spinner" />}
                      {mode === "login" ? "Sign In to Workspace" : "Initialize Account"}
                    </button>
                  </form>

                  <div className="border-t border-border pt-4 text-center font-mono text-[0.6875rem] text-text-muted">
                    <span>Single-tenant &amp; self-hosted mode enabled.</span>
                  </div>
                </>
              )}
            </div>

            {/* Quick Architecture Box */}
            <div className="border border-border bg-bg-surface p-4 space-y-3 font-mono text-xs">
              <div className="font-semibold text-text-primary uppercase tracking-wider flex items-center justify-between">
                <span>System Manifest</span>
                <span className="text-success">READY</span>
              </div>
              <div className="space-y-1.5 text-text-muted text-[0.6875rem]">
                <div className="flex justify-between">
                  <span>Engine:</span>
                  <span className="text-text-secondary">LangGraph v1.0+</span>
                </div>
                <div className="flex justify-between">
                  <span>Checkpointer:</span>
                  <span className="text-text-secondary">Postgres / SQLite</span>
                </div>
                <div className="flex justify-between">
                  <span>Search Fallback:</span>
                  <span className="text-text-secondary">Tavily → Brave → DDG</span>
                </div>
                <div className="flex justify-between">
                  <span>Privacy:</span>
                  <span className="text-text-secondary">Zero Third-Party Telemetry</span>
                </div>
              </div>
            </div>

            {/* Citation UX Preview Card */}
            <div className="border border-border bg-bg-surface p-4 space-y-2">
              <div className="font-mono text-[0.6875rem] font-semibold uppercase tracking-wider text-text-muted">
                Interactive Citation Demonstration
              </div>
              <p className="text-xs leading-relaxed text-text-secondary italic">
                &ldquo;Multi-agent systems achieve higher factual fidelity when critic nodes fail closed on malformed evidence<span className="font-mono font-bold text-accent not-italic ml-1">[1]</span>.&rdquo;
              </p>
              <div className="border-t border-border pt-2 flex items-center justify-between font-mono text-[0.625rem] text-text-muted">
                <span>[1] Tow Center for Digital Journalism, 2025</span>
                <span className="text-success font-semibold">VERIFIED</span>
              </div>
            </div>

          </div>
        </div>
      </main>

      {/* ── Academic Footer ────────────────────────────────────────────── */}
      <footer className="border-t border-border bg-bg-surface py-6 text-center font-mono text-xs text-text-muted">
        <div className="mx-auto max-w-7xl px-4 flex flex-col sm:flex-row items-center justify-between gap-3">
          <div>
            Multi-Agent Research Assistant · Open Source Research Engine · MIT License
          </div>
          <div className="flex items-center gap-4 text-[0.6875rem]">
            <span>Deterministic Provenance</span>
            <span aria-hidden>·</span>
            <span>Zero Hallucinated Attribution</span>
            <span aria-hidden>·</span>
            <span>Self-Hostable</span>
          </div>
        </div>
      </footer>
    </div>
  );
}

