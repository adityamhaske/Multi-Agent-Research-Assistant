"use client";

import { useState } from "react";
import toast from "react-hot-toast";

import { Report, SourcesPanel } from "@/lib/citations";
import { formatCost, formatDuration, formatNumber } from "@/lib/format";
import type { SessionDetail } from "@/lib/types";

import { ChatPanel } from "./ChatPanel";

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[0.7rem] uppercase tracking-wide text-text-muted">{label}</div>
      <div className="font-mono text-sm text-text-primary tabular-nums">{value}</div>
    </div>
  );
}

export function ReportView({ session }: { session: SessionDetail }) {
  const report = session.final_report ?? session.draft_report ?? "";
  const sources = session.sources ?? [];
  const tokens = session.total_tokens_input + session.total_tokens_output;
  const [exporting, setExporting] = useState<null | "md" | "pdf">(null);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(report);
      toast.success("Report copied to clipboard.");
    } catch {
      toast.error("Couldn't access the clipboard.");
    }
  };

  // Server-rendered export (docs/05 §3, docs/07 §3): .md is the raw report; .pdf is
  // WeasyPrint. Fetched same-origin so the httpOnly cookie authenticates; a 501 (PDF
  // libs missing) surfaces as a toast rather than a broken download.
  const download = async (format: "md" | "pdf") => {
    setExporting(format);
    try {
      const res = await fetch(`/api/v1/research/${session.session_id}/export.${format}`, {
        credentials: "include",
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => null);
        toast.error(
          (detail as { detail?: string } | null)?.detail ??
            (format === "pdf" ? "PDF export is unavailable." : "Export failed."),
        );
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `research-${session.session_id.slice(0, 8)}.${format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      toast.error("Network error during export.");
    } finally {
      setExporting(null);
    }
  };

  return (
    <div className="space-y-6">
      <section aria-labelledby="report-heading" className="card">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h1 id="report-heading" className="text-lg font-semibold text-text-primary">
            Report
          </h1>
          <div className="flex gap-2 print:hidden">
            <button
              type="button"
              onClick={copy}
              disabled={exporting !== null}
              className="btn btn-secondary px-3 py-1.5 text-sm"
            >
              Copy
            </button>
            <button
              type="button"
              onClick={() => download("md")}
              disabled={exporting !== null}
              className="btn btn-secondary px-3 py-1.5 text-sm"
            >
              {exporting === "md" && <span className="spinner" />}
              .md
            </button>
            <button
              type="button"
              onClick={() => download("pdf")}
              disabled={exporting !== null}
              className="btn btn-secondary px-3 py-1.5 text-sm"
            >
              {exporting === "pdf" && <span className="spinner" />}
              PDF
            </button>
          </div>
        </div>

        <div className="mb-6 flex flex-wrap gap-x-8 gap-y-3 border-y border-border py-3">
          <Metric label="Duration" value={formatDuration(session.elapsed_seconds)} />
          <Metric label="Cost" value={formatCost(session.total_cost_usd)} />
          <Metric label="Tokens" value={formatNumber(tokens)} />
          <Metric label="Sources" value={String(sources.length)} />
        </div>

        {report ? (
          <Report markdown={report} sources={sources} />
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
