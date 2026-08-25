"use client";

import Link from "next/link";
import { useState } from "react";

import { useActiveProject } from "@/components/ActiveProject";
import {
  defaultKind,
  isUnpricedRoute,
  PROVIDER_LABEL,
  ProviderPicker,
  routeForKind,
  routingFor,
  type ProviderKind,
} from "@/components/research/ProviderPicker";
import {
  useCorpusStatus,
  useCustomEndpointStatus,
  useLocalLLMStatus,
  useModelCatalog,
} from "@/hooks/queries";
import { useStartV2Research } from "@/hooks/v2";
import { ApiError } from "@/lib/api";
import type { ResearchDepth } from "@/lib/types";

/**
 * Asking the question.
 *
 * The page is the question. Everything else is a setting, and settings live behind a
 * disclosure that names its own state when closed — the pattern the V1 run form arrived at
 * after the same lesson: four decisions at equal visual weight meant asking a question
 * required first resolving three that almost never change.
 *
 * The V2 form previously had *no* settings at all: a textarea and a button, posting the
 * API's defaults. That is not simpler, it is less capable — depth, corpus mode and the
 * design gate are all real fields on `POST /v2/runs`, so the run form was the only surface
 * in the product that could not reach them.
 *
 * **Only fields the endpoint accepts appear here.** `POST /v2/runs` takes `project_id`,
 * `question`, `depth`, `corpus_mode`, `skip_plan_gate` and `model_routing`. It does not
 * take `demo`, so that is not offered — a control that posts a field the server drops is
 * worse than a missing one.
 *
 * **The model is chosen here because the alternative was choosing it invisibly.** Routing
 * lived only in Settings, and a saved preference outranks the deployment's own
 * configuration, so a machine whose `.env` routed through a gateway still ran on whatever
 * was picked once in Settings — with nothing on this page saying so. The picker shows the
 * *resolved* route even when you change nothing, which is the only version of "use my
 * settings" a person can actually consent to.
 */

/** The API accepts 1–2000. Ten is this form's own floor: a three-word question produces a
 *  plan nobody wants, and saying so before the run costs nothing. */
const MIN_QUERY = 10;
const MAX_QUERY = 2000;

const DEPTHS: { value: ResearchDepth; label: string; hint: string }[] = [
  { value: "fast", label: "Fast", hint: "A quick scan — fewer sources, lowest cost." },
  {
    value: "balanced",
    label: "Balanced",
    hint: "Solid coverage at moderate cost. Recommended for most questions.",
  },
  {
    value: "comprehensive",
    label: "Comprehensive",
    hint: "A deep dive — most sources, highest cost and longest run.",
  },
];

const SAMPLE_QUERY =
  "What are the leading approaches to long-term memory in LLM agents, and their trade-offs?";

export function StartResearchForm({
  onStarted,
  initialQuestion = "",
}: {
  onStarted: (runId: string) => void;
  /** Seeded from `?q=`, so "ask this again" from a failed run is one click and an edit. */
  initialQuestion?: string;
}) {
  const { activeId, active, isLoading: projectsLoading } = useActiveProject();
  const [question, setQuestion] = useState(initialQuestion);
  const [depth, setDepth] = useState<ResearchDepth>("balanced");
  const [corpusMode, setCorpusMode] = useState(false);
  // On by default, and sent explicitly on every run.
  //
  // `POST /v2/runs` defaults `skip_plan_gate` to `true` so that a script posting an
  // un-updated body keeps the journey it already had. The *run form* is the other of the
  // three populations AGENTS.md describes, and its default is the opposite: the design
  // gate is how the product spends nothing until a person has seen what will be searched,
  // and docs/getting-started/20-quick-start.md documents it as a step of the first run.
  // That is why this is always in the body rather than omitted when true — omitting it
  // would silently inherit the script default and quietly drop the gate.
  const [planGate, setPlanGate] = useState(true);
  const [showAdvanced, setShowAdvanced] = useState(false);
  // `null` until the probes answer, so the default lands once rather than flipping under
  // the cursor. `picked` is the user's own choice and always wins after that.
  const [picked, setPicked] = useState<ProviderKind | null>(null);

  const start = useStartV2Research();
  const corpus = useCorpusStatus(corpusMode ? activeId : null);
  const catalog = useModelCatalog();
  const customEndpoint = useCustomEndpointStatus();
  const localLLM = useLocalLLMStatus();

  // Custom endpoint first, then local, then API — whichever is actually reachable. A
  // *selection* default, resolved before the run starts and shown on the button; nothing
  // switches provider mid-run.
  const kind = picked ?? defaultKind(catalog.data, customEndpoint.data, localLLM.data);
  const chosenRoute = kind
    ? routeForKind(kind, catalog.data, customEndpoint.data, localLLM.data)
    : null;

  const trimmed = question.trim();
  const tooShort = trimmed.length > 0 && trimmed.length < MIN_QUERY;
  const noProject = !projectsLoading && !activeId;
  const canSubmit =
    trimmed.length >= MIN_QUERY && trimmed.length <= MAX_QUERY && Boolean(activeId) && !start.isPending;

  // What the closed disclosure reports: departures from the default, never the default
  // itself. Silent non-default state is worse than clutter, and a badge for something
  // that is simply on reads as a warning.
  const overrides = [
    corpusMode ? "Corpus only" : null,
    planGate ? null : "No plan review",
    // A chosen model is a departure from the default and has to survive the disclosure
    // being closed — the whole point of this control is that routing stops being silent.
    kind && kind !== "custom" ? PROVIDER_LABEL[kind] : null,
  ].filter(Boolean);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    run();
  };

  const run = () => {
    // Guards the Enter key and a double click alike: `isPending` is folded into
    // `canSubmit`, so a second submit while the first is in flight does nothing.
    if (!canSubmit || !activeId) return;
    start.mutate(
      {
        project_id: activeId,
        question: trimmed,
        depth,
        corpus_mode: corpusMode,
        skip_plan_gate: !planGate,
        // Omitted, not null, when nothing was chosen: the field's absence is what means
        // "resolve it from my settings", and sending an empty map would fail validation
        // for missing roles.
        // Sent whenever a backend resolved to a real route, so the run records the models
        // it was started on rather than re-resolving them later from settings that may
        // have changed. Omitted only when nothing is configured at all.
        ...(chosenRoute ? { model_routing: routingFor(chosenRoute) } : {}),
      },
      { onSuccess: (r) => onStarted(r.run_id) },
    );
  };

  return (
    <form onSubmit={submit} className="card space-y-5" aria-describedby="start-context">
      <div>
        <label htmlFor="question" className="text-[0.8125rem] font-medium text-text-secondary">
          Research question
        </label>
        <textarea
          id="question"
          rows={4}
          value={question}
          onChange={(e) => setQuestion(e.target.value.slice(0, MAX_QUERY))}
          placeholder={`e.g. ${SAMPLE_QUERY}`}
          className="textarea-base mt-1.5 w-full resize-y font-serif text-base leading-relaxed"
          aria-describedby="query-counter"
          aria-invalid={tooShort || undefined}
          disabled={start.isPending}
        />
        <div id="query-counter" className="mt-1 flex justify-between font-mono text-xs">
          <span style={{ color: tooShort ? "var(--warning)" : "var(--text-muted)" }}>
            {tooShort ? `At least ${MIN_QUERY} characters` : " "}
          </span>
          <span className="tabular-nums text-text-muted">
            {trimmed.length} / {MAX_QUERY}
          </span>
        </div>
        {question.length === 0 && (
          <button
            type="button"
            onClick={() => setQuestion(SAMPLE_QUERY)}
            className="text-xs text-accent hover:underline"
          >
            Use a sample question
          </button>
        )}
      </div>

      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="order-2 flex flex-col gap-2 sm:order-1">
          <button type="submit" disabled={!canSubmit} className="btn btn-primary self-start">
            {start.isPending && <span className="spinner" />}
            {start.isPending ? "Starting…" : "Start research"}
          </button>
          {/* A disabled button with no reason is the worst state a first-run user can meet:
              it looks broken rather than blocked. Say which of the two it is. */}
          <p id="start-context" className="max-w-sm text-xs leading-snug text-text-muted">
            {projectsLoading
              ? "Loading your projects…"
              : noProject
                ? "Create a project first — research is always scoped to one."
                : start.isPending
                  ? "Opening the run. You will land on its workspace."
                  : planGate
                    ? `Saved to ${active?.name}. The run pauses for your plan review before searching, and again for your report review.`
                    : `Saved to ${active?.name}. The run pauses for your review before anything is finalised.`}
          </p>
          {/* The models this run will actually use, stated before it starts and whether or
              not anything was chosen. Routing resolves user → deployment behind the
              scenes, and until it was shown here the first place it became visible was the
              finished report's attribution — after the run had already spent. */}
          <p className="max-w-sm font-mono text-[length:var(--text-micro)] text-text-muted">
            {kind === null ? (
              "Models: resolving…"
            ) : (
              <>
                Models:{" "}
                <span className="text-text-secondary">
                  {chosenRoute ?? `${PROVIDER_LABEL[kind]} — not configured`}
                </span>
                {isUnpricedRoute(chosenRoute) && (
                  // The cap is computed from catalog prices, which this provider has none
                  // of, so a run on it reports $0.00 whatever it cost. Said here rather
                  // than left for the run to display an unmeasured zero as a total.
                  <span className="block text-text-muted">
                    Cost is not measurable for this provider — cap spend at the provider.
                  </span>
                )}
              </>
            )}
          </p>
        </div>

        <div className="order-1 flex flex-col gap-2 sm:order-2 sm:items-end">
          {/* Real radios in a fieldset, so arrow keys and screen readers work. */}
          <fieldset className="flex items-center gap-2.5">
            <legend className="sr-only">Research depth</legend>
            <span
              aria-hidden
              className="font-mono text-[length:var(--text-micro)] uppercase tracking-wider text-text-muted"
            >
              Depth
            </span>
            <div className="inline-flex border border-border">
              {DEPTHS.map((d) => {
                const selected = depth === d.value;
                return (
                  <label
                    key={d.value}
                    className="cursor-pointer border-r border-border px-2.5 py-1 text-xs font-medium transition-colors last:border-r-0"
                    style={{
                      backgroundColor: selected ? "var(--accent-muted)" : "var(--bg-surface)",
                      color: selected ? "var(--accent)" : "var(--text-secondary)",
                    }}
                  >
                    <input
                      type="radio"
                      name="depth"
                      value={d.value}
                      checked={selected}
                      onChange={() => setDepth(d.value)}
                      className="sr-only"
                      disabled={start.isPending}
                    />
                    {d.label}
                  </label>
                );
              })}
            </div>
          </fieldset>

          <p className="max-w-xs text-xs leading-snug text-text-muted sm:text-right">
            {DEPTHS.find((d) => d.value === depth)?.hint}
          </p>

          <button
            type="button"
            onClick={() => setShowAdvanced((v) => !v)}
            aria-expanded={showAdvanced}
            aria-controls="run-options"
            className="flex items-center gap-1.5 font-mono text-xs text-text-muted transition-colors hover:text-text-primary"
          >
            <span aria-hidden className="inline-block w-2 text-center">
              {showAdvanced ? "▾" : "▸"}
            </span>
            <span className="uppercase tracking-wider">Options</span>
            {/* Closed state still names what the run will do, so nothing is hidden. */}
            {!showAdvanced &&
              (overrides.length > 0 ? (
                <span className="font-semibold text-accent">{overrides.join(" · ")}</span>
              ) : (
                <span>Web search · plan and report review</span>
              ))}
          </button>
        </div>
      </div>

      {showAdvanced && (
        <div id="run-options" className="space-y-3 border-t border-border pt-5">
          <ProviderPicker
            value={kind ?? "custom"}
            onChange={setPicked}
            disabled={start.isPending}
          />

          <label className="flex cursor-pointer items-start gap-3 border border-border bg-bg-surface p-3">
            <input
              type="checkbox"
              checked={corpusMode}
              onChange={(e) => setCorpusMode(e.target.checked)}
              className="mt-0.5 h-4 w-4 shrink-0 border-border accent-[var(--accent)]"
              disabled={start.isPending}
            />
            <span>
              <span className="block text-sm font-medium text-text-primary">
                Restrict to uploaded corpus
              </span>
              <span className="block text-xs leading-relaxed text-text-muted">
                No web search. Evidence comes only from this project&apos;s documents.
              </span>
              {/* Checked against the project's real corpus, not assumed: a corpus-only run
                  over an empty corpus produces a report with nothing behind it, and the
                  time to learn that is before the run, not after. */}
              {corpusMode && corpus.data && corpus.data.documents === 0 && (
                <span className="mt-1 block text-xs" style={{ color: "var(--warning)" }}>
                  This project has no documents yet.{" "}
                  <Link href="/corpus" className="underline">
                    Upload some
                  </Link>{" "}
                  or the run will have nothing to read.
                </span>
              )}
              {corpusMode && corpus.data && corpus.data.documents > 0 && (
                <span className="mt-1 block text-xs text-text-secondary">
                  {corpus.data.documents} document
                  {corpus.data.documents === 1 ? "" : "s"} available.
                </span>
              )}
            </span>
          </label>

          <label className="flex cursor-pointer items-start gap-3 border border-border bg-bg-surface p-3">
            <input
              type="checkbox"
              checked={planGate}
              onChange={(e) => setPlanGate(e.target.checked)}
              className="mt-0.5 h-4 w-4 shrink-0 border-border accent-[var(--accent)]"
              disabled={start.isPending}
            />
            <span>
              <span className="block text-sm font-medium text-text-primary">
                Review the research plan before searching
              </span>
              <span className="block text-xs leading-relaxed text-text-muted">
                The run pauses after the planner so you can see the subtopics it chose and
                drop the ones you did not ask for. Nothing is spent until you approve them.
                Turning this off starts searching immediately.
              </span>
            </span>
          </label>
        </div>
      )}

      {start.isError && (
        <div
          className="border p-3 text-xs leading-relaxed"
          role="alert"
          style={{
            color: "var(--danger)",
            backgroundColor: "var(--danger-soft)",
            borderColor: "var(--danger-line)",
          }}
        >
          <p className="font-medium">Research couldn&apos;t be started.</p>
          <p className="mt-1">
            {start.error instanceof ApiError
              ? start.error.message
              : "The request failed before it reached the server. Check your connection."}
          </p>
          <button type="button" className="btn btn-secondary mt-2" disabled={!canSubmit} onClick={run}>
            Try again
          </button>
        </div>
      )}
    </form>
  );
}
