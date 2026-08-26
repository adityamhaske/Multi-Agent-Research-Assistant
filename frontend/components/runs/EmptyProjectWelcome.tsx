"use client";

import Link from "next/link";

/**
 * A brand-new project has no runs, no corpus and — necessarily — no memory. Showing
 * Attention, Active Research and Project Health as three stacked empty panels would be
 * exactly the "large empty panels" problem the redesign brief calls out, for a reader who
 * needs one clear next step more than three separate confirmations that nothing exists
 * yet. `page.tsx` renders this in their place, not alongside them.
 *
 * Two CTAs, not one: a run works with no corpus at all (web search is the default path),
 * and uploading source material is worthwhile before a single question is asked — so this
 * does not pick a path for the reader.
 */
export function EmptyProjectWelcome({ projectName }: { projectName: string }) {
  return (
    <section aria-labelledby="empty-project" className="card py-10 text-center">
      <h2
        id="empty-project"
        className="font-serif text-xl font-bold tracking-tight text-text-primary"
      >
        {projectName} is ready for its first research
      </h2>
      {/* "Nothing active here" rather than "nothing has ever been asked": the emptiness
          check reads the *unarchived* session list, and archiving is explicitly recoverable
          rather than deletion — so a user who archived an old project's sessions would be
          told their work never happened. */}
      <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-text-secondary">
        There&apos;s no active research or source material here. Start with a question, add
        material for it to draw on, or both — neither has to come first.
      </p>
      <div className="mt-5 flex flex-wrap items-center justify-center gap-3">
        <Link href="/research" className="btn btn-primary">
          Start research
        </Link>
        <Link href="/corpus" className="btn btn-secondary">
          Add corpus material
        </Link>
      </div>
    </section>
  );
}
