import type {
  AnalyzeAccepted,
  AuthResponse,
  AuthUser,
  ContractReport,
  DashboardMetrics,
  JobList,
  JobStatus,
  ProgressEvent,
} from "./types";

/**
 * The single typed backend surface every screen uses (spec 013 §2.4). Both the mock and real
 * providers implement it; `provider.ts` selects one via a single config flag (spec AC-15),
 * so swapping mock↔real for a screen is a one-place change.
 */
export interface JobEventHandlers {
  onProgress?: (e: ProgressEvent) => void;
  /** Fires on the terminal completed|failed event, which carries `final: JobStatus`. */
  onTerminal?: (e: ProgressEvent) => void;
  onError?: (err: unknown) => void;
}

export interface ApiClient {
  submitAnalysis(file: File, recipient?: string): Promise<AnalyzeAccepted>;
  getJob(jobId: string): Promise<JobStatus>;
  /** Opens the SSE stream; returns an unsubscribe function. */
  openJobEvents(jobId: string, handlers: JobEventHandlers): () => void;
  getReportUrl(jobId: string, format: "md" | "json"): string;
  /** Fetches the report JSON (009 ContractReport). Rejects with ApiError (status preserved:
   * 409 not-ready, 404 unknown/artifact-missing) so callers can branch (spec 017 D7). */
  getReport(jobId: string): Promise<ContractReport>;
  /** Feature 018 — paginated job list for the Activity Feed / contracts list. */
  getJobs(params?: { limit?: number; offset?: number }): Promise<JobList>;
  /** Feature 018 — portfolio aggregate metrics for the dashboard/reports pages. */
  getDashboardMetrics(): Promise<DashboardMetrics>;
  health(): Promise<{ status: string }>;
  // ── Feature 014 auth (AC-19); name/title added in 020 ───────────────────
  signup(email: string, password: string, name: string, title?: string): Promise<AuthResponse>;
  login(email: string, password: string): Promise<AuthResponse>;
  logout(): Promise<void>;
  me(): Promise<AuthUser>;
  // ── Feature 023 account settings ────────────────────────────────────────
  /** Update the caller's own profile (name/title). Returns the refreshed user. */
  updateProfile(body: { name: string; title?: string | null }): Promise<AuthUser>;
  /** Change the caller's own password (verify current, set new). Rejects with ApiError
   * (message = the backend detail, e.g. "Current password is incorrect") on failure. */
  changePassword(body: { current_password: string; new_password: string }): Promise<void>;
}

/** Typed error surfaced by the real provider on network/HTTP failure (spec EC-1). */
export class ApiError extends Error {
  readonly status?: number;
  constructor(message: string, status?: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}
