"use client";

import { useCallback, useMemo, useRef, useState } from "react";

import { useV2Cancel } from "@/hooks/runs";
import type { RunGraph } from "@/lib/types";
import { isTab, type Tab } from "@/lib/runTabs";

import { ArtifactPanel } from "./panels/ArtifactPanel";
import { ClaimsPanel } from "./panels/ClaimsPanel";
import { ContradictionsPanel } from "./panels/ContradictionsPanel";
import { EvidencePanel } from "./panels/EvidencePanel";
import { PlanPanel } from "./panels/PlanPanel";
import { ReportPanel } from "./panels/ReportPanel";
import { ReviewPanel } from "./panels/ReviewPanel";
import { SourcesPanel } from "./panels/SourcesPanel";
import { runTotals } from "./primitives";

/**
 * The research workspace.
 *
 * The tab order *is* the argument the product makes: a report is the end of a chain, not the
 * whole of it.
 *
 *     Plan → Report → Claims → Evidence → Sources → Contradictions → Review → Artifact
 *
 * Every tab reads the same `RunGraph`, so the counts on one cannot disagree with the rows
 * on another, and moving claim → evidence → source is a filter rather than a fetch.
 *
 * Three distinctions the layout refuses to blur, because they are the product:
 * retrieved ≠ verified, retrieved ≠ cited, and a citation marker ≠ evidence.
 *
 * The tablist follows the ARIA pattern properly: one tab stop for the whole strip, arrow
 * keys to move, `aria-controls` to the panel, and the panel focusable so keyboard focus
 * lands somewhere after a switch. It previously had `role="tab"` and nothing else, which is
 * the shape that looks right in a screenshot and traps a keyboard user in the strip.
 */

export function RunWorkspace({
  graph,
  initialTab,
  onTabChange,
}: {
  graph: RunGraph;
  /** Deep link from the URL, honoured once on mount. */
  initialTab?: Tab | null;
  /** Called when a *person* picks a tab, so the page can put it in the URL. Not called
   *  for the automatic re-route below: reaching a gate should move the view, not rewrite
   *  the reader's history. */
  onTabChange?: (tab: Tab) => void;
}) {
  const totals = useMemo(() => runTotals(graph), [graph]);

  // The tab a run's current state demands, or null when nothing is waiting on a person.
  const demanded: Tab | null = graph.artifact
    ? "artifact"
    : graph.run.status === "AWAITING_REVIEW"
      ? "review"
      : graph.run.status === "AWAITING_PLAN"
        ? "plan"
        : null;

  // A deep link wins on first paint — someone following a link to the Evidence tab meant
  // it — but a run parked at a gate still overrides on the *transition* below.
  const [tab, setTab] = useState<Tab>(initialTab ?? demanded ?? "report");

  // Re-route when the run REACHES a gate, not only when the page is first opened.
  //
  // Found by the end-to-end journey: a run watched from RUNNING through to
  // AWAITING_REVIEW left the reviewer on the Report tab with the decision hidden behind
  // another one, because the opening tab was computed once by `useState`. Written as
  // setState-during-render keyed on the demanded tab — the codebase's "reset state when a
  // prop changes" pattern — rather than an effect, so the correct tab is painted in the
  // same commit as the new status instead of one frame later.
  const [lastDemanded, setLastDemanded] = useState<Tab | null>(demanded);
  if (demanded !== lastDemanded) {
    setLastDemanded(demanded);
    if (demanded) setTab(demanded);
  }

  // Cross-tab focus: following a claim to its evidence, or evidence to its source, is a
  // filter on data already loaded. Both are cleared explicitly rather than left to linger,
  // because a silently filtered ledger is how a reader miscounts a run.
  const [focusClaim, setFocusClaim] = useState<string | null>(null);
  const [focusSource, setFocusSource] = useState<string | null>(null);

  const panelRef = useRef<HTMLDivElement>(null);
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  const select = useCallback(
    (next: Tab, fromUser = true) => {
      setTab(next);
      if (fromUser) onTabChange?.(next);
    },
    [onTabChange],
  );

  /** Moving to another tab programmatically must not leave a stale filter behind. */
  const go = useCallback(
    (next: Tab, opts?: { claim?: string | null; source?: string | null }) => {
      if (opts && "claim" in opts) setFocusClaim(opts.claim ?? null);
      if (opts && "source" in opts) setFocusSource(opts.source ?? null);
      select(next);
    },
    [select],
  );

  const tabs: { id: Tab; label: string; count?: number | null }[] = [
    ...(graph.plans.length > 0 ? [{ id: "plan" as const, label: "Plan" }] : []),
    { id: "report", label: "Report" },
    { id: "claims", label: "Claims", count: totals.claims.length },
    { id: "evidence", label: "Evidence", count: totals.evidence },
    { id: "sources", label: "Sources", count: totals.sources },
    { id: "contradictions", label: "Contradictions", count: totals.contradictions },
    { id: "review", label: "Review" },
    { id: "artifact", label: "Artifact" },
  ];

  // The demanded tab may not be in the strip (a run with no plan rows never shows Plan),
  // so the rendered selection is clamped to what exists.
  const active = tabs.some((t) => t.id === tab) ? tab : "report";

  const onKeyDown = (e: React.KeyboardEvent) => {
    const i = tabs.findIndex((t) => t.id === active);
    let next = -1;
    if (e.key === "ArrowRight") next = (i + 1) % tabs.length;
    else if (e.key === "ArrowLeft") next = (i - 1 + tabs.length) % tabs.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = tabs.length - 1;
    if (next === -1) return;
    e.preventDefault();
    const id = tabs[next]!.id;
    select(id);
    tabRefs.current[id]?.focus();
  };

  return (
    <div className="space-y-4">
      {/* Overflows horizontally rather than wrapping into three rows on a phone: eight
          labels with counts do not fit, and a wrapped tab strip stops reading as one
          control. */}
      <div className="-mx-1 overflow-x-auto px-1">
        <div
          role="tablist"
          aria-label="Research run"
          onKeyDown={onKeyDown}
          className="flex min-w-max gap-1 border-b border-border"
        >
          {tabs.map((t) => {
            const selected = active === t.id;
            return (
              <button
                key={t.id}
                ref={(el) => {
                  tabRefs.current[t.id] = el;
                }}
                id={`run-tab-${t.id}`}
                type="button"
                role="tab"
                aria-selected={selected}
                aria-controls={`run-panel-${t.id}`}
                tabIndex={selected ? 0 : -1}
                onClick={() => select(t.id)}
                className={`-mb-px shrink-0 border-b-2 px-3 py-2 text-[0.8125rem] font-medium transition-colors ${
                  selected
                    ? "border-accent text-accent"
                    : "border-transparent text-text-secondary hover:text-text-primary"
                }`}
              >
                {t.label}
                {t.count !== undefined && t.count !== null && (
                  <span className="ml-1.5 tabular-nums text-text-muted">{t.count}</span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      <div
        ref={panelRef}
        role="tabpanel"
        id={`run-panel-${active}`}
        aria-labelledby={`run-tab-${active}`}
        tabIndex={0}
        className="focus:outline-none"
      >
        {active === "plan" && <PlanPanel graph={graph} />}
        {active === "report" && <ReportPanel graph={graph} />}
        {active === "claims" && (
          <ClaimsPanel
            graph={graph}
            onInspectEvidence={(claimId) => go("evidence", { claim: claimId })}
            onInspectSource={(sourceId) => go("sources", { source: sourceId })}
          />
        )}
        {active === "evidence" && (
          <EvidencePanel
            graph={graph}
            focusClaim={focusClaim}
            onClearFocus={() => setFocusClaim(null)}
            onInspectSource={(sourceId) => go("sources", { source: sourceId })}
          />
        )}
        {active === "sources" && (
          <SourcesPanel
            graph={graph}
            focus={focusSource}
            onInspectEvidence={(sourceId) => {
              // Evidence filters by claim, not by source; jumping there with a stale claim
              // filter would show a subset that has nothing to do with the source clicked.
              setFocusClaim(null);
              setFocusSource(sourceId);
              select("evidence");
            }}
          />
        )}
        {active === "contradictions" && <ContradictionsPanel graph={graph} />}
        {active === "review" && (
          <ReviewPanel graph={graph} onShowTab={(t) => isTab(t) && select(t)} />
        )}
        {active === "artifact" && <ArtifactPanel graph={graph} />}
      </div>
    </div>
  );
}

/* ── Cancel ─────────────────────────────────────────────────────────────────── */

/**
 * Stopping a run.
 *
 * The copy is careful because the mechanism is: cancel is **advisory** on both hosts —
 * neither outcome writer checks status before persisting — so a button labelled "Cancel"
 * would promise something the backend does not do. The server's own `detail` is preferred
 * over this page's wording whenever it answers.
 */
export function CancelButton({ runId }: { runId: string }) {
  const cancel = useV2Cancel(runId);
  const [confirming, setConfirming] = useState(false);

  if (cancel.isSuccess) {
    return (
      <p className="max-w-xs text-xs text-text-secondary">
        {cancel.data?.detail ?? "Stop requested."}
      </p>
    );
  }

  return (
    <div className="text-right">
      {confirming ? (
        <div className="flex flex-wrap items-center justify-end gap-2">
          <button
            type="button"
            className="btn btn-danger"
            disabled={cancel.isPending}
            onClick={() => cancel.mutate()}
          >
            {cancel.isPending && <span className="spinner" />}
            Confirm stop
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            disabled={cancel.isPending}
            onClick={() => setConfirming(false)}
          >
            Keep running
          </button>
        </div>
      ) : (
        <button type="button" className="btn btn-secondary" onClick={() => setConfirming(true)}>
          Stop run
        </button>
      )}
      <p className="mt-1 max-w-xs text-[length:var(--text-micro)] leading-snug text-text-muted">
        Records a stop request. Work already in flight finishes its current step — this does
        not kill the run mid-sentence.
      </p>
      {cancel.isError && (
        <p className="mt-1 text-xs text-danger" role="alert">
          {(cancel.error as Error).message}
        </p>
      )}
    </div>
  );
}
