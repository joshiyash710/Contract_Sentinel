import { describe, test, expect } from "vitest";
import { titleCase, findingTitle, formatGeneratedAt } from "@/lib/reportFormat";
import type { ReportFinding } from "@/lib/api/types";

function finding(overrides: Partial<ReportFinding> = {}): ReportFinding {
  return {
    clause_id: "c-1",
    position: 1,
    section_number: null,
    clause_type: null,
    risk_level: null,
    risk_rationale: null,
    clause_text: "x",
    rewrite_state: "not_eligible",
    suggested_rewrite: null,
    path_taken: null,
    confidence_score: null,
    evidence: [],
    ...overrides,
  };
}

describe("reportFormat helpers (spec 017 D3)", () => {
  test("title_cases_clause_type", () => {
    expect(titleCase("limitation_of_liability")).toBe("Limitation Of Liability");
  });

  test("finding_title_uses_clause_type", () => {
    expect(findingTitle(finding({ clause_type: "indemnification", position: 2 }))).toBe(
      "Indemnification",
    );
  });

  test("finding_title_falls_back_to_position_verbatim", () => {
    expect(findingTitle(finding({ clause_type: null, position: 3 }))).toBe("Clause 3");
  });

  test("formats_generated_at_non_empty", () => {
    const out = formatGeneratedAt("2026-01-01T00:01:35Z");
    expect(typeof out).toBe("string");
    expect(out.length).toBeGreaterThan(0);
  });

  test("formats_generated_at_tolerates_bad_input", () => {
    expect(() => formatGeneratedAt("not-a-date")).not.toThrow();
  });
});
