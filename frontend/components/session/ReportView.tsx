"use client";

import { useState } from "react";
import toast from "react-hot-toast";

import { ApiError } from "@/lib/api";
import { Report, SourcesPanel } from "@/lib/citations";
import { downloadExport } from "@/lib/download";
import { formatCost, formatDuration, formatNumber } from "@/lib/format";
import type { SessionDetail } from "@/lib/types";

import { PreviewDrawer } from "@/components/preview/PreviewDrawer";
import { documentUrl } from "@/components/preview/DocumentPreview";
import { Disclosure } from "@/components/ui/Disclosure";

import { ChatPanel } from "./ChatPanel";
import { ModelAttribution } from "./ModelAttribution";

/**
 * The three export routes, as their URL suffixes.
 *
 * `bundle.json` is the hash-verifiable artifact (docs/reference/15-bundle-format.md) —
 * report, evidence with per-snippet hashes, sources, contradictions, model routing and the
 * approval chain, checkable offline by `research_engine.verify_bundle` with no AI, no
 * network and no account.
 *
 * It has existed as an endpoint since v1.0.0 and had no control anywhere in the app: the
 * landing page, the login page, the settings copy and the comparison table all sold it
 * while the only way to obtain one was to construct the URL by hand.
 */
type ExportFormat = "md" | "pdf" | "bundle.json";

/**
 * The verifier invocation, as a reader would actually run it.
 *
 * Kept verbatim rather than assembled from parts: this is a command someone copies into a
 * shell, and `docs/user-guide/29-exports.md` prints the same one. If the module path moves,
 * both change — `python -m research_engine.verify_bundle` is the module's own documented
 * entry point (see its `__main__` block), not a wrapper we invented here.
 */
const VERIFY_COMMAND = "python -m research_engine.verify_bundle research-xxxxxxxx.bundle.json";

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="font-mono text-[0.6875rem] font-semibold uppercase tracking-wider text-text-muted">{label}</div>
      <div className="font-mono text-sm font-medium text-text-primary tabular-nums mt-0.5">{value}</div>
    </div>
  );
}

export function ReportView({ session }: { session: SessionDetail }) {
  const report = session.final_report ?? session.draft_report ?? "";
  const sources = session.sources ?? [];
  const tokens = session.total_tokens_input + session.total_tokens_output;
  const [exporting, setExporting] = useState<null | ExportFormat>(null);
  // A corpus citation resolves to a document in this session's project, so clicking [3]
  // can show the page rather than downloading it (docs/07 §2, Phase 6). Web citations
  // keep their ordinary link — there is no local file to preview.
  const [preview, setPreview] = useState<{ id: string; filename: string; page: number | null } | null>(
    null,
  );

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(report);
      toast.success("Report copied to clipboard.");
    } catch {
      toast.error("Couldn't access the clipboard.");
    }
  };

  // Server-rendered export (docs/05 §3, docs/07 §3): .md is the raw report; .pdf is
  // WeasyPrint; .bundle.json is the hash-verifiable artifact. A 501 (PDF libs missing) or
  // 400 (bundle requires a COMPLETED session) surfaces as a toast rather than a broken
  // download.
  //
  // Routed through `downloadExport`, which is the *only* place that knows how to reach the
  // API on both hosts. This function used to build its own `fetch` with a hardcoded
  // `/api/v1` path and `credentials: "include"`, which is a web-only request in all three
  // respects: the packaged desktop app talks to a sidecar on another origin and
  // authenticates with a per-launch bearer token, so every export control in the packaged
  // app failed with "Network error during export." The newer export UIs already went
  // through the helper — this was the forgotten copy, which is the failure mode
  // AGENTS.md names as the recurring one.
  //
  // The path carries no `/api/v1` prefix: `apiBase()` supplies it, and it differs per host.
  // The URL suffix and the saved filename share one string, which is why `bundle.json`
  // works unmodified — the route is `export.bundle.json` and the file lands as
  // `research-<id>.bundle.json`.
  const download = async (format: ExportFormat) => {
    setExporting(format);
    try {
      await downloadExport(
        `/research/${session.session_id}/export.${format}`,
        `research-${session.session_id.slice(0, 8)}.${format}`,
      );
    } catch (err) {
      toast.error(
        err instanceof ApiError
          ? err.message
          : format === "pdf"
            ? "PDF export is unavailable."
            : "Export failed.",
      );
    } finally {
      setExporting(null);
    }
  };

  return (
    <div className="space-y-6">
      {preview && (
        <PreviewDrawer
          open
          onClose={() => setPreview(null)}
          url={documentUrl(session.project_id, preview.id)}
          filename={preview.filename}
          downloadable
          subtitle={preview.page ? `Cited from page ${preview.page}` : "Cited from your corpus"}
        />
      )}

      <section aria-labelledby="report-heading" className="card p-6">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h1 id="report-heading" className="font-serif text-xl font-bold tracking-tight text-text-primary">
            Research Report
          </h1>
          <div className="flex gap-2 print:hidden">
            <button
              type="button"
              onClick={copy}
              disabled={exporting !== null}
              className="btn btn-secondary px-3 py-1 text-xs font-mono"
            >
              Copy
            </button>
            <button
              type="button"
              onClick={() => download("md")}
              disabled={exporting !== null}
              className="btn btn-secondary px-3 py-1 text-xs font-mono"
            >
              {exporting === "md" && <span className="spinner" />}
              .md
            </button>
            <button
              type="button"
              onClick={() => download("pdf")}
              disabled={exporting !== null}
              className="btn btn-secondary px-3 py-1 text-xs font-mono"
            >
              {exporting === "pdf" && <span className="spinner" />}
              PDF
            </button>
            {/* The verifiable artifact. Titled rather than labelled at length because the
                filename says what it is on download, and the Verify panel below explains
                what to do with it — a button is the wrong place for a paragraph. */}
            <button
              type="button"
              onClick={() => download("bundle.json")}
              disabled={exporting !== null}
              title="Verifiable research bundle — report, evidence, sources and approval chain, hash-checkable offline"
              className="btn btn-secondary px-3 py-1 text-xs font-mono"
            >
              {exporting === "bundle.json" && <span className="spinner" />}
              .bundle.json
            </button>
          </div>
        </div>

        <div className="mb-6 flex flex-wrap gap-x-8 gap-y-3 border-y border-border py-3">
          <Metric label="Duration" value={formatDuration(session.elapsed_seconds)} />
          <Metric label="Cost" value={formatCost(session.total_cost_usd)} />
          <Metric label="Tokens" value={formatNumber(tokens)} />
          <Metric label="Sources" value={String(sources.length)} />
        </div>

        <div className="mb-6 space-y-4">
          <ModelAttribution modelRouting={session.model_routing} />
          {/* Collapsed by default: the instruction only matters once someone has the file,
              and an always-open command block would put shell syntax above the report on
              every read. The claim on the landing page is that a reviewer does not have to
              trust this tool — this is where that becomes actionable. */}
          <Disclosure
            label="Verify this report independently"
            summary="offline, no AI, no account"
          >
            <div className="space-y-3 text-sm leading-relaxed text-text-secondary">
              <p>
                Download <code className="font-mono text-xs">.bundle.json</code> above, then
                check it with the standalone verifier. It re-computes every hash, confirms
                each citation resolves to a source, and confirms an approval record matches
                this exact report text — with no network access and no model call.
              </p>
              <pre className="overflow-x-auto border border-border bg-bg-elevated p-3 font-mono text-xs text-text-primary">
                <code>{VERIFY_COMMAND}</code>
              </pre>
              <p className="text-text-muted">
                Exit status is 0 on pass and 1 on fail. Add{" "}
                <code className="font-mono text-xs">--format json</code> for a machine-readable
                report. A bundle produced in demo mode says so above its verdict.
              </p>
            </div>
          </Disclosure>
        </div>

        {report ? (
          <Report
            markdown={report}
            sources={sources}
            onPreview={(locator, source) =>
              setPreview({
                id: locator.documentId,
                // The engine puts the filename in the source title for corpus evidence;
                // it is what picks the renderer, so fall back to the id rather than
                // guessing a type.
                filename: source.title || locator.documentId,
                page: locator.page,
              })
            }
          />
        ) : (
          <p className="text-sm text-text-muted">This report has no body.</p>
        )}
        <SourcesPanel sources={sources} />
      </section>

      <div className="print:hidden">
        <ChatPanel sessionId={session.session_id} sources={sources} />
      </div>
    </div>
  );
}
