import { Download } from "lucide-react";
import { getApiClient } from "@/lib/api/provider";
import { StatusBadge, type BadgeTone } from "@/components/ui/StatusBadge";
import { deriveRiskBand, countsLine, type RiskBand } from "@/lib/riskBand";
import { formatGeneratedAt } from "@/lib/reportFormat";
import type { ContractReport } from "@/lib/api/types";

const BAND_TONE: Record<RiskBand, BadgeTone> = {
  high: "danger",
  medium: "warning",
  low: "success",
  none: "success",
};

/**
 * Report header (spec 017 §2.4, grounded screen-11 header): filename, DERIVED risk band + literal
 * counts (D2 — no fabricated 0–100 score), generated-at, an OCR note when used, and exactly two
 * honest downloads — Markdown + JSON (D5). No Notion/JPG/PDF-split/email controls.
 */
export function ReportHeader({ jobId, report }: { jobId: string; report: ContractReport }) {
  const client = getApiClient();
  const band = deriveRiskBand(report.summary);

  return (
    <header className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
      <div className="min-w-0">
        <h1 className="truncate text-h2 font-bold text-text-primary">{report.original_filename}</h1>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <StatusBadge label={band.label} tone={BAND_TONE[band.band]} />
          <span className="text-small text-text-secondary">{countsLine(report.summary)}</span>
        </div>
        <p className="mt-1 text-small text-text-tertiary">
          Generated {formatGeneratedAt(report.generated_at)}
        </p>
        {report.ocr_used && (
          <p className="mt-1 text-small text-text-tertiary">
            OCR was used to read this document
            {report.ocr_confidence != null && ` (${Math.round(report.ocr_confidence * 100)}% confidence)`}
            .
          </p>
        )}
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <a
          href={client.getReportUrl(jobId, "md")}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 rounded-input bg-accent-gradient px-4 py-2.5 font-semibold text-accent-fg hover:opacity-95"
        >
          <Download size={16} /> Download report (Markdown)
        </a>
        <a
          href={client.getReportUrl(jobId, "json")}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 rounded-input border border-subtle px-4 py-2.5 font-medium text-text-primary hover:bg-card-raised"
        >
          <Download size={16} /> Download data (JSON)
        </a>
      </div>
    </header>
  );
}
