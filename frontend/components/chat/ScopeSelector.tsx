"use client";

import type { ChatScope } from "@/lib/types";

/**
 * What a follow-up question may read (docs/07 §2, Phase 5; req 8).
 *
 * Each option names what it reads **and** what it will not touch. That second half is
 * load-bearing rather than tidy copy: a control that only advertised what it includes
 * would let "Web" quietly also read the corpus without the label ever becoming false.
 *
 * The corpus wording is deliberately "no web search" rather than "no network calls".
 * Corpus scope guarantees no *retrieval* egress — nothing is searched, and the backend
 * refuses to embed the question at all if the configured embedder is remote — but the
 * answer is still written by a model, which is off-machine unless chat is routed to a
 * local one. Claiming more than that here is exactly the kind of unverifiable statement
 * this product exists to refuse.
 */

type Option = { value: ChatScope; label: string; detail: string };

const OPTIONS: Option[] = [
  {
    value: "report",
    label: "This report",
    detail: "The finished report and the sources it already cites. No new search.",
  },
  {
    value: "corpus",
    label: "My corpus",
    detail:
      "Only documents you uploaded to this project. No web search, and your question is never embedded off this machine.",
  },
  {
    value: "web",
    label: "Web",
    detail: "A live search, returning sources the report didn't have. No uploaded documents.",
  },
  {
    value: "everything",
    label: "Everything",
    detail: "Finished research, your uploaded documents, and a live web search.",
  },
];

/** The project chat has no single report — its finished research is the whole project. */
const PROJECT_LABELS: Partial<Record<ChatScope, Pick<Option, "label" | "detail">>> = {
  report: {
    label: "My research",
    detail: "Reports you've approved in this project. No new search.",
  },
};

export function ScopeSelector({
  value,
  onChange,
  surface = "report",
  disabled,
}: {
  value: ChatScope;
  onChange: (scope: ChatScope) => void;
  /** Which chat this is mounted on — only the wording of the first option differs. */
  surface?: "report" | "project";
  disabled?: boolean;
}) {
  const active = OPTIONS.find((o) => o.value === value) ?? OPTIONS[0];
  const activeCopy = (surface === "project" ? PROJECT_LABELS[active.value] : undefined) ?? active;

  return (
    <div className="space-y-1.5">
      <div
        role="radiogroup"
        aria-label="What this question may read"
        className="flex flex-wrap gap-1"
      >
        {OPTIONS.map((option) => {
          const copy =
            (surface === "project" ? PROJECT_LABELS[option.value] : undefined) ?? option;
          const selected = option.value === value;
          return (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={selected}
              disabled={disabled}
              onClick={() => onChange(option.value)}
              title={copy.detail}
              className="border px-2.5 py-1 font-mono text-[0.6875rem] uppercase tracking-wider transition-colors disabled:cursor-not-allowed disabled:opacity-50"
              style={{
                borderColor: selected ? "var(--accent)" : "var(--border)",
                color: selected ? "var(--accent)" : "var(--text-muted)",
                backgroundColor: selected
                  ? "color-mix(in srgb, var(--accent) 10%, var(--bg-surface))"
                  : "var(--bg-surface)",
              }}
            >
              {copy.label}
            </button>
          );
        })}
      </div>
      {/* Always rendered, not a tooltip only: the promise has to be readable without a
          pointer, and on a phone there is no hover at all. */}
      <p className="text-xs leading-snug text-text-muted">{activeCopy.detail}</p>
    </div>
  );
}
