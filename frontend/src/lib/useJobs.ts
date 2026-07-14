"use client";

import { useEffect, useState } from "react";
import { getApiClient } from "@/lib/api/provider";
import type { JobList } from "@/lib/api/types";

/** Loads the recent-jobs list for the Activity Feed (feature 018). */
export type JobsPhase = "loading" | "loaded" | "empty" | "error";

export interface JobsState {
  phase: JobsPhase;
  data?: JobList | null;
  message?: string;
}

export function useJobs(params?: { limit?: number; offset?: number }): {
  state: JobsState;
  retry: () => void;
} {
  const [state, setState] = useState<JobsState>({ phase: "loading" });
  const [retryKey, setRetryKey] = useState(0);
  const limit = params?.limit;
  const offset = params?.offset;

  useEffect(() => {
    let cancelled = false;
    setState({ phase: "loading" });
    getApiClient()
      .getJobs({ limit, offset })
      .then((data) => {
        if (cancelled) return;
        setState({ phase: data.total === 0 ? "empty" : "loaded", data });
      })
      .catch(() => {
        if (cancelled) return;
        setState({ phase: "error", message: "We couldn't load recent activity." });
      });
    return () => {
      cancelled = true;
    };
  }, [retryKey, limit, offset]);

  return { state, retry: () => setRetryKey((k) => k + 1) };
}
