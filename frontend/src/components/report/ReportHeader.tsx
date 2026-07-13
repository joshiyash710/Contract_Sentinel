import { Download, FileText, ScanLine, CalendarClock } from "lucide-react";
import { getApiClient } from "@/lib/api/provider";
import { deriveRiskBand, countsLine, type RiskBand } from "@/lib/riskBand";
import { formatGeneratedAt } from "@/lib/reportFormat";
import type { ContractReport } from "@/lib/api/types";

const BAND_STYLE: Record<RiskBand, { dot: string; text: string; ring: string; glow: string }> = {
  high: { dot: "bg-risk-high", text: "text-risk-high", ring: "ring-risk-high/30", glow: "shadow-[0_0_40px_-8px_var(--risk-high)]" },
  medium: { dot: "bg-risk-medium", text: "text-risk-medium", ring: "ring-risk-medium/30", glow: "shadow-[0_0_40px_-8px_var(--risk-medium)]" },
  low: { dot: "bg-risk-low", text: "text-risk-low", ring: "ring-risk-low/30", glow: "shadow-[0_0_40px_-8px_var(--risk-low)]" },
  none: { dot: "bg-risk-low", text: "text-risk-low", ring: "ring-risk-low/30", glow: "" },
};

/**
 * Report hero header (spec 017 §2.4, grounded screen-11 header): filename, DERIVED risk band +
 * literal counts (D2 — no fabricated 0–100 score), generated-at, an OCR note, and exactly two
 * honest downloads — Markdown + JSON (D5). Styled as a gradient hero for a polished SaaS feel.
 */
export function ReportHeader({ jobId, report }: { jobId: string; report: ContractReport }) {
  const client = getApiClient();
  const band = deriveRiskBand(report.summary);
  const s = BAND_STYLE[band.band];

  return (
    <header
      className={`relative overflow-hidden rounded-card border border-subtle bg-card-raised p-6 ${s.glow}`}
    >
      {/* subtle brand gradient wash */}
      <div className="pointer-events-none absolute -right-24 -top-24 h-64 w-64 rounded-full bg-accent-gradient opacity-10 blur-3xl" />

      <div className="relative flex flex-col gap-5 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-small text-text-tertiary">
            <FileText size={14} /> Contract analysis report
          </div>
          <h1 className="mt-1 truncate text-h2 font-bold text-text-primary">
            {report.original_filename}
          </h1>

          {/* Risk band pill + counts */}
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <span
              className={`inline-flex items-center gap-2 rounded-pill bg-app px-3 py-1 text-body font-semibold ring-1 ${s.ring} ${s.text}`}
            >
              <span className={`h-2.5 w-2.5 rounded-pill ${s.dot}`} />
              {band.label}
            </span>
            <span className="text-small text-text-secondary">{countsLine(report.summary)}</span>
          </div>

          {/* meta row */}
          <div className="mt-3 flex flex-wrap items-center gap-4 text-small text-text-tertiary">
            <span className="inline-flex items-center gap-1.5">
              <CalendarClock size={14} /> Generated {formatGeneratedAt(report.generated_at)}
            </span>
            {report.ocr_used && (
              <span className="inline-flex items-center gap-1.5">
                <ScanLine size={14} /> OCR used
                {report.ocr_confidence != null &&
                  ` (${Math.round(report.ocr_confidence * 100)}% confidence)`}
              </span>
            )}
          </div>
        </div>

        {/* Downloads */}
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <a
            href={client.getReportUrl(jobId, "md")}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 rounded-input bg-accent-gradient px-4 py-2.5 font-semibold text-accent-fg shadow-glow transition hover:opacity-95"
          >
            <Download size={16} /> Download report (Markdown)
          </a>
          <a
            href={client.getReportUrl(jobId, "json")}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 rounded-input border border-subtle bg-card px-4 py-2.5 font-medium text-text-primary transition hover:bg-card-raised"
          >
            <Download size={16} /> Download data (JSON)
          </a>
        </div>
      </div>
    </header>
  );
}
