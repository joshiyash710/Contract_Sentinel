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
