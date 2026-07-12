import { vi } from "vitest";
import type { ApiClient, JobEventHandlers } from "@/lib/api/client";
import type { AnalyzeAccepted, JobStatus, ProgressEvent, SseEventName } from "@/lib/api/types";

/**
 * Scripted fake ApiClient for 015 tests (plan §4 / review B2). The 013 mock provider emits only
 * one happy sequence; this lets processing/upload tests drive failed / ingest-error /
 * already-finished / connecting / submit-error variants while components keep calling
 * getApiClient() unchanged (spec AC-16).
 */
export interface FakeClientOpts {
  events?: ProgressEvent[]; // replayed via openJobEvents (SSE seam; kept for api-client tests)
  emitError?: boolean; // openJobEvents invokes onError instead of events
  accepted?: AnalyzeAccepted; // submitAnalysis resolves this
  submitError?: unknown; // submitAnalysis rejects this
  statuses?: JobStatus[]; // getJob returns these in sequence (last one sticky) — drives polling
  getJobError?: unknown; // getJob rejects this (EC-6 404 / network)
}

export function makeFakeClient(opts: FakeClientOpts = {}): ApiClient {
  const openJobEvents = vi.fn((_, handlers: JobEventHandlers) => {
    const timers: ReturnType<typeof setTimeout>[] = [];
    let cancelled = false;
    if (opts.emitError) {
      timers.push(setTimeout(() => !cancelled && handlers.onError?.(new Error("boom")), 1));
    } else {
      (opts.events ?? []).forEach((ev, i) => {
        timers.push(
          setTimeout(() => {
            if (cancelled) return;
            if (ev.event === "progress") handlers.onProgress?.(ev);
            else handlers.onTerminal?.(ev);
          }, i + 1),
        );
      });
    }
    return () => {
      cancelled = true;
      timers.forEach(clearTimeout);
    };
  });

  return {
    submitAnalysis: vi.fn(async (): Promise<AnalyzeAccepted> => {
      if (opts.submitError) throw opts.submitError;
      return opts.accepted ?? { job_id: "job-1", status: "queued", submitted_at: "t" };
    }),
    getJob: (() => {
      let i = 0;
      return vi.fn(async (): Promise<JobStatus> => {
        if (opts.getJobError) throw opts.getJobError;
        const arr = opts.statuses ?? [completedFinal()];
        return arr[Math.min(i++, arr.length - 1)]; // advance, last sticky
      });
    })(),
    openJobEvents,
    getReportUrl: (id: string, fmt: "md" | "json") => `/api/jobs/${id}/report?format=${fmt}`,
    health: vi.fn(async () => ({ status: "ok" })),
  };
}

export function progress(node: string, index: number, total: number): ProgressEvent {
  return { event: "progress", job_id: "job-1", node, index, total, elapsed_seconds: 1, final: null };
}

export function terminal(event: SseEventName, final: JobStatus): ProgressEvent {
  return { event, job_id: "job-1", final };
}

export function runningStatus(currentNode: string, completed: string[] = []): JobStatus {
  return {
    job_id: "job-1",
    status: "running",
    current_node: currentNode,
    completed_nodes: completed,
    submitted_at: "t",
    started_at: "t",
    finished_at: null,
    report_available: false,
    mcp_delivery_status: {},
    error: null,
  };
}

export function queuedStatus(): JobStatus {
  return { ...runningStatus("", []), status: "queued", current_node: null };
}

export function completedFinal(overrides: Partial<JobStatus> = {}): JobStatus {
  return {
    job_id: "job-1",
    status: "completed",
    current_node: "report",
    completed_nodes: ["ingest_agent", "clause_splitter", "risk_score", "report"],
    submitted_at: "t",
    started_at: "t",
    finished_at: "t",
    report_available: true,
    mcp_delivery_status: {},
    error: null,
    ...overrides,
  };
}
