"use client";

import { useEffect, useState } from "react";
import { getApiClient } from "@/lib/api/provider";
import type { JobStatus, ProgressEvent } from "@/lib/api/types";

export type JobPhase = "connecting" | "running" | "completed" | "failed" | "error";

export interface JobEventsState {
  phase: JobPhase;
  node?: string | null; // last progress node
  index?: number | null;
  total?: number | null;
  completedNodes: string[]; // ordered, for the step trace
  final?: JobStatus | null; // set on completed/failed
  errorMessage?: string; // connection-phase text only (EC-3/5/6) — NOT the ingest-error message
}

/**
 * Drives the processing screen from the SSE stream (spec 015 §2 / plan §3.3). Subscribes on
 * mount, unsubscribes on unmount (AC-9). Bumping `reconnect()` re-runs the effect → re-opens the
 * stream (011's per-job buffer replays, so a manual refresh recovers — OQ3/EC-5/EC-6).
 */
export function useJobEvents(jobId: string): {
  state: JobEventsState;
  reconnect: () => void;
} {
  const [state, setState] = useState<JobEventsState>({ phase: "connecting", completedNodes: [] });
  const [reconnectKey, setReconnectKey] = useState(0);

  useEffect(() => {
    const client = getApiClient();
    let closed = false;
    const stop = client.openJobEvents(jobId, {
      onProgress: (e: ProgressEvent) => {
        if (closed) return;
        setState((s) => ({
          ...s,
          phase: "running",
          node: e.node,
          index: e.index,
          total: e.total,
          completedNodes: e.node ? [...s.completedNodes, e.node] : s.completedNodes,
        }));
      },
      onTerminal: (e: ProgressEvent) => {
        if (closed) return;
        // Do NOT copy final.error.message into errorMessage (review B1) — the completed-with-
        // issue branch reads state.final?.error directly; a normal completion has error == null.
        setState((s) => ({
          ...s,
          phase: e.event === "completed" ? "completed" : "failed",
          final: e.final ?? null,
        }));
      },
      onError: () => {
        if (closed) return;
        // 404 (unknown/evicted job, EC-6) or a dropped connection (EC-5) land here; show a
        // recoverable state with a manual refresh, unless we already reached a terminal state.
        setState((s) =>
          s.phase === "completed" || s.phase === "failed"
            ? s
            : { ...s, phase: "error", errorMessage: "Lost connection to the analysis stream." },
        );
      },
    });
    return () => {
      closed = true;
      stop();
    };
  }, [jobId, reconnectKey]);

  return { state, reconnect: () => setReconnectKey((k) => k + 1) };
}
