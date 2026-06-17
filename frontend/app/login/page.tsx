"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

type AuthMode = "login" | "register";

export default function AuthPage() {
  const router = useRouter();
  const [mode, setMode] = useState<AuthMode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Redirect if already logged in
  useEffect(() => {
    if (typeof window !== "undefined" && localStorage.getItem("access_token")) {
      router.replace("/dashboard");
    }
  }, [router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);

    if (!email || !password) {
      setError("Please fill in all fields.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }

    setIsLoading(true);
    try {
      if (mode === "register") {
        const res = await fetch(`${API_BASE}/auth/register`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Registration failed.");
        setSuccess("Account created! Logging you in...");
        // Auto-login after register
        await doLogin(email, password);
      } else {
        await doLogin(email, password);
      }
    } catch (err: any) {
      setError(err.message || "An unexpected error occurred.");
    } finally {
      setIsLoading(false);
    }
  };

  const doLogin = async (email: string, password: string) => {
    const res = await fetch(`${API_BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Login failed.");
    localStorage.setItem("access_token", data.access_token);
    router.push("/dashboard");
  };

  return (
    <div className="min-h-screen bg-bg-base flex items-center justify-center px-4">
      {/* Ambient background */}
      <div
        aria-hidden
        className="fixed inset-0 pointer-events-none"
        style={{
          background:
            "radial-gradient(ellipse 80% 50% at 50% -20%, rgba(108,99,255,0.15) 0%, transparent 60%)",
        }}
      />

      <div className="w-full max-w-md animate-slide-up">
        {/* Logo */}
        <div className="text-center mb-8">
          <div
            className="w-16 h-16 rounded-2xl flex items-center justify-center text-3xl mx-auto mb-4"
            style={{ background: "rgba(108,99,255,0.15)", border: "1px solid rgba(108,99,255,0.3)" }}
          >
            🔬
          </div>
          <h1 className="text-2xl font-bold text-gradient">Research Assistant</h1>
          <p className="text-slate-400 text-sm mt-1">AI-powered multi-agent research synthesis</p>
        </div>

        {/* Card */}
        <div className="card">
          {/* Tab switcher */}
          <div
            className="flex rounded-lg p-1 mb-6"
            style={{ background: "var(--color-bg-elevated)" }}
          >
            {(["login", "register"] as AuthMode[]).map((m) => (
              <button
                key={m}
                type="button"
                id={`tab-${m}`}
                onClick={() => { setMode(m); setError(null); setSuccess(null); }}
                className="flex-1 py-2 rounded-md text-sm font-medium capitalize transition-all duration-200"
                style={{
                  background: mode === m ? "var(--color-bg-surface)" : "transparent",
                  color: mode === m ? "#f1f5f9" : "#64748b",
                  border: mode === m ? "1px solid var(--color-border)" : "1px solid transparent",
                }}
              >
                {m === "login" ? "Sign In" : "Create Account"}
              </button>
            ))}
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="email" className="block text-sm font-medium text-slate-300 mb-1.5">
                Email
              </label>
              <input
                id="email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                className="input-base"
                required
              />
            </div>

            <div>
              <label htmlFor="password" className="block text-sm font-medium text-slate-300 mb-1.5">
                Password
              </label>
              <input
                id="password"
                type="password"
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={mode === "register" ? "Min. 8 characters" : "••••••••"}
                className="input-base"
                required
              />
            </div>

            {/* Error / Success messages */}
            {error && (
              <div
                className="rounded-lg px-4 py-3 text-sm animate-fade-in"
                style={{ background: "rgba(248,113,113,0.1)", border: "1px solid rgba(248,113,113,0.3)", color: "#f87171" }}
              >
                ⚠️ {error}
              </div>
            )}
            {success && (
              <div
                className="rounded-lg px-4 py-3 text-sm animate-fade-in"
                style={{ background: "rgba(74,222,128,0.1)", border: "1px solid rgba(74,222,128,0.3)", color: "#4ade80" }}
              >
                ✅ {success}
              </div>
            )}

            <button
              id="auth-submit-btn"
              type="submit"
              disabled={isLoading}
              className="btn-primary w-full mt-2"
              style={{ paddingTop: "0.875rem", paddingBottom: "0.875rem" }}
            >
              {isLoading ? (
                <><span className="spinner" /> {mode === "login" ? "Signing in..." : "Creating account..."}</>
              ) : (
                mode === "login" ? "Sign In →" : "Create Account →"
              )}
            </button>
          </form>

          {/* Dev quick-start hint */}
          <p className="text-center text-xs text-slate-600 mt-5">
            First time?{" "}
            <button
              type="button"
              onClick={() => setMode("register")}
              className="text-slate-400 hover:text-slate-200 underline transition-colors"
            >
              Create an account
            </button>{" "}
            to get started.
          </p>
        </div>

        <p className="text-center text-xs text-slate-600 mt-6">
          Multi-Agent Research Assistant v1.0 · Powered by GPT-4o & Gemini
        </p>
      </div>
    </div>
  );
}
