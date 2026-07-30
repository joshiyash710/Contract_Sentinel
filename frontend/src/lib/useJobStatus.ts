"use client";

import { useEffect, useState } from "react";
import { getApiClient } from "@/lib/api/provider";
import type { JobStatus } from "@/lib/api/types";
import { nodeIndex, TOTAL_STEPS } from "@/lib/jobProgress";

export type JobPhase = "connecting" | "running" | "completed" | "failed" | "error";

export interface JobEventsState {
  phase: JobPhase;
  node?: string | null;
  index?: number | null;
  total?: number | null;
  completedNodes: string[];
  final?: JobStatus | null; // set on completed/failed
  errorMessage?: string; // connection-phase text only (EC-3/5/6)
}

export const POLL_INTERVAL_MS = 2500;
// During the CPU/GPU-heavy local-LLM run the API can blip; tolerate a few consecutive
// failures before surfacing an error so a single hiccup doesn't kill the progress screen.
export const MAX_CONSECUTIVE_POLL_FAILURES = 5;

function mapStatus(js: JobStatus): JobEventsState {
  const phase: JobPhase =
    js.status === "completed"
      ? "completed"
      : js.status === "failed"
        ? "failed"
        : js.status === "queued"
          ? "connecting"
          : "running";
  const terminal = phase === "completed" || phase === "failed";
  return {
    phase,
    node: js.current_node,
    index: nodeIndex(js.current_node),
    total: TOTAL_STEPS,
    completedNodes: js.completed_nodes ?? [],
    final: terminal ? js : null,
  };
}

/**
 * Drives the processing screen by POLLING `GET /api/jobs/{id}` (spec 015 D7). SSE buffers through
 * the Next dev proxy, so polling is the reliable transport. Polls on mount until a terminal
 * status; `reconnect()` restarts polling (EC-5/EC-6). Reaches the backend only via getApiClient().
 */
export function useJobStatus(jobId: string): { state: JobEventsState; reconnect: () => void } {
  const [state, setState] = useState<JobEventsState>({
    phase: "connecting",
    completedNodes: [],
    total: TOTAL_STEPS,
  });
  const [reconnectKey, setReconnectKey] = useState(0);

  useEffect(() => {
    const client = getApiClient();
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let failures = 0;

    const tick = async () => {
      try {
        const js = await client.getJob(jobId);
        if (stopped) return;
        failures = 0; // a successful poll clears the transient-failure streak
        const next = mapStatus(js);
        setState(next);
        if (next.phase === "completed" || next.phase === "failed") return; // stop polling
      } catch {
        if (stopped) return;
        failures += 1;
        // Only surface an error after SUSTAINED failures — a single blip during the heavy
        // local-LLM run must NOT drop the progress screen (EC-5). Below the threshold we keep
        // polling silently (the last known progress stays on screen).
        if (failures >= MAX_CONSECUTIVE_POLL_FAILURES) {
          setState((s) =>
            s.phase === "completed" || s.phase === "failed"
              ? s
              : {
                  ...s,
                  phase: "error",
                  errorMessage: "Couldn't reach the analysis. Try refreshing.",
                },
          );
          return; // give up after sustained failures; the user can Refresh
        }
        // else: transient — fall through and schedule the next poll
      }
      timer = setTimeout(tick, POLL_INTERVAL_MS);
    };
    tick();

    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, [jobId, reconnectKey]);

  return { state, reconnect: () => setReconnectKey((k) => k + 1) };
}
