import type { AnalyzeAccepted, JobStatus, ProgressEvent } from "./types";

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
