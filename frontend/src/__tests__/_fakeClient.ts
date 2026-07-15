import { vi } from "vitest";
import type { ApiClient, JobEventHandlers } from "@/lib/api/client";
import type {
  AnalyzeAccepted,
  AuthResponse,
  AuthUser,
  ContractReport,
  DashboardMetrics,
  JobList,
  JobStatus,
  ProgressEvent,
  ReportFinding,
  SseEventName,
} from "@/lib/api/types";
import {
  authUserFixture,
  reportFixture,
  dashboardMetricsFixture,
  jobListFixture,
} from "@/lib/api/fixtures";

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
  report?: ContractReport; // getReport resolves this (feature 017)
  getReportError?: unknown; // getReport rejects this (017 D7: ApiError 409/404 branching)
  dashboard?: DashboardMetrics; // getDashboardMetrics resolves this (feature 018)
  dashboardError?: unknown; // getDashboardMetrics rejects this
  jobList?: JobList; // getJobs resolves this
  jobsError?: unknown; // getJobs rejects this
  // ── Feature 014 auth scripting ──────────────────────────────────────────
  authUser?: AuthUser; // login/signup/me resolve this
  authError?: unknown; // login/signup/me reject this
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
    getReport: vi.fn(async (): Promise<ContractReport> => {
      if (opts.getReportError) throw opts.getReportError;
      return opts.report ?? reportFixture;
    }),
    getJobs: vi.fn(async (): Promise<JobList> => {
      if (opts.jobsError) throw opts.jobsError;
      return opts.jobList ?? jobListFixture;
    }),
    getDashboardMetrics: vi.fn(async (): Promise<DashboardMetrics> => {
      if (opts.dashboardError) throw opts.dashboardError;
      return opts.dashboard ?? dashboardMetricsFixture;
    }),
    health: vi.fn(async () => ({ status: "ok" })),
    // ── Feature 014 auth ─────────────────────────────────────────────────
    signup: vi.fn(
      async (
        _email: string,
        _password: string,
        _name?: string,
        _title?: string,
      ): Promise<AuthResponse> => {
        if (opts.authError) throw opts.authError;
        return { user: opts.authUser ?? authUserFixture };
      },
    ),
    login: vi.fn(async (_email: string, _password: string): Promise<AuthResponse> => {
      if (opts.authError) throw opts.authError;
      return { user: opts.authUser ?? authUserFixture };
    }),
    logout: vi.fn(async (): Promise<void> => {
      if (opts.authError) throw opts.authError;
    }),
    me: vi.fn(async (): Promise<AuthUser> => {
      if (opts.authError) throw opts.authError;
      return opts.authUser ?? authUserFixture;
    }),
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

/** Build a ContractReport from the rich fixture, overriding findings/top-level fields. Summary
 * counts are NOT auto-derived — pass a `summary` override when a test needs specific counts. */
export function reportWith(
  findings: ReportFinding[],
  overrides: Partial<ContractReport> = {},
): ContractReport {
  return { ...reportFixture, findings, ...overrides };
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
