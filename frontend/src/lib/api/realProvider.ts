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
import { clearCurrentUser } from "@/lib/useCurrentUser";

/**
 * Real ApiClient (spec AC-14): fetch/EventSource against the configured base URL.
 * Feature 014 (D15): every fetch sets credentials:"include" and the EventSource uses
 * withCredentials:true so the cs_session cookie is sent on all calls (AC-18a).
 */
function base(): string {
  return getConfig().apiBaseUrl;
}

// ── Feature 032 (W2, AC-19): session-expiry handling ──────────────────────────
// Once the user has been authenticated (login / a successful /me), a later 401 means the session
// expired (idle timeout, absolute cap, or a logout-everywhere epoch bump) — clear the cached user
// and hard-navigate to /login. A 401 BEFORE any auth is just the unauthenticated bootstrap probe
// and must NOT redirect (no loop). `redirecting` guards against firing twice.
let sessionActive = false;
let redirecting = false;

function markAuthenticated(): void {
  sessionActive = true;
}

function handleSessionExpired(): void {
  if (redirecting || !sessionActive) return;
  redirecting = true;
  try {
    clearCurrentUser();
  } catch {
    /* best effort */
  }
  if (typeof window !== "undefined") {
    // Hard navigation (not router.replace) so the Next Router Cache can't serve a prior user's
    // authed pages — mirrors the account-switch fix (commit 32cbd03).
    window.location.assign("/login");
  }
}

/** Fire the session-expiry flow when a response is a 401 on a previously-authenticated session. */
function checkAuth(res: Response): void {
  if (res.status === 401) handleSessionExpired();
}

async function asJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    checkAuth(res);
    throw new ApiError(`HTTP ${res.status} for ${res.url}`, res.status);
  }
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
      const body = await asJson<AuthResponse>(res);
      markAuthenticated();
      redirecting = false;
      return body;
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
      const body = await asJson<AuthResponse>(res);
      markAuthenticated(); // now a later 401 means the session expired (AC-19)
      redirecting = false; // allow a fresh expiry cycle after a new login
      return body;
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

  async logoutAll(): Promise<void> {
    try {
      const res = await fetch(`${base()}/api/auth/logout-all`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) {
        checkAuth(res);
        throw new ApiError(`HTTP ${res.status}`, res.status);
      }
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError(`Network error on logout-all: ${String(err)}`);
    }
  },

  async me(): Promise<AuthUser> {
    try {
      const res = await fetch(`${base()}/api/auth/me`, { credentials: "include" });
      const body = await asJson<AuthResponse>(res);
      markAuthenticated(); // a confirmed session — subsequent 401s trigger the expiry flow
      return body.user;
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError(`Network error on me: ${String(err)}`);
    }
  },

  async updateProfile(body: { name: string; title?: string | null }): Promise<AuthUser> {
    try {
      const res = await fetch(`${base()}/api/auth/me`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        credentials: "include",
      });
      return (await asJson<AuthResponse>(res)).user;
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError(`Network error on updateProfile: ${String(err)}`);
    }
  },

  async changePassword(body: {
    current_password: string;
    new_password: string;
  }): Promise<void> {
    try {
      const res = await fetch(`${base()}/api/auth/me/password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        credentials: "include",
      });
      if (!res.ok) {
        checkAuth(res); // a 401 here means the session lapsed mid-edit → redirect
        // Surface the backend detail (e.g. "Current password is incorrect") for the form.
        let detail = `HTTP ${res.status}`;
        try {
          const j = (await res.json()) as { detail?: unknown };
          if (typeof j?.detail === "string") detail = j.detail;
        } catch {
          /* non-JSON body — keep the status message */
        }
        throw new ApiError(detail, res.status);
      }
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError(`Network error on changePassword: ${String(err)}`);
    }
  },

  // ── Feature 031: per-user Google Drive connect ───────────────────────────
  async getGoogleDriveStatus(): Promise<{ connected: boolean; googleEmail?: string | null }> {
    try {
      const res = await fetch(`${base()}/api/integrations/google/status`, {
        credentials: "include",
      });
      const body = await asJson<{ connected: boolean; google_email?: string | null }>(res);
      return { connected: body.connected, googleEmail: body.google_email ?? null };
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError(`Network error fetching Drive status: ${String(err)}`);
    }
  },

  googleDriveAuthorizeUrl(): string {
    // Absolute URL so the top-level browser navigation lands on the backend (:8000)
    // and carries the session cookie (feature 031 plan §4).
    return `${base()}/api/integrations/google/authorize`;
  },

  async disconnectGoogleDrive(): Promise<void> {
    try {
      const res = await fetch(`${base()}/api/integrations/google/disconnect`, {
        method: "POST",
        credentials: "include",
      });
      await asJson<unknown>(res);
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError(`Network error disconnecting Drive: ${String(err)}`);
    }
  },
};
