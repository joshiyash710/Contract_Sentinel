import { ApiError, type ApiClient, type JobEventHandlers } from "./client";
import type {
  AnalyzeAccepted,
  AuthResponse,
  AuthUser,
  ContractReport,
  DashboardMetrics,
  JobList,
  JobStatus,
  ProgressEvent,
  SseEventName,
} from "./types";
import { SSE_EVENT_NAMES } from "./types";
import { getConfig } from "@/lib/config";

/**
 * Real ApiClient (spec AC-14): fetch/EventSource against the configured base URL.
 * Feature 014 (D15): every fetch sets credentials:"include" and the EventSource uses
 * withCredentials:true so the cs_session cookie is sent on all calls (AC-18a).
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
      const res = await fetch(`${base()}/api/analyze`, {
        method: "POST",
        body: form,
        credentials: "include",
      });
      return await asJson<AnalyzeAccepted>(res);
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError(`Network error submitting analysis: ${String(err)}`);
    }
  },

  async getJob(jobId: string): Promise<JobStatus> {
    try {
      const res = await fetch(`${base()}/api/jobs/${jobId}`, { credentials: "include" });
      return await asJson<JobStatus>(res);
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError(`Network error fetching job ${jobId}: ${String(err)}`);
    }
  },

  openJobEvents(jobId: string, handlers: JobEventHandlers): () => void {
    const source = new EventSource(`${base()}/api/jobs/${jobId}/events`, {
      withCredentials: true,
    });

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

  async getReport(jobId: string): Promise<ContractReport> {
    try {
      const res = await fetch(`${base()}/api/jobs/${jobId}/report?format=json`, {
        credentials: "include",
      });
      return await asJson<ContractReport>(res);
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError(`Network error fetching report ${jobId}: ${String(err)}`);
    }
  },

  async getJobs(params?: { limit?: number; offset?: number }): Promise<JobList> {
    const q = new URLSearchParams();
    if (params?.limit != null) q.set("limit", String(params.limit));
    if (params?.offset != null) q.set("offset", String(params.offset));
    const qs = q.toString() ? `?${q.toString()}` : "";
    try {
      const res = await fetch(`${base()}/api/jobs${qs}`, { credentials: "include" });
      return await asJson<JobList>(res);
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError(`Network error fetching jobs: ${String(err)}`);
    }
  },

  async getDashboardMetrics(): Promise<DashboardMetrics> {
    try {
      const res = await fetch(`${base()}/api/dashboard`, { credentials: "include" });
      return await asJson<DashboardMetrics>(res);
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError(`Network error fetching dashboard: ${String(err)}`);
    }
  },

  async health(): Promise<{ status: string }> {
    try {
      const res = await fetch(`${base()}/api/health`, { credentials: "include" });
      return await asJson<{ status: string }>(res);
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError(`Network error on health: ${String(err)}`);
    }
  },

  // ── Feature 014 auth (D15 / AC-18a) ──────────────────────────────────────

  async signup(
    email: string,
    password: string,
    name: string,
    title?: string,
  ): Promise<AuthResponse> {
    try {
      const res = await fetch(`${base()}/api/auth/signup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password, name, title }),
        credentials: "include",
      });
      return await asJson<AuthResponse>(res);
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError(`Network error on signup: ${String(err)}`);
    }
  },

  async login(email: string, password: string): Promise<AuthResponse> {
    try {
      const res = await fetch(`${base()}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
        credentials: "include",
      });
      return await asJson<AuthResponse>(res);
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError(`Network error on login: ${String(err)}`);
    }
  },

  async logout(): Promise<void> {
    try {
      const res = await fetch(`${base()}/api/auth/logout`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) throw new ApiError(`HTTP ${res.status}`, res.status);
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError(`Network error on logout: ${String(err)}`);
    }
  },

  async me(): Promise<AuthUser> {
    try {
      const res = await fetch(`${base()}/api/auth/me`, { credentials: "include" });
      const body = await asJson<AuthResponse>(res);
      return body.user;
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError(`Network error on me: ${String(err)}`);
    }
  },
};
