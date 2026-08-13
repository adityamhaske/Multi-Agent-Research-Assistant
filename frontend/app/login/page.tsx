"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import toast from "react-hot-toast";

import { useLogin, useMe, useRegister } from "@/hooks/queries";
import { ApiError } from "@/lib/api";

type Mode = "login" | "register";

const MIN_PASSWORD = 12; // matches backend policy (services/passwords.py)

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const login = useLogin();
  const register = useRegister();
  // If a valid session (or refreshable one) already exists, skip the form.
  const { data: me } = useMe();

  useEffect(() => {
    if (me) router.replace("/dashboard");
  }, [me, router]);

  const busy = login.isPending || register.isPending;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!email.trim()) return setError("Please enter your email.");
    if (mode === "register" && password.length < MIN_PASSWORD) {
      return setError(`Password must be at least ${MIN_PASSWORD} characters.`);
    }
    if (!password) return setError("Please enter your password.");

    try {
      if (mode === "register") {
        await register.mutateAsync({ email, password });
        // Registration is neutral (no enumeration). Try to log straight in; if the
        // email was already taken, the login will fail and we guide them to sign in.
        try {
          await login.mutateAsync({ email, password });
          router.replace("/dashboard");
        } catch {
          toast.success("If that email was available, your account is ready. Please sign in.");
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
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-md animate-slide-up">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center border border-border bg-accent-muted text-2xl font-serif text-accent font-bold">
            §
          </div>
          <h1 className="font-serif text-2xl font-bold tracking-tight text-text-primary">
            Research Assistant
          </h1>
          <p className="mt-1 text-sm text-text-muted">
            Plan, gather cited evidence, and synthesize a reviewable report.
          </p>
        </div>

        <div className="card">
          <div role="tablist" aria-label="Authentication mode" className="segmented mb-6">
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
              <label htmlFor="email" className="mb-1.5 block text-sm font-medium text-text-secondary">
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
              <label htmlFor="password" className="mb-1.5 block text-sm font-medium text-text-secondary">
                Password
              </label>
              <input
                id="password"
                type="password"
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={mode === "register" ? `At least ${MIN_PASSWORD} characters` : "••••••••••••"}
                className="input-base font-mono"
                required
                minLength={mode === "register" ? MIN_PASSWORD : undefined}
              />
            </div>

            {error && (
              <p
                role="alert"
                className="border border-danger/40 bg-danger/10 px-3 py-2 font-mono text-xs text-danger"
              >
                {error}
              </p>
            )}

            <button type="submit" disabled={busy} className="btn btn-primary w-full">
              {busy && <span className="spinner" />}
              {mode === "login" ? "Sign in" : "Create account"}
            </button>
          </form>
        </div>

        <p className="mt-6 text-center font-mono text-xs text-text-muted">
          Multi-Agent Research Assistant · Academic Edition
        </p>
      </div>
    </div>
  );
}
