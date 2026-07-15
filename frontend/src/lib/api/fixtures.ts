import type {
  AnalyzeAccepted,
  AuthUser,
  ContractReport,
  DashboardMetrics,
  JobList,
  JobStatus,
  ProgressEvent,
} from "./types";

/**
 * Static fixtures for the mock provider (spec 013 §2.4). No mockup strings as semantic data
 * (spec EC-5) — generic placeholder ids only. The scripted event sequence mirrors a real run:
 * several `progress` events then a terminal `completed` carrying `final: JobStatus`.
 */

export const FIXTURE_JOB_ID = "job-fixture-1";

// ── 014 auth fixture ──────────────────────────────────────────────────────────
export const authUserFixture: AuthUser = {
  id: "user-fixture-1",
  email: "fixture@example.com",
  name: "Alex Morgan",
  title: "Legal Counsel",
};

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

// ── 018 dashboard fixtures ────────────────────────────────────────────────────
function usageDays(counts: Record<string, number> = {}): { period: string; count: number }[] {
  // 30 dense day-buckets ending on a fixed date, matching the backend shape.
  const end = new Date("2026-01-30T00:00:00Z");
  const out: { period: string; count: number }[] = [];
  for (let i = 29; i >= 0; i--) {
    const d = new Date(end);
    d.setUTCDate(end.getUTCDate() - i);
    const period = d.toISOString().slice(0, 10);
    out.push({ period, count: counts[period] ?? 0 });
  }
  return out;
}

export const dashboardMetricsFixture: DashboardMetrics = {
  total_contracts: 5,
  completed_contracts: 4,
  risk_distribution: { high: 3, medium: 2, low: 6 },
  portfolio_health_pct: 64,
  portfolio_health_band: "elevated",
  usage_timeline: usageDays({ "2026-01-28": 2, "2026-01-30": 3 }),
  risk_by_clause_type: [
    { clause_type: "liability", high: 2, medium: 0, low: 1 },
    { clause_type: "indemnification", high: 1, medium: 2, low: 0 },
    { clause_type: "term", high: 0, medium: 0, low: 4 },
    { clause_type: "Uncategorized", high: 0, medium: 0, low: 1 },
  ],
  clause_risk_heatmap: {
    rows: ["Uncategorized", "indemnification", "liability", "term"],
    cols: ["low", "medium", "high"],
    cells: [
      [1, 0, 0],
      [0, 2, 1],
      [1, 0, 2],
      [4, 0, 0],
    ],
  },
  top_risky_clause_types: [
    { clause_type: "liability", high_count: 2 },
    { clause_type: "indemnification", high_count: 1 },
  ],
};

export const emptyDashboardFixture: DashboardMetrics = {
  total_contracts: 0,
  completed_contracts: 0,
  risk_distribution: { high: 0, medium: 0, low: 0 },
  portfolio_health_pct: 100,
  portfolio_health_band: "healthy",
  usage_timeline: usageDays(),
  risk_by_clause_type: [],
  clause_risk_heatmap: { rows: [], cols: ["low", "medium", "high"], cells: [] },
  top_risky_clause_types: [],
};

export const jobListFixture: JobList = {
  total: 3,
  items: [
    {
      job_id: "job-a",
      original_filename: "MSA_AcmeCorp.pdf",
      status: "completed",
      submitted_at: "2026-01-30T09:00:00Z",
      finished_at: "2026-01-30T09:03:00Z",
      report_available: true,
      risk_band: "high",
      high: 3,
      medium: 1,
      low: 2,
    },
    {
      job_id: "job-b",
      original_filename: "NDA_draft.docx",
      status: "running",
      submitted_at: "2026-01-30T08:40:00Z",
      finished_at: null,
      report_available: false,
      risk_band: null,
      high: null,
      medium: null,
      low: null,
    },
    {
      job_id: "job-c",
      original_filename: "vendor_terms.pdf",
      status: "failed",
      submitted_at: "2026-01-29T14:00:00Z",
      finished_at: "2026-01-29T14:01:00Z",
      report_available: false,
      risk_band: null,
      high: null,
      medium: null,
      low: null,
    },
  ],
};

export const emptyJobListFixture: JobList = { items: [], total: 0 };

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
