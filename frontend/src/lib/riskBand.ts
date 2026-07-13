import type { ReportSummary } from "@/lib/api/types";

/**
 * Overall risk band DERIVED from the 009 summary counts (spec 017 D2). The backend produces
 * NO aggregate 0–100 score, so we never fabricate one — the header shows a band + the literal
 * counts. This is the only overall-severity logic in the app.
 */
export type RiskBand = "high" | "medium" | "low" | "none";

export function deriveRiskBand(s: ReportSummary): { band: RiskBand; label: string } {
  if (s.high > 0) return { band: "high", label: "High risk" };
  if (s.medium > 0) return { band: "medium", label: "Medium risk" };
  if (s.validated_findings > 0) return { band: "low", label: "Low risk" };
  return { band: "none", label: "No issues found" };
}

export function countsLine(s: ReportSummary): string {
  return `${s.high} high · ${s.medium} medium · ${s.low} low across ${s.total_clauses} clauses`;
}
