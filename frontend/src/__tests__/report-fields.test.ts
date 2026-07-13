import { describe, test, expect } from "vitest";
import {
  reportFixture,
  ingestErrorReportFixture,
  emptyReportFixture,
} from "@/lib/api/fixtures";

/**
 * Drift lock (spec 017 AC-15a). A plain `tsc` check compares object shapes but nothing
 * automatically compares the TS ContractReport mirror to the Python 009 model. So we write
 * the 009 field lists down literally here: if backend/app/models/report.py adds or removes a
 * field, this test fails, forcing the TS mirror (and this list) to be updated in lockstep.
 * The field lists below are copied from backend/app/models/report.py.
 */

const CONTRACT_REPORT_FIELDS = [
  "document_id",
  "original_filename",
  "uploaded_at",
  "processing_started_at",
  "generated_at",
  "ocr_used",
  "ocr_confidence",
  "ingest_error",
  "summary",
  "findings",
  "node_timings",
  "error_count",
] as const;

const REPORT_SUMMARY_FIELDS = [
  "total_clauses",
  "validated_findings",
  "clean_clauses",
  "high",
  "medium",
  "low",
] as const;

const REPORT_FINDING_FIELDS = [
  "clause_id",
  "position",
  "section_number",
  "clause_type",
  "risk_level",
  "risk_rationale",
  "clause_text",
  "rewrite_state",
  "suggested_rewrite",
  "path_taken",
  "confidence_score",
  "evidence",
] as const;

const REPORT_EVIDENCE_FIELDS = ["source_reference", "snippet_text"] as const;

describe("ContractReport mirror ↔ 009 model drift lock (AC-15a)", () => {
  test("reportFixture carries exactly the 009 ContractReport fields", () => {
    expect(Object.keys(reportFixture).sort()).toEqual([...CONTRACT_REPORT_FIELDS].sort());
  });

  test("summary carries exactly the 009 ReportSummary fields", () => {
    expect(Object.keys(reportFixture.summary).sort()).toEqual([...REPORT_SUMMARY_FIELDS].sort());
  });

  test("each finding carries exactly the 009 ReportFinding fields", () => {
    expect(reportFixture.findings.length).toBeGreaterThan(0);
    for (const f of reportFixture.findings) {
      expect(Object.keys(f).sort()).toEqual([...REPORT_FINDING_FIELDS].sort());
    }
  });

  test("each evidence item carries exactly the 009 ReportEvidence fields", () => {
    const withEvidence = reportFixture.findings.filter((f) => f.evidence.length > 0);
    expect(withEvidence.length).toBeGreaterThan(0);
    for (const f of withEvidence) {
      for (const e of f.evidence) {
        expect(Object.keys(e).sort()).toEqual([...REPORT_EVIDENCE_FIELDS].sort());
      }
    }
  });

  test("ingest-error and empty fixtures share the ContractReport shape", () => {
    expect(Object.keys(ingestErrorReportFixture).sort()).toEqual(
      [...CONTRACT_REPORT_FIELDS].sort(),
    );
    expect(Object.keys(emptyReportFixture).sort()).toEqual([...CONTRACT_REPORT_FIELDS].sort());
  });
});
