import type {
  AnalyzeAccepted,
  ContractReport,
  JobStatus,
  ProgressEvent,
} from "./types";

/**
 * Static fixtures for the mock provider (spec 013 §2.4). No mockup strings as semantic data
 * (spec EC-5) — generic placeholder ids only. The scripted event sequence mirrors a real run:
 * several `progress` events then a terminal `completed` carrying `final: JobStatus`.
 */

export const FIXTURE_JOB_ID = "job-fixture-1";

export const acceptedFixture: AnalyzeAccepted = {
  job_id: FIXTURE_JOB_ID,
  status: "queued",
  submitted_at: "2026-01-01T00:00:00Z",
};

export const completedStatusFixture: JobStatus = {
  job_id: FIXTURE_JOB_ID,
  status: "completed",
  current_node: "report",
  completed_nodes: ["ingest_agent", "clause_splitter", "risk_score", "report"],
  submitted_at: "2026-01-01T00:00:00Z",
  started_at: "2026-01-01T00:00:01Z",
  finished_at: "2026-01-01T00:01:35Z",
  report_available: true,
  mcp_delivery_status: {
    drive: { status: "success", error_message: null, delivered_at: "2026-01-01T00:01:36Z" },
    gmail: { status: "success", error_message: null, delivered_at: "2026-01-01T00:01:37Z" },
  },
  error: null,
};

// ── 009 ContractReport fixtures (feature 017) ────────────────────────────────
// Rich fixture exercising every FindingCard branch (spec 017 Task 1): a High rewritten
// finding with evidence, a Medium with an unavailable rewrite, a Low not-eligible with no
// evidence, and a null-severity/null-rationale finding. One long clause_text for the
// collapse control. Generic placeholder text only (no mockup strings as data, spec EC-5).
export const reportFixture: ContractReport = {
  document_id: FIXTURE_JOB_ID,
  original_filename: "sample_contract.pdf",
  uploaded_at: "2026-01-01T00:00:00Z",
  processing_started_at: "2026-01-01T00:00:01Z",
  generated_at: "2026-01-01T00:01:35Z",
  ocr_used: false,
  ocr_confidence: null,
  ingest_error: null,
  summary: {
    total_clauses: 12,
    validated_findings: 4,
    clean_clauses: 8,
    high: 1,
    medium: 1,
    low: 1,
  },
  findings: [
    {
      clause_id: "c-001",
      position: 1,
      section_number: "3.1",
      clause_type: "limitation_of_liability",
      risk_level: "high",
      risk_rationale: "Caps liability far below the contract value, exposing the buyer.",
      clause_text:
        "In no event shall the Provider's aggregate liability exceed the fees paid in the " +
        "preceding month, regardless of the form of action, whether in contract, tort, or " +
        "otherwise, and notwithstanding any failure of essential purpose of any limited remedy, " +
        "and this limitation shall apply even where the Provider has been advised of the " +
        "possibility of such damages arising from any cause whatsoever under this Agreement.",
      rewrite_state: "rewritten",
      suggested_rewrite:
        "The Provider's aggregate liability shall not exceed the total fees paid in the twelve (12) " +
        "months preceding the claim.",
      path_taken: "corrective",
      confidence_score: 0.82,
      evidence: [
        {
          source_reference: "playbook://liability/caps#12-month",
          snippet_text: "Liability caps below a 12-month fee floor are considered high risk.",
        },
      ],
    },
    {
      clause_id: "c-002",
      position: 2,
      section_number: "5.2",
      clause_type: "indemnification",
      risk_level: "medium",
      risk_rationale: "One-sided indemnity favoring the counterparty.",
      clause_text: "The Customer shall indemnify and hold harmless the Provider from all claims.",
      rewrite_state: "unavailable",
      suggested_rewrite: null,
      path_taken: "corrective",
      confidence_score: 0.6,
      evidence: [
        {
          source_reference: "playbook://indemnity/mutual",
          snippet_text: "Prefer mutual indemnification for balanced risk allocation.",
        },
      ],
    },
    {
      clause_id: "c-003",
      position: 3,
      section_number: null,
      clause_type: "governing_law",
      risk_level: "low",
      risk_rationale: "Standard governing-law clause; minor venue note.",
      clause_text: "This Agreement is governed by the laws of the State of Delaware.",
      rewrite_state: "not_eligible",
      suggested_rewrite: null,
      path_taken: "direct",
      confidence_score: null,
      evidence: [],
    },
    {
      clause_id: "c-004",
      position: 4,
      section_number: "9.4",
      clause_type: null,
      risk_level: null,
      risk_rationale: null,
      clause_text: "Miscellaneous provisions apply as set forth in Exhibit B.",
      rewrite_state: "not_eligible",
      suggested_rewrite: null,
      path_taken: null,
      confidence_score: null,
      evidence: [],
    },
  ],
  node_timings: { report: 0.4 },
  error_count: 0,
};

// Minimal "could not process" report (009 Edge Case 1 / spec 017 D6 / AC-10).
export const ingestErrorReportFixture: ContractReport = {
  document_id: FIXTURE_JOB_ID,
  original_filename: "corrupt.pdf",
  uploaded_at: "2026-01-01T00:00:00Z",
  processing_started_at: "2026-01-01T00:00:01Z",
  generated_at: "2026-01-01T00:00:05Z",
  ocr_used: false,
  ocr_confidence: null,
  ingest_error: { message: "Could not parse the uploaded file." },
  summary: {
    total_clauses: 0,
    validated_findings: 0,
    clean_clauses: 0,
    high: 0,
    medium: 0,
    low: 0,
  },
  findings: [],
  node_timings: {},
  error_count: 1,
};

// Successful but issue-free report (spec 017 D6 / AC-11). OCR used, so the header shows the note.
export const emptyReportFixture: ContractReport = {
  document_id: FIXTURE_JOB_ID,
  original_filename: "clean_contract.pdf",
  uploaded_at: "2026-01-01T00:00:00Z",
  processing_started_at: "2026-01-01T00:00:01Z",
  generated_at: "2026-01-01T00:01:00Z",
  ocr_used: true,
  ocr_confidence: 0.87,
  ingest_error: null,
  summary: {
    total_clauses: 9,
    validated_findings: 0,
    clean_clauses: 9,
    high: 0,
    medium: 0,
    low: 0,
  },
  findings: [],
  node_timings: {},
  error_count: 0,
};

/** Ordered scripted stream for a fixture run. */
export function scriptedEvents(jobId: string): ProgressEvent[] {
  const nodes = ["ingest_agent", "clause_splitter", "risk_score", "report"];
  const progress: ProgressEvent[] = nodes.map((node, i) => ({
    event: "progress",
    job_id: jobId,
    node,
    index: i + 1,
    total: nodes.length,
    elapsed_seconds: 1.0,
    final: null,
  }));
  const terminal: ProgressEvent = {
    event: "completed",
    job_id: jobId,
    final: { ...completedStatusFixture, job_id: jobId },
  };
  return [...progress, terminal];
}
