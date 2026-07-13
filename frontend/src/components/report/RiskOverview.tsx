"use client";

import { DonutChart, type DonutSlice } from "@/components/charts/DonutChart";
import type { ReportSummary } from "@/lib/api/types";

const ROWS: { key: "high" | "medium" | "low"; label: string; color: string }[] = [
  { key: "high", label: "High", color: "bg-risk-high" },
  { key: "medium", label: "Medium", color: "bg-risk-medium" },
  { key: "low", label: "Low", color: "bg-risk-low" },
];

/**
 * Risk overview (spec 017 — real data-viz, no fabrication): a donut of the ACTUAL risk
 * distribution from the 009 summary counts, plus a severity breakdown with proportion bars.
 * Rendered only when there are graded findings; a report with only severity-unavailable
 * findings shows nothing here (no fake slices).
 */
export function RiskOverview({ summary }: { summary: ReportSummary }) {
  const graded = summary.high + summary.medium + summary.low;
  const slices: DonutSlice[] = ROWS.filter((r) => summary[r.key] > 0).map((r) => ({
    name: r.label,
    value: summary[r.key],
    level: r.key,
  }));

  if (graded === 0) return null;

  return (
    <section className="rounded-card border border-subtle bg-card p-6">
      <h2 className="mb-4 text-h3 font-semibold text-text-primary">Risk overview</h2>
      <div className="grid items-center gap-6 md:grid-cols-2">
        {/* Donut */}
        <div className="relative mx-auto w-full max-w-[240px]">
          <DonutChart
            data={slices}
            height={200}
            center={
              <div className="text-center">
                <div className="text-h1 font-bold leading-none text-text-primary tabular-nums">
                  {graded}
                </div>
                <div className="mt-1 text-small text-text-tertiary">
                  {graded === 1 ? "clause flagged" : "clauses flagged"}
                </div>
              </div>
            }
          />
        </div>

        {/* Severity breakdown with proportion bars */}
        <div className="space-y-3">
          {ROWS.map((r) => {
            const v = summary[r.key];
            const pct = graded > 0 ? Math.round((v / graded) * 100) : 0;
            return (
              <div key={r.key}>
                <div className="mb-1 flex items-center justify-between text-small">
                  <span className="inline-flex items-center gap-2 text-text-secondary">
                    <span className={`h-2.5 w-2.5 rounded-pill ${r.color}`} />
                    {r.label} severity
                  </span>
                  <span className="font-semibold text-text-primary tabular-nums">{v}</span>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-pill bg-app">
                  <div className={`h-full rounded-pill ${r.color}`} style={{ width: `${pct}%` }} />
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
