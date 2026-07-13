/**
 * TypeScript mirror of the feature-011 HTTP+SSE contract (spec 011 §2) and the 001 enums.
 * These are the ONLY typed backend surface every screen imports. They mirror the Pydantic
 * boundary models field-for-field — the internal ContractState TypedDict never crosses here
 * (constitution §4). Do not invent divergent field names (spec 013 §2.1).
 *
 * The `as const` tuples below are the drift-lock (spec AC-17): each type is derived from its
 * tuple, so a tuple and its type cannot diverge, and a test compares the tuples to the
 * 001/011 enum sets.
 */

// ── 001 enums ────────────────────────────────────────────────────────────────
export const RISK_LEVELS = ["low", "medium", "high"] as const;
export type RiskLevel = (typeof RISK_LEVELS)[number];

export const DELIVERY_STATES = ["pending", "success", "failed"] as const;
export type MCPDeliveryStatus = (typeof DELIVERY_STATES)[number];

export interface MCPDeliveryInfo {
  status: MCPDeliveryStatus;
  error_message?: string | null;
  delivered_at?: string | null;
}

// ── 011 job-lifecycle ────────────────────────────────────────────────────────
export const JOB_STATES = ["queued", "running", "completed", "failed"] as const;
export type JobState = (typeof JOB_STATES)[number];

export interface ErrorInfo {
  kind: string;
  message: string;
}

// 011 §2.2 — 202 body for POST /api/analyze
export interface AnalyzeAccepted {
  job_id: string;
  status: JobState;
  submitted_at: string;
}

// 011 §2.3 — GET /api/jobs/{id}. ALL nine fields, verbatim.
export interface JobStatus {
  job_id: string;
  status: JobState;
  current_node?: string | null;
  completed_nodes: string[];
  submitted_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  report_available: boolean;
  mcp_delivery_status: Record<string, MCPDeliveryInfo>;
  error?: ErrorInfo | null;
}

// 011 §2.4 — one SSE payload.
export const SSE_EVENT_NAMES = ["progress", "completed", "failed"] as const;
export type SseEventName = (typeof SSE_EVENT_NAMES)[number];

export interface ProgressEvent {
  event: SseEventName;
  job_id: string;
  node?: string | null;
  index?: number | null;
  total?: number | null;
  elapsed_seconds?: number | null;
  // Present ONLY on the terminal "completed" | "failed" event, never on "progress".
  final?: JobStatus | null;
}

// ── 009 report boundary model (Node 7 output) ────────────────────────────────
// Field-for-field mirror of backend/app/models/report.py. This is the ReportAgent's
// serialized ContractReport (model_dump_json), served by GET /api/jobs/{id}/report?format=json.
// It is a boundary model — the internal ContractState TypedDict never crosses here
// (constitution §4). Do not invent divergent field names (spec 017 §2.1 / plan §3.1).

export interface ReportEvidence {
  source_reference: string;
  snippet_text: string;
}

// 009 three-way rewrite state, flattened by the assembler (spec 017 D3 / AC-6).
export const REWRITE_STATES = ["rewritten", "unavailable", "not_eligible"] as const;
export type RewriteState = (typeof REWRITE_STATES)[number];

export interface ReportFinding {
  clause_id: string;
  position: number;
  section_number?: string | null;
  clause_type?: string | null;
  // RiskLevel value on the wire, but 009 types it Optional[str]; widened to string|null
  // so an unknown/absent value renders "Severity unavailable" rather than crashing (AC-5).
  risk_level?: string | null;
  risk_rationale?: string | null;
  clause_text: string;
  rewrite_state: RewriteState;
  suggested_rewrite?: string | null; // present only when rewrite_state === "rewritten"
  path_taken?: string | null;
  confidence_score?: number | null;
  evidence: ReportEvidence[];
}

export interface ReportSummary {
  total_clauses: number;
  validated_findings: number;
  clean_clauses: number;
  high: number;
  medium: number;
  low: number;
}

export interface ContractReport {
  document_id: string;
  original_filename: string;
  uploaded_at: string;
  processing_started_at?: string | null;
  generated_at: string;
  ocr_used: boolean;
  ocr_confidence?: number | null;
  // 009 Optional[dict] → set means a minimal "could not process" report (spec 017 D6 / EC-4).
  ingest_error?: Record<string, unknown> | null;
  summary: ReportSummary;
  findings: ReportFinding[];
  node_timings: Record<string, unknown>;
  error_count: number;
}
