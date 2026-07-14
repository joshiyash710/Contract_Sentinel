import { describe, test, expect } from "vitest";
import {
  dashboardMetricsFixture,
  emptyDashboardFixture,
  jobListFixture,
  emptyJobListFixture,
} from "@/lib/api/fixtures";

/**
 * Drift lock (spec 018 AC-18). Field lists copied from backend app/runner/models.py — if a
 * boundary model gains/loses a field, this fails, forcing the TS mirror + this list to update.
 */
const DASHBOARD_FIELDS = [
  "total_contracts",
  "completed_contracts",
  "risk_distribution",
  "portfolio_health_pct",
  "portfolio_health_band",
  "usage_timeline",
  "risk_by_clause_type",
  "clause_risk_heatmap",
  "top_risky_clause_types",
] as const;

const JOB_LIST_ITEM_FIELDS = [
  "job_id",
  "original_filename",
  "status",
  "submitted_at",
  "finished_at",
  "report_available",
  "risk_band",
  "high",
  "medium",
  "low",
] as const;

const HEATMAP_FIELDS = ["rows", "cols", "cells"] as const;
const CLAUSE_TYPE_RISK_FIELDS = ["clause_type", "high", "medium", "low"] as const;

describe("018 boundary mirror ↔ Pydantic drift lock (AC-18)", () => {
  test("DashboardMetrics carries exactly the model fields", () => {
    expect(Object.keys(dashboardMetricsFixture).sort()).toEqual([...DASHBOARD_FIELDS].sort());
    expect(Object.keys(emptyDashboardFixture).sort()).toEqual([...DASHBOARD_FIELDS].sort());
  });

  test("clause_risk_heatmap + risk_by_clause_type shapes", () => {
    expect(Object.keys(dashboardMetricsFixture.clause_risk_heatmap).sort()).toEqual(
      [...HEATMAP_FIELDS].sort(),
    );
    expect(dashboardMetricsFixture.risk_by_clause_type.length).toBeGreaterThan(0);
    for (const c of dashboardMetricsFixture.risk_by_clause_type) {
      expect(Object.keys(c).sort()).toEqual([...CLAUSE_TYPE_RISK_FIELDS].sort());
    }
  });

  test("JobListItem carries exactly the model fields", () => {
    expect(jobListFixture.items.length).toBeGreaterThan(0);
    for (const it of jobListFixture.items) {
      expect(Object.keys(it).sort()).toEqual([...JOB_LIST_ITEM_FIELDS].sort());
    }
    expect(emptyJobListFixture).toEqual({ items: [], total: 0 });
  });
});
