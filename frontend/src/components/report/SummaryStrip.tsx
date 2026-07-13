import type { ReportSummary } from "@/lib/api/types";

/** Header roll-up stat chips (spec 017 §2.4). Reads the 009 ReportSummary counts. */
export function SummaryStrip({ summary }: { summary: ReportSummary }) {
  const chips: Array<{ label: string; value: number; tone?: string; accent?: string }> = [
    { label: "Total clauses", value: summary.total_clauses },
    { label: "Findings", value: summary.validated_findings, accent: "text-accent" },
    { label: "Clean", value: summary.clean_clauses },
    { label: "High", value: summary.high, tone: "text-risk-high" },
    { label: "Medium", value: summary.medium, tone: "text-risk-medium" },
    { label: "Low", value: summary.low, tone: "text-risk-low" },
  ];
  return (
    <div className="grid grid-cols-3 gap-3 sm:grid-cols-6">
      {chips.map((c) => (
        <div
          key={c.label}
          className="rounded-card border border-subtle bg-card p-3 text-center transition hover:bg-card-raised"
        >
          <div className={`text-h2 font-bold tabular-nums ${c.tone ?? c.accent ?? "text-text-primary"}`}>
            {c.value}
          </div>
          <div className="mt-0.5 text-small text-text-tertiary">{c.label}</div>
        </div>
      ))}
    </div>
  );
}
