"use client";

import { useEffect, useState } from "react";
import { getApiClient } from "@/lib/api/provider";
import type { DashboardMetrics } from "@/lib/api/types";

/**
 * Loads portfolio aggregates for /dashboard + /reports (feature 018). Discriminated state:
 * `empty` when there are no contracts yet (D11) so the views show a real empty state rather
 * than zero-charts. Reaches the backend only via getApiClient() (spec AC-18).
 */
export type DashboardPhase = "loading" | "loaded" | "empty" | "error";

export interface DashboardState {
  phase: DashboardPhase;
  data?: DashboardMetrics | null;
  message?: string;
}

export function useDashboard(): { state: DashboardState; retry: () => void } {
  const [state, setState] = useState<DashboardState>({ phase: "loading" });
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setState({ phase: "loading" });
    getApiClient()
      .getDashboardMetrics()
      .then((data) => {
        if (cancelled) return;
        setState({ phase: data.total_contracts === 0 ? "empty" : "loaded", data });
      })
      .catch(() => {
        if (cancelled) return;
        setState({ phase: "error", message: "We couldn't load your dashboard metrics." });
      });
    return () => {
      cancelled = true;
    };
  }, [retryKey]);

  return { state, retry: () => setRetryKey((k) => k + 1) };
}
