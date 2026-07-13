import { describe, test, expect } from "vitest";
import { deriveRiskBand, countsLine } from "@/lib/riskBand";
import type { ReportSummary } from "@/lib/api/types";

function summary(overrides: Partial<ReportSummary> = {}): ReportSummary {
  return {
    total_clauses: 10,
    validated_findings: 0,
    clean_clauses: 10,
    high: 0,
    medium: 0,
    low: 0,
    ...overrides,
  };
}

describe("deriveRiskBand (spec 017 D2 / AC-2)", () => {
  test("high_dominates", () => {
    expect(deriveRiskBand(summary({ high: 1, medium: 5, low: 9, validated_findings: 15 }))).toEqual({
      band: "high",
      label: "High risk",
    });
  });

  test("medium_when_no_high", () => {
    expect(deriveRiskBand(summary({ high: 0, medium: 2, validated_findings: 2 }))).toEqual({
      band: "medium",
      label: "Medium risk",
    });
  });

  test("low_when_only_lows", () => {
    expect(deriveRiskBand(summary({ high: 0, medium: 0, low: 3, validated_findings: 3 }))).toEqual({
      band: "low",
      label: "Low risk",
    });
  });

  test("none_when_no_findings", () => {
    expect(deriveRiskBand(summary({ validated_findings: 0 }))).toEqual({
      band: "none",
      label: "No issues found",
    });
  });

  test("counts_line", () => {
    expect(countsLine(summary({ high: 2, medium: 3, low: 1, total_clauses: 42 }))).toBe(
      "2 high · 3 medium · 1 low across 42 clauses",
    );
  });
});
