import type { AnalyzeAccepted, JobStatus, ProgressEvent } from "./types";

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
  health(): Promise<{ status: string }>;
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
