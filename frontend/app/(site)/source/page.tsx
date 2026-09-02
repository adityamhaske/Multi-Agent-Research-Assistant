import Link from "next/link";

import { pageUrls } from "@/lib/pages-build";

export const metadata = {
  // The root layout's `title.template` appends " · Research Assistant" — see app/layout.tsx.
  title: "Source & Architecture",
  description:
    "Open architecture, module map, reproducible verification, and local execution guide.",
  ...pageUrls("/source"),
};

const MODULES = [
  {
    layer: "Backend Engine",
    path: "backend/research_engine",
    role: "LangGraph pipeline: Planner → Executor ⇄ Critic → Synthesizer → Gate → Finalizer. Fully host-agnostic, deterministic checkpointing, citation extraction, and budget guards.",
    docs: "/docs/architecture/agent-architecture",
  },
  {
    layer: "Backend Application",
    path: "backend/app",
    role: "FastAPI REST API, WebSocket/SSE streaming, Celery pipeline runner, auth cookies, Postgres/pgvector embeddings, and cryptographic bundle signing.",
    docs: "/docs/architecture/system-architecture",
  },
  {
    layer: "Frontend Site & App",
    path: "frontend",
    role: "Next.js 16 + React 19 interface. Multi-target build supporting Standalone Server, Static Documentation Pages, and Tauri Desktop.",
    docs: "/docs/developers/frontend-guidelines",
  },
  {
    layer: "Desktop Sidecar",
    path: "desktop",
    role: "Tauri v2 native desktop shell wrapping an embedded Python sidecar with local SQLite checkpoints and airgapped corpus processing.",
    docs: "/docs/getting-started/desktop-app",
  },
  {
    layer: "Evaluation & Benchmarks",
    path: "backend/evals",
    role: "Rigorous citation-fidelity benchmark harness, baseline comparisons, and support-rate scoring with write-once evidence records.",
    docs: "/docs/research/citation-fidelity-benchmark",
  },
];

export default function SourcePage() {
  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-12 sm:px-6">
      <header>
        <p className="font-mono text-[0.6875rem] uppercase tracking-widest text-text-muted">
          Codebase &amp; Architecture
        </p>
        <h1 className="mt-3 font-serif text-3xl font-bold tracking-tight text-text-primary sm:text-4xl">
          Source &amp; Inspection
        </h1>
        <p className="mt-4 text-base leading-relaxed text-text-secondary">
          Every component of the Multi-Agent Research Assistant is built from the ground up to be
          inspectable, verifiable, and self-hostable.
        </p>
      </header>

      {/* Verification Invariant Banner */}
      <section
        className="mt-8 border p-5"
        style={{
          borderColor: "color-mix(in srgb, var(--accent) 35%, var(--border))",
          backgroundColor: "color-mix(in srgb, var(--accent) 5%, var(--bg-surface))",
        }}
      >
        <h2 className="font-serif text-lg font-bold text-text-primary">
          The Verifiability Invariant
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-text-secondary">
          The core product claim is verifiability: every citation resolves to a real, verifiable source
          with a verbatim supporting snippet. Unverified claims are prominently flagged, and eval
          records are write-once artifacts.
        </p>
      </section>

      {/* Module Architecture Map */}
      <section className="mt-12">
        <h2 className="font-serif text-2xl font-bold tracking-tight text-text-primary">
          Architecture &amp; Subsystems
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-text-muted">
          The codebase is organized into discrete, deeply decoupled layers:
        </p>

        <div className="mt-6 flex flex-col divide-y divide-border border border-border bg-bg-surface">
          {MODULES.map((mod) => (
            <article key={mod.path} className="p-5 transition-colors hover:bg-bg-elevated/40">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-mono text-xs font-semibold text-accent">{mod.layer}</span>
                <code className="font-mono text-xs text-text-muted">{mod.path}</code>
              </div>
              <p className="mt-2 text-sm leading-relaxed text-text-secondary">{mod.role}</p>
              <div className="mt-3">
                <Link
                  href={mod.docs}
                  className="font-mono text-xs text-accent transition-opacity hover:opacity-80"
                >
                  Read documentation →
                </Link>
              </div>
            </article>
          ))}
        </div>
      </section>

      {/* Running & Building Locally */}
      <section className="mt-12">
        <h2 className="font-serif text-2xl font-bold tracking-tight text-text-primary">
          Running Locally
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-text-secondary">
          You can inspect, build, and run the complete research assistant stack on your own machine
          using standard Docker compose or native development environments.
        </p>

        <div className="mt-6 space-y-4">
          <div className="border border-border bg-bg-surface p-4">
            <h3 className="font-mono text-xs font-semibold uppercase tracking-wider text-text-muted">
              1. Full Stack with Docker
            </h3>
            <pre className="mt-2 overflow-x-auto border border-border bg-bg-elevated p-3 font-mono text-xs text-text-primary">
              docker compose -f docker-compose.full.yml up --build
            </pre>
          </div>

          <div className="border border-border bg-bg-surface p-4">
            <h3 className="font-mono text-xs font-semibold uppercase tracking-wider text-text-muted">
              2. Backend Development
            </h3>
            <pre className="mt-2 overflow-x-auto border border-border bg-bg-elevated p-3 font-mono text-xs text-text-primary">
              cd backend &amp;&amp; pytest &amp;&amp; ruff check
            </pre>
          </div>

          <div className="border border-border bg-bg-surface p-4">
            <h3 className="font-mono text-xs font-semibold uppercase tracking-wider text-text-muted">
              3. Frontend Development
            </h3>
            <pre className="mt-2 overflow-x-auto border border-border bg-bg-elevated p-3 font-mono text-xs text-text-primary">
              cd frontend &amp;&amp; npm install &amp;&amp; npm test &amp;&amp; npm run dev
            </pre>
          </div>
        </div>
      </section>

      {/* Quick Navigation Links */}
      <section className="mt-12 flex flex-wrap gap-4 border-t border-border pt-8">
        <Link href="/docs" className="btn btn-primary">
          Explore documentation →
        </Link>
        <Link
          href="/why"
          className="flex h-9 items-center border border-border bg-bg-surface px-3 font-mono text-xs text-text-secondary transition-colors hover:bg-bg-elevated hover:text-text-primary"
        >
          Why this assistant →
        </Link>
        <Link
          href="/license"
          className="flex h-9 items-center border border-border bg-bg-surface px-3 font-mono text-xs text-text-secondary transition-colors hover:bg-bg-elevated hover:text-text-primary"
        >
          View MIT license →
        </Link>
        <Link
          href="/download"
          className="flex h-9 items-center border border-border bg-bg-surface px-3 font-mono text-xs text-text-secondary transition-colors hover:bg-bg-elevated hover:text-text-primary"
        >
          Download desktop app →
        </Link>
      </section>
    </main>
  );
}
