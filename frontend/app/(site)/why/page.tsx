import Link from "next/link";

import {
  AS_OF,
  AUDIENCES,
  COMPETITORS,
  LOSSES,
  MECHANISMS,
  ROWS,
  type Support,
} from "@/lib/comparison";

/**
 * Why this over NotebookLM (docs/01 §0).
 *
 * The page leads with the caveat and ends with the losses, on purpose. A comparison table
 * written by the thing being compared is worth very little unless it is visibly willing to
 * lose rows, so the rows this product loses are in the same table as the rows it wins,
 * and "use something else" is a verdict the audience section is allowed to reach.
 */

export const metadata = {
  title: "Why this over NotebookLM · Research Assistant",
  description:
    "How this differs from NotebookLM, Scholar, Perplexity and Elicit — what it does that " +
    "they cannot, what they do better, and who should use which.",
};

const SUPPORT_MARK: Record<
  Support,
  { glyph: string; label: string; token: string }
> = {
  // Red/green, at a size you can read across a wide row — but the glyph differs too, and
  // an accessible label is always present. Roughly one reader in twelve cannot separate
  // these two hues, and this table's whole job is being scannable, so colour reinforces
  // the shape rather than carrying the meaning alone.
  yes: { glyph: "●", label: "yes", token: "var(--success)" },
  partial: { glyph: "◐", label: "partial", token: "var(--warning)" },
  no: { glyph: "○", label: "no", token: "var(--danger)" },
  na: { glyph: "–", label: "not applicable", token: "var(--text-muted)" },
};

function Mark({ value }: { value: Support }) {
  const mark = SUPPORT_MARK[value];
  return (
    <span
      className="font-mono text-xl leading-none"
      style={{ color: mark.token }}
    >
      <span aria-hidden>{mark.glyph}</span>
      <span className="sr-only">{mark.label}</span>
    </span>
  );
}

/** Spelled out once above the table, so the glyphs do not have to be guessed at. */
function MarkLegend() {
  return (
    <ul className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2">
      {(["yes", "partial", "no", "na"] as Support[]).map((value) => (
        <li key={value} className="flex items-center gap-1.5">
          <Mark value={value} />
          <span className="font-mono text-[0.6875rem] uppercase tracking-widest text-text-muted">
            {SUPPORT_MARK[value].label}
          </span>
        </li>
      ))}
    </ul>
  );
}

export default function WhyPage() {
  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-12 sm:px-6">
      <header className="max-w-3xl">
        <p className="font-mono text-[0.6875rem] uppercase tracking-widest text-text-muted">
          Positioning
        </p>
        <h1 className="mt-3 font-serif text-3xl font-bold tracking-tight text-text-primary sm:text-4xl">
          Why this over NotebookLM?
        </h1>
        <p className="mt-5 text-base leading-relaxed text-text-secondary">
          Everything here helps you read faster. This is the only one that
          produces a synthesis a third party can check{" "}
          <strong className="font-semibold text-text-primary">
            offline, without trusting us, without an AI, and without a network
            connection
          </strong>
          .
        </p>
        <p
          role="note"
          className="mt-6 border-l-2 border-border bg-bg-surface p-4 text-xs leading-relaxed text-text-muted"
        >
          <strong className="font-semibold text-text-secondary">
            On the other columns.
          </strong>{" "}
          These products move fast and this is a best-understanding snapshot as
          of {AS_OF}, not audited fact. The claims in this project&rsquo;s own
          column were verified against the source; the rest is worth re-checking
          before you rely on it.
        </p>
      </header>

      {/* Wide table: readable comparison, but only where there is room for six columns. */}
      <section aria-labelledby="table-heading" className="mt-12">
        <h2
          id="table-heading"
          className="font-serif text-2xl font-bold tracking-tight text-text-primary"
        >
          Feature by feature
        </h2>
        <MarkLegend />

        <div className="mt-6 hidden overflow-x-auto lg:block">
          <table className="w-full border-collapse text-left">
            <caption className="sr-only">
              Capability comparison across Research Assistant, NotebookLM,
              Google Scholar, Perplexity and Elicit
            </caption>
            <thead>
              <tr className="border-b border-border">
                <th
                  scope="col"
                  className="py-2 pr-4 font-mono text-[0.6875rem] uppercase tracking-widest text-text-muted"
                >
                  Capability
                </th>
                <th
                  scope="col"
                  className="px-3 py-2 font-mono text-[0.6875rem] uppercase tracking-widest text-text-primary"
                >
                  This
                </th>
                {COMPETITORS.map((c) => (
                  <th
                    key={c.key}
                    scope="col"
                    className="px-3 py-2 font-mono text-[0.6875rem] uppercase tracking-widest text-text-muted"
                  >
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ROWS.map((row) => (
                <tr key={row.dimension} className="border-b border-border/60">
                  <th
                    scope="row"
                    className="max-w-xs py-3 pr-4 align-top font-normal"
                  >
                    <span className="block text-sm text-text-primary">
                      {row.dimension}
                    </span>
                    {row.note && (
                      <span className="mt-0.5 block text-xs text-text-muted">
                        {row.note}
                      </span>
                    )}
                  </th>
                  <td className="px-3 py-3 align-top">
                    <Mark value={row.ours} />
                  </td>
                  {COMPETITORS.map((c) => (
                    <td key={c.key} className="px-3 py-3 align-top">
                      <Mark value={row[c.key]} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Narrow: stacked cards. A six-column table at 375px hides the columns that carry
            the argument behind a horizontal scrollbar nobody finds. */}
        <div className="mt-6 space-y-3 lg:hidden">
          {ROWS.map((row) => (
            <div
              key={row.dimension}
              className="border border-border bg-bg-surface p-4"
            >
              <p className="text-sm font-medium text-text-primary">
                {row.dimension}
              </p>
              {row.note && (
                <p className="mt-1 text-xs text-text-muted">{row.note}</p>
              )}
              <dl className="mt-3 flex flex-wrap gap-x-4 gap-y-1">
                <div className="flex items-center gap-1.5">
                  <dt className="font-mono text-[0.6875rem] text-text-primary">
                    This
                  </dt>
                  <dd>
                    <Mark value={row.ours} />
                  </dd>
                </div>
                {COMPETITORS.map((c) => (
                  <div key={c.key} className="flex items-center gap-1.5">
                    <dt className="font-mono text-[0.6875rem] text-text-muted">
                      {c.label}
                    </dt>
                    <dd>
                      <Mark value={row[c.key]} />
                    </dd>
                  </div>
                ))}
              </dl>
            </div>
          ))}
        </div>
      </section>

      <section aria-labelledby="how-heading" className="mt-16">
        <h2
          id="how-heading"
          className="font-serif text-2xl font-bold tracking-tight text-text-primary"
        >
          The three claims nobody else makes — and how they are built
        </h2>
        <div className="mt-6 space-y-4">
          {MECHANISMS.map((m, i) => (
            <article
              key={m.claim}
              className="border border-border bg-bg-surface p-5"
            >
              <h3 className="font-serif text-lg font-bold text-text-primary">
                <span className="mr-2 font-mono text-xs text-text-muted">
                  {String(i + 1).padStart(2, "0")}
                </span>
                {m.claim}
              </h3>
              <p className="mt-3 text-sm leading-relaxed text-text-secondary">
                <span className="font-mono text-[0.6875rem] uppercase tracking-widest text-text-muted">
                  How{" "}
                </span>
                {m.how}
              </p>
              <p className="mt-3 text-sm leading-relaxed text-text-secondary">
                <span className="font-mono text-[0.6875rem] uppercase tracking-widest text-text-muted">
                  Why it matters{" "}
                </span>
                {m.why}
              </p>
              <p className="mt-3 font-mono text-[0.6875rem] text-text-muted">
                {m.source}
              </p>
            </article>
          ))}
        </div>
      </section>

      <section aria-labelledby="who-heading" className="mt-16">
        <h2
          id="who-heading"
          className="font-serif text-2xl font-bold tracking-tight text-text-primary"
        >
          Who should actually use this
        </h2>
        <ul className="mt-6 space-y-2">
          {AUDIENCES.map((a) => (
            <li
              key={a.who}
              className="flex flex-col gap-1 border border-border bg-bg-surface p-4 sm:flex-row sm:items-baseline sm:gap-4"
            >
              <span className="min-w-0 flex-1 text-sm text-text-primary">
                {a.who}
              </span>
              <span
                className={`font-mono text-xs font-medium ${
                  a.elsewhere ? "text-text-muted" : "text-accent"
                }`}
              >
                {a.verdict}
              </span>
              <span className="min-w-0 flex-1 text-xs text-text-muted">
                {a.why}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="losses-heading" className="mt-16">
        <h2
          id="losses-heading"
          className="font-serif text-2xl font-bold tracking-tight text-text-primary"
        >
          Where it honestly loses
        </h2>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-secondary">
          A comparison written by the thing being compared is worth nothing
          unless it is willing to lose. These are the reasons to pick something
          else.
        </p>
        <ul className="mt-6 space-y-2">
          {LOSSES.map((loss) => (
            <li
              key={loss}
              className="border-l-2 border-border bg-bg-surface p-4 text-sm leading-relaxed text-text-secondary"
            >
              {loss}
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-16 border border-border bg-bg-surface p-6">
        <h2 className="font-serif text-xl font-bold tracking-tight text-text-primary">
          Read further
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-text-secondary">
          The documentation describes what is built, not what is planned —
          including the agent design, the local-first architecture, and the
          security model.
        </p>
        <div className="mt-4 flex flex-wrap gap-3">
          <Link
            href="/docs"
            className="flex h-9 items-center border border-border bg-bg-base px-3 font-mono text-xs text-text-secondary transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            Documentation →
          </Link>
          <Link
            href="/download"
            className="flex h-9 items-center border border-border bg-bg-base px-3 font-mono text-xs text-text-secondary transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            Download →
          </Link>
        </div>
      </section>
    </main>
  );
}
