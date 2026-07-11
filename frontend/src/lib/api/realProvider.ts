import { ApiError, type ApiClient, type JobEventHandlers } from "./client";
import type { AnalyzeAccepted, JobStatus, ProgressEvent, SseEventName } from "./types";
import { SSE_EVENT_NAMES } from "./types";
import { getConfig } from "@/lib/config";

/**
 * Real ApiClient (spec AC-14): fetch/EventSource against the configured base URL, mapping all
 * five 011 endpoints. Base URL defaults to "" (same-origin → Next.js dev proxy, Q4). Network/
 * HTTP failures are wrapped in a typed ApiError, never thrown through raw (spec EC-1).
 */
function base(): string {
  return getConfig().apiBaseUrl;
}

async function asJson<T>(res: Response): Promise<T> {
  if (!res.ok) throw new ApiError(`HTTP ${res.status} for ${res.url}`, res.status);
  return (await res.json()) as T;
}

export const realClient: ApiClient = {
  async submitAnalysis(file: File, recipient?: string): Promise<AnalyzeAccepted> {
    const form = new FormData();
    form.append("file", file);
    if (recipient) form.append("recipient", recipient);
    try {
      const res = await fetch(`${base()}/api/analyze`, { method: "POST", body: form });
      return await asJson<AnalyzeAccepted>(res);
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError(`Network error submitting analysis: ${String(err)}`);
    }
  },

  async getJob(jobId: string): Promise<JobStatus> {
    try {
      const res = await fetch(`${base()}/api/jobs/${jobId}`);
      return await asJson<JobStatus>(res);
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError(`Network error fetching job ${jobId}: ${String(err)}`);
    }
  },

  openJobEvents(jobId: string, handlers: JobEventHandlers): () => void {
    const source = new EventSource(`${base()}/api/jobs/${jobId}/events`);

    const dispatch = (name: SseEventName) => (evt: MessageEvent) => {
      try {
        const data = JSON.parse(evt.data) as ProgressEvent;
        if (name === "progress") handlers.onProgress?.(data);
        else handlers.onTerminal?.(data);
      } catch (err) {
        handlers.onError?.(err);
      }
      if (name === "completed" || name === "failed") source.close();
    };

    const registered: Array<[SseEventName, (e: MessageEvent) => void]> = SSE_EVENT_NAMES.map(
      (name) => {
        const cb = dispatch(name);
        source.addEventListener(name, cb as EventListener);
        return [name, cb];
      },
    );

    source.onerror = (e) => handlers.onError?.(e);

    return () => {
      registered.forEach(([name, cb]) => source.removeEventListener(name, cb as EventListener));
      source.close();
    };
  },

  getReportUrl(jobId: string, format: "md" | "json"): string {
    return `${base()}/api/jobs/${jobId}/report?format=${format}`;
  },

  async health(): Promise<{ status: string }> {
    try {
      const res = await fetch(`${base()}/api/health`);
      return await asJson<{ status: string }>(res);
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError(`Network error on health: ${String(err)}`);
    }
  },
};
