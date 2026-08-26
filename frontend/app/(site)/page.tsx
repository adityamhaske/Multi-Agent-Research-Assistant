import { cookies } from "next/headers";
import Link from "next/link";
import { redirect } from "next/navigation";

import { isDesktop } from "@/lib/desktop";
import { isPagesBuild } from "@/lib/pages-build";

/**
 * Landing page and app entry point (docs/07 §2).
 *
 * The redirect logic is unchanged from when this file did nothing else: a session cookie
 * still means "go straight into the app", server-side so there is no unauthenticated
 * flash of app chrome, and the desktop build still skips all of it because it has no login
 * (docs/13 §7) — `isDesktop` is inlined, so the cookie read compiles out of the static
 * export exactly as before. What changed is only what a *logged-out web visitor* gets:
 * previously a login form, now the page that explains what they would be logging into.
 *
 * Ordering matters. The pitch below leads with verifiability rather than with the agent
 * pipeline, because the pipeline is how it works and verifiability is why anyone would
 * switch (docs/01 §0).
 */

export const metadata = {
  title: "Research Assistant — cited research you can actually verify",
  description:
    "A self-hostable multi-agent research assistant. Every citation resolves to a source " +
    "and a verbatim snippet, and the export can be verified offline with no AI and no network.",
};

const REPO = "https://github.com/adityamhaske/Multi-Agent-Research-Assistant";

const OPEN_SOURCE = [
  {
    term: "Licence",
    detail:
      "MIT. Use it, fork it, run it commercially — no per-seat cost and no lock-in.",
  },
  {
    term: "Your keys, your data",
    detail:
      "Bring your own API key, or run entirely on local models. Nothing is proxied through a service we operate, because there isn't one.",
  },
  {
    term: "Auditable claims",
    detail:
      "The measurements this project publishes are backed by committed evaluation results, and the harness refuses to print a number it did not measure.",
  },
] as const;

const CLAIMS = [
  {
    title: "Every citation is falsifiable",
    body: "Each [n] resolves to a real source and the verbatim sentence that supports it. One that cannot be verified renders a ⚠ chip instead of rendering clean.",
  },
  {
    title: "You approve the plan before it spends",
    body: "The run pauses after the planner. Edit the subtopics, pick the report structure, drop what you did not ask for — all before a single search costs anything.",
  },
  {
    title: "Your corpus never has to leave",
    body: "Airgapped corpus mode makes zero network calls, and local models mean an unpublished manuscript stays on your machine.",
  },
] as const;

// Typed rather than `as const`: the latter narrows each entry to its own literal shape, so
// `step.gate` is a type error on the four steps that omit it.
const PIPELINE: { name: string; note: string; gate?: boolean }[] = [
  { name: "Planner", note: "decomposes the question" },
  { name: "Design gate", note: "you edit the plan", gate: true },
  { name: "Executor ⇄ Critic", note: "gathers and grades evidence" },
  { name: "Synthesizer", note: "writes the cited draft" },
  { name: "Review gate", note: "you approve the draft", gate: true },
  { name: "Finalizer", note: "report + verifiable export" },
];

export default async function Home() {
  // The Pages build has no server, no session and no app to redirect into — it is the
  // public site and nothing else, so it renders the landing page unconditionally. Checked
  // first because `cookies()` cannot be called from a statically exported route at all;
  // this is not an optimisation, it is what makes the export possible.
  if (!isPagesBuild) {
    // /research is the product's entry point: a question, and the run it becomes.
    if (!isDesktop) {
      const store = await cookies();
      if (store.has("access_token")) redirect("/research");
    } else {
      redirect("/research");
    }
  }

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-16 sm:px-6">
      <section className="max-w-3xl">
        <p className="font-mono text-[0.6875rem] uppercase tracking-widest text-text-muted">
          Self-hostable · bring your own key · runs on local models
        </p>
        {/* The project's actual name, said once and plainly. The tagline below is the
            pitch; a visitor arriving from a link still needs to know what this is called. */}
        <h1 className="mt-4 font-serif text-4xl font-bold leading-tight tracking-tight text-text-primary sm:text-5xl">
          Multi-Agent Research Assistant
        </h1>
        <p className="mt-3 font-serif text-2xl leading-snug text-text-secondary sm:text-3xl">
          Cited research you can actually verify.
        </p>
        <p className="mt-5 text-base leading-relaxed text-text-secondary">
          A multi-agent pipeline that searches, gathers evidence, and writes a
          cited report — then pauses for you twice, and exports something a
          third party can check{" "}
          <strong className="font-semibold text-text-primary">
            offline, with no AI and no network
          </strong>
          .
        </p>

        <div className="mt-8 flex flex-wrap items-center gap-3">
          {isPagesBuild ? (
            // No /login in the static export — the primary action on the public site is
            // to get the app, not to sign in to a server that is not there.
            <Link
              href="/download"
              className="flex h-10 items-center border border-accent bg-accent px-4 font-mono text-xs font-medium text-accent-contrast transition-opacity hover:opacity-90"
            >
              Get the desktop app →
            </Link>
          ) : (
            <Link
              href="/login"
              className="flex h-10 items-center border border-accent bg-accent px-4 font-mono text-xs font-medium text-accent-contrast transition-opacity hover:opacity-90"
            >
              Start researching →
            </Link>
          )}
          <Link
            href="/why"
            className="flex h-10 items-center border border-border bg-bg-surface px-4 font-mono text-xs text-text-secondary transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            Why not NotebookLM?
          </Link>
          {!isPagesBuild && (
            <Link
              href="/download"
              className="flex h-10 items-center px-2 font-mono text-xs text-text-muted transition-colors hover:text-text-primary"
            >
              Download the desktop app
            </Link>
          )}
        </div>
      </section>

      <section aria-labelledby="claims-heading" className="mt-16">
        <h2 id="claims-heading" className="sr-only">
          What this does that others do not
        </h2>
        <div className="grid gap-4 sm:grid-cols-3">
          {CLAIMS.map((claim) => (
            <div
              key={claim.title}
              className="border border-border bg-bg-surface p-5"
            >
              <h3 className="font-serif text-base font-bold text-text-primary">
                {claim.title}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-text-secondary">
                {claim.body}
              </p>
            </div>
          ))}
        </div>
      </section>

      <section aria-labelledby="pipeline-heading" className="mt-16">
        <h2
          id="pipeline-heading"
          className="font-serif text-2xl font-bold tracking-tight text-text-primary"
        >
          Two human gates, not zero
        </h2>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-secondary">
          Both are durable checkpoints, not polling loops: state is written to
          disk and the worker exits, so resuming continues rather than
          re-running research you already paid for.
        </p>
        <ol className="mt-6 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {PIPELINE.map((step, i) => (
            <li
              key={step.name}
              className={`flex items-baseline gap-3 border p-3 ${
                step.gate
                  ? "border-accent bg-bg-elevated"
                  : "border-border bg-bg-surface"
              }`}
            >
              <span className="font-mono text-[0.6875rem] text-text-muted">
                {String(i + 1).padStart(2, "0")}
              </span>
              <span className="min-w-0">
                <span className="block font-mono text-xs font-medium text-text-primary">
                  {step.gate ? `⏸ ${step.name}` : step.name}
                </span>
                <span className="block text-xs text-text-muted">
                  {step.note}
                </span>
              </span>
            </li>
          ))}
        </ol>
      </section>

      <section className="mt-16 border border-border bg-bg-surface p-6">
        <h2 className="font-serif text-xl font-bold tracking-tight text-text-primary">
          The part nobody else has
        </h2>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-secondary">
          Every report exports as a{" "}
          <code className="font-mono text-xs">.bundle.json</code> carrying its
          evidence, its sources, the models actually dialled, and the approval
          chain — hashed so that editing the report after a human approved it
          breaks the chain. A standalone verifier checks the whole thing with no
          AI, no network, and no account. Your reviewer does not have to trust
          this tool, or us.
        </p>
        <Link
          href="/why"
          className="mt-4 inline-flex font-mono text-xs text-accent transition-opacity hover:opacity-80"
        >
          See how it compares →
        </Link>
      </section>

      <section aria-labelledby="oss-heading" className="mt-16">
        <h2
          id="oss-heading"
          className="font-serif text-2xl font-bold tracking-tight text-text-primary"
        >
          Open source, and inspectable
        </h2>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-secondary">
          MIT licensed. The verification claims on this site are the kind that
          are worth nothing unless you can check them, so the source, the tests
          that hold them up, and the documentation are all public and all built
          from the same repository as this page.
        </p>
        <dl className="mt-6 grid gap-4 sm:grid-cols-3">
          {OPEN_SOURCE.map((item) => (
            <div
              key={item.term}
              className="border border-border bg-bg-surface p-4"
            >
              <dt className="font-mono text-[0.6875rem] uppercase tracking-widest text-text-muted">
                {item.term}
              </dt>
              <dd className="mt-1.5 text-sm leading-relaxed text-text-secondary">
                {item.detail}
              </dd>
            </div>
          ))}
        </dl>
        <div className="mt-6 flex flex-wrap gap-3">
          <a
            href={REPO}
            className="flex h-9 items-center border border-border bg-bg-surface px-3 font-mono text-xs text-text-secondary transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            Source on GitHub ↗
          </a>
          <a
            href={`${REPO}/blob/main/LICENSE`}
            className="flex h-9 items-center border border-border bg-bg-surface px-3 font-mono text-xs text-text-secondary transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            MIT licence ↗
          </a>
          <Link
            href="/releases"
            className="flex h-9 items-center border border-border bg-bg-surface px-3 font-mono text-xs text-text-secondary transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            Release history →
          </Link>
        </div>
      </section>
    </main>
  );
}
