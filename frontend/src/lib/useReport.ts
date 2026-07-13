"use client";

import { useEffect, useState } from "react";
import { getApiClient } from "@/lib/api/provider";
import { ApiError } from "@/lib/api/client";
import type { ContractReport } from "@/lib/api/types";

/**
 * Loads the 009 ContractReport for a job and applies the D7 direct-navigation guard
 * (spec 017 §2.3 D7, INV-1/INV-2). Navigation stays in the component (`redirecting` is a
 * phase, not an in-hook router call) so it's test-observable. Reaches the backend only via
 * getApiClient() (spec AC-15).
 */
export type ReportPhase =
  | "loading"
  | "loaded"
  | "redirecting" // 409, or a non-terminal job → go watch it finish (D1 brings the user back)
  | "not_found" // 404 + unknown job (INV-2 unknown case)
  | "artifact_unavailable" // 404 + completed job (INV-2 out-of-band file loss)
  | "error"; // network / parse (EC-3)

export interface ReportState {
  phase: ReportPhase;
  report?: ContractReport | null;
  message?: string;
}

export function useReport(jobId: string): { state: ReportState; retry: () => void } {
  const [state, setState] = useState<ReportState>({ phase: "loading" });
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    const client = getApiClient();
    let cancelled = false;

    const load = async () => {
      setState({ phase: "loading" });
      try {
        const report = await client.getReport(jobId);
        if (cancelled) return;
        setState({ phase: "loaded", report });
      } catch (err) {
        if (cancelled) return;
        const status = err instanceof ApiError ? err.status : undefined;

        if (status === 409) {
          setState({ phase: "redirecting" });
          return;
        }
        if (status === 404) {
          // Ambiguous: unknown job OR a completed job whose file is gone (INV-2).
          // Disambiguate with getJob.
          try {
            const job = await client.getJob(jobId);
            if (cancelled) return;
            if (job.status === "completed") {
              setState({ phase: "artifact_unavailable" });
            } else {
              // still queued/running → treat like 409 (watch it finish)
              setState({ phase: "redirecting" });
            }
          } catch {
            if (cancelled) return;
            setState({ phase: "not_found" });
          }
          return;
        }
        setState({ phase: "error", message: "We couldn't load the report." });
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [jobId, retryKey]);

  return { state, retry: () => setRetryKey((k) => k + 1) };
}
