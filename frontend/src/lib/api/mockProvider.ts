import type { ApiClient, JobEventHandlers } from "./client";
import type {
  AnalyzeAccepted,
  AuthResponse,
  AuthUser,
  ContractReport,
  DashboardMetrics,
  JobList,
  JobStatus,
} from "./types";
import {
  acceptedFixture,
  authUserFixture,
  completedStatusFixture,
  dashboardMetricsFixture,
  jobListFixture,
  reportFixture,
  scriptedEvents,
} from "./fixtures";

/**
 * Mock ApiClient (spec AC-14): resolves from static fixtures with ZERO network calls. Used by
 * screens with no backend and for isolated dev. `openJobEvents` emits the scripted sequence
 * via setTimeout, honors unsubscribe, and never hangs for an unknown/finished job (spec EC-2).
 */
export const mockClient: ApiClient = {
  async submitAnalysis(_file: File, _recipient?: string): Promise<AnalyzeAccepted> {
    return { ...acceptedFixture };
  },

  async getJob(jobId: string): Promise<JobStatus> {
    return { ...completedStatusFixture, job_id: jobId };
  },

  openJobEvents(jobId: string, handlers: JobEventHandlers): () => void {
    let cancelled = false;
    const timers: ReturnType<typeof setTimeout>[] = [];
    const events = scriptedEvents(jobId);

    events.forEach((ev, i) => {
      const t = setTimeout(() => {
        if (cancelled) return;
        if (ev.event === "progress") handlers.onProgress?.(ev);
        else handlers.onTerminal?.(ev);
      }, i * 5);
      timers.push(t);
    });

    return () => {
      cancelled = true;
      timers.forEach(clearTimeout);
    };
  },

  getReportUrl(jobId: string, format: "md" | "json"): string {
    return `/api/jobs/${jobId}/report?format=${format}`;
  },

  async getReport(jobId: string): Promise<ContractReport> {
    return { ...reportFixture, document_id: jobId };
  },

  async getJobs(_params?: { limit?: number; offset?: number }): Promise<JobList> {
    return jobListFixture;
  },

  async getDashboardMetrics(): Promise<DashboardMetrics> {
    return dashboardMetricsFixture;
  },

  async health(): Promise<{ status: string }> {
    return { status: "ok" };
  },

  // ── Feature 014 auth — mock is always authenticated (D10); 020 name/title ─
  async signup(
    email: string,
    _password: string,
    name?: string,
    title?: string,
  ): Promise<AuthResponse> {
    return {
      user: {
        ...authUserFixture,
        email: email || authUserFixture.email,
        name: name ?? authUserFixture.name,
        title: title ?? authUserFixture.title,
      },
    };
  },
  async login(_email: string, _password: string): Promise<AuthResponse> {
    return { user: { ...authUserFixture } };
  },
  async logout(): Promise<void> {
    return;
  },
  async me(): Promise<AuthUser> {
    return { ...authUserFixture };
  },
};
